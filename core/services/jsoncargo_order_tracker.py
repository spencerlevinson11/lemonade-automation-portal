from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from core.models import OrderContainer, OrderContainerTrackingUpdate
from core.services.jsoncargo import fetch_container_tracking, fetch_bill_of_lading_lookup


def _parse_date(val: str | None) -> dt.date | None:
    """Parse JSONCargo timestamps like '2026-02-22 07:00' into a date."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None
def _parse_dt(val: str | None) -> dt.datetime | None:
    """Parse JSONCargo timestamps to a timezone-aware datetime when possible."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            naive = dt.datetime.strptime(s, fmt)
            return timezone.make_aware(naive, timezone.get_current_timezone())
        except Exception:
            continue
    try:
        naive = dt.datetime.strptime(s, "%Y-%m-%d")
        return timezone.make_aware(naive, timezone.get_current_timezone())
    except Exception:
        return None


def normalize_city(raw: str | None) -> str:
    """Reduce noisy destination strings to a clean city-like label.

    Example:
      'Miami SOUTH FLORIDA CONTAINER TERM N775 United States' -> 'Miami'
    """
    if not raw:
        return ""
    s = " ".join(str(raw).strip().split())  # collapse whitespace
    if not s:
        return ""

    lower = s.lower()

    # Strip country tails
    for token in [" united states", " usa", " us"]:
        idx = lower.find(token)
        if idx != -1:
            s = s[:idx].strip()
            lower = s.lower()

    # Strip common terminal/port descriptors
    stop_words = [
        " terminal",
        " container",
        " term",
        " port",
        " ramp",
        " rail",
        " depot",
        " yard",
        " facility",
    ]
    cut_idx = None
    for w in stop_words:
        idx = lower.find(w)
        if idx != -1:
            if cut_idx is None or idx < cut_idx:
                cut_idx = idx
    if cut_idx is not None:
        s = s[:cut_idx].strip()

    s = " ".join(s.split())
    if not s:
        return ""

    # If it's all caps or mostly caps, title-case it for display.
    letters = [ch for ch in s if ch.isalpha()]
    if letters:
        caps = sum(1 for ch in letters if ch.isupper())
        if caps / len(letters) > 0.7:
            s = s.title()

    return s




def tracking_reference_for_jsoncargo(container: OrderContainer) -> str:
    """Return the tracking reference to send to JSONCargo's container endpoint.

    JSONCargo's /api/v1/containers/{tracking_number} endpoint expects a true
    container number such as TXGU7347900. Booking/BOL references can be useful
    for lookup/validation through JSONCargo's separate BOL endpoint, but they
    should not replace the container number in the normal container-tracking
    request.
    """
    return (getattr(container, "container_number", "") or "").strip()


def _extract_eta(data: Dict[str, Any]) -> dt.date | None:
    """Extract the most useful ETA from JSONCargo's possible ETA fields."""
    return _parse_date(
        data.get("eta_final_destination")
        or data.get("eta_next_destination")
        or data.get("eta_destination")
        or data.get("eta")
        or data.get("eta_delivery")
        or data.get("eta_discharge")
    )


def _extract_city(data: Dict[str, Any]) -> str:
    """Extract a useful destination/next-destination city from JSONCargo."""
    raw_city = (
        data.get("final_destination")
        or data.get("final_destination_port")
        or data.get("final_destination_city")
        or data.get("destination")
        or data.get("delivery_to")
        or data.get("delivered_to")
        or data.get("consignee_city")
        or data.get("shipped_to")
        or data.get("next_location")
        or data.get("discharging_port")
        or ""
    )
    return normalize_city(str(raw_city).strip())

def sync_all_containers(
    *,
    api_key: str | None = None,
    queryset=None,
    limit: int | None = 500,
    include_delivered: bool = False,
    include_archived: bool = False,
) -> Dict[str, int]:
    """Sync JSONCargo tracking for many containers in one call.

    This mirrors the Order Tracker "Sync JSON updates" button behavior:
    - Skips blank container numbers
    - Skips archived by default
    - Skips Delivered by default

    Returns a small stats dict you can print/log.

    Notes
    -----
    * If api_key is not provided, this reads JSONCARGO_API_KEY from the
      environment (Render env vars).
    * This function does NOT auto-apply pending updates; it only creates/updates
      OrderContainerTrackingUpdate pending records (same as sync_one_container).
    """
    if api_key is None:
        api_key = os.getenv("JSONCARGO_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("JSONCARGO_API_KEY is not set")

    qs = queryset if queryset is not None else OrderContainer.objects.all()

    # Only sync containers that actually have a container number entered.
    qs = qs.exclude(container_number__isnull=True).exclude(container_number__exact="")
    qs = qs.exclude(container_number__regex=r"^\s*$")

    if not include_archived:
        qs = qs.filter(is_archived=False)
    if not include_delivered:
        qs = qs.exclude(status__iexact="Delivered")

    if limit is not None:
        qs = qs.order_by("-updated_at", "-created_at")[:limit]

    stats = {"checked": 0, "created": 0, "updated": 0, "skipped": 0, "errors": 0}
    for c in qs:
        stats["checked"] += 1
        try:
            result, _pending = sync_one_container(c, api_key=api_key)
        except Exception:
            stats["errors"] += 1
            continue

        if result in ("error_note_created", "error_note_updated"):
            stats["errors"] += 1
        elif result == "skipped_no_data":
            stats["skipped"] += 1
        elif result in ("change_created", "no_change_created"):
            stats["created"] += 1
        elif result in ("change_updated", "no_change_updated"):
            stats["updated"] += 1
        else:
            stats["skipped"] += 1

    return stats

def _should_retry_without_shipping_line(err) -> bool:
    """Return True when JSONCargo may succeed if provider auto-detects the carrier.

    Some valid leased-container prefixes are not mapped to the selected carrier in
    JSONCargo. In those cases JSONCargo may reject the prefix when we force a
    provider, even though a provider-less lookup can still work. We also retry
    provider-less on JSONCargo 500s because those are often carrier/provider
    lookup failures with no useful payload.
    """
    if not err:
        return False
    message = (getattr(err, "message", "") or "").lower()
    if getattr(err, "status_code", None) == 400 and "prefix not found" in message:
        return True
    if getattr(err, "status_code", None) in (404, 500):
        return True
    return False


def _save_jsoncargo_error(
    *,
    container: OrderContainer,
    msg: str,
    payload: Dict[str, Any] | None,
) -> Tuple[str, OrderContainerTrackingUpdate]:
    """Create/update the pending JSONCargo error note for a container."""
    pending = (
        OrderContainerTrackingUpdate.objects.filter(
            container=container,
            status=OrderContainerTrackingUpdate.STATUS_PENDING,
            kind=OrderContainerTrackingUpdate.KIND_ERROR,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    if pending:
        pending.note = msg
        pending.source_payload = payload or {}
        pending.source_last_updated = timezone.now()
        pending.proposed_eta = None
        pending.proposed_eta_city = ""
        pending.save(update_fields=[
            "note",
            "source_payload",
            "source_last_updated",
            "proposed_eta",
            "proposed_eta_city",
            "updated_at",
        ])
        return ("error_note_updated", pending)

    new_obj = OrderContainerTrackingUpdate.objects.create(
        container=container,
        kind=OrderContainerTrackingUpdate.KIND_ERROR,
        note=msg,
        proposed_eta=None,
        proposed_eta_city="",
        source_last_updated=timezone.now(),
        source_payload=payload or {},
        status=OrderContainerTrackingUpdate.STATUS_PENDING,
    )
    return ("error_note_created", new_obj)

def _save_jsoncargo_no_data_note(
    *,
    container: OrderContainer,
    msg: str,
    payload: Dict[str, Any] | None,
) -> Tuple[str, OrderContainerTrackingUpdate]:
    """Create/update a visible pending note when JSONCargo returns no usable ETA/city data.

    This intentionally uses KIND_ERROR so the Order Tracker surfaces it instead
    of silently counting the container as skipped. These are not application
    crashes; they are tracking lookups that produced no actionable update.
    """
    return _save_jsoncargo_error(container=container, msg=msg, payload=payload)


def _jsoncargo_data(payload: Dict[str, Any] | None) -> Dict[str, Any]:
    """Return the most likely shipment-data dict from a JSONCargo response."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    # Some endpoints/providers return shipment fields at the top level.
    return payload


def _tracking_reference_candidates(container: OrderContainer) -> list[str]:
    """Return BOL/booking references to try after container-number failures."""
    refs: list[str] = []
    for attr in ("booking_number", "bill_of_lading_number"):
        value = (getattr(container, attr, "") or "").strip()
        if value and value not in refs:
            refs.append(value)
    return refs


def _attempt_container_lookup(
    *,
    tracking_reference: str,
    api_key: str,
    shipping_line: str | None,
) -> tuple[dict[str, Any] | None, Any, list[dict[str, Any]]]:
    """Try container tracking with selected carrier, then auto-detect fallback.

    Returns (tracking, err, attempts). err is None on success.
    """
    attempts: list[dict[str, Any]] = []

    tracking, err = fetch_container_tracking(
        container_number=tracking_reference,
        api_key=api_key,
        shipping_line=shipping_line,
    )
    attempts.append({
        "type": "container",
        "tracking_reference": tracking_reference,
        "shipping_line": shipping_line,
        "status_code": getattr(err, "status_code", 200 if err is None else None),
        "message": getattr(err, "message", "success" if err is None else ""),
        "payload": (tracking if err is None else (getattr(err, "payload", None) or {})),
    })
    if err is None:
        return tracking, None, attempts

    if shipping_line and _should_retry_without_shipping_line(err):
        fallback_tracking, fallback_err = fetch_container_tracking(
            container_number=tracking_reference,
            api_key=api_key,
            shipping_line=None,
        )
        attempts.append({
            "type": "container_auto_detect",
            "tracking_reference": tracking_reference,
            "shipping_line": None,
            "status_code": getattr(fallback_err, "status_code", 200 if fallback_err is None else None),
            "message": getattr(fallback_err, "message", "success" if fallback_err is None else ""),
            "payload": (fallback_tracking if fallback_err is None else (getattr(fallback_err, "payload", None) or {})),
        })
        if fallback_err is None:
            if isinstance(fallback_tracking, dict):
                fallback_tracking = {
                    **fallback_tracking,
                    "jsoncargo_fallback": {
                        "used_without_shipping_line": True,
                        "first_attempt": attempts[0],
                    },
                }
            return fallback_tracking, None, attempts
        return fallback_tracking, fallback_err, attempts

    return tracking, err, attempts


def _attempt_booking_lookup_then_container(
    *,
    container: OrderContainer,
    api_key: str,
    shipping_line: str | None,
    original_container_number: str,
) -> tuple[dict[str, Any] | None, Any, list[dict[str, Any]]]:
    """Try booking/BOL lookup, then track associated containers normally."""
    attempts: list[dict[str, Any]] = []
    refs = _tracking_reference_candidates(container)
    last_tracking = None
    last_err = None

    for ref in refs:
        # JSONCargo requires shipping_line for BOL/booking lookups. When the
        # order has a selected carrier, always include it. Do not make a final
        # provider-less BOL/booking retry because JSONCargo returns an avoidable
        # 400: "Missing required parameter shipping_line".
        bol_shipping_lines = [shipping_line] if shipping_line else [None]
        for bol_shipping_line in bol_shipping_lines:
            bol_tracking, bol_err = fetch_bill_of_lading_lookup(
                bill_of_lading_number=ref,
                api_key=api_key,
                shipping_line=bol_shipping_line,
            )
            attempts.append({
                "type": "bol_booking_lookup",
                "tracking_reference": ref,
                "shipping_line": bol_shipping_line,
                "status_code": getattr(bol_err, "status_code", 200 if bol_err is None else None),
                "message": getattr(bol_err, "message", "success" if bol_err is None else ""),
                "payload": (bol_tracking if bol_err is None else (getattr(bol_err, "payload", None) or {})),
            })
            if bol_err is not None:
                last_tracking, last_err = bol_tracking, bol_err
                continue

            data = _jsoncargo_data(bol_tracking)
            associated = data.get("associated_container_numbers") or data.get("containers") or data.get("container_numbers") or []
            if isinstance(associated, str):
                associated = [associated]
            normalized_associated: list[str] = []
            for item in associated:
                if isinstance(item, dict):
                    item = item.get("container_number") or item.get("number") or item.get("tracking_number") or ""
                item_s = str(item or "").strip()
                if item_s:
                    normalized_associated.append(item_s)
            associated = normalized_associated

            # Prefer the actual container stored on the order when it appears in
            # the booking/BOL response, then try any associated containers.
            ordered_candidates: list[str] = []
            if original_container_number:
                ordered_candidates.append(original_container_number)
            for num in associated:
                if num not in ordered_candidates:
                    ordered_candidates.append(num)

            if not ordered_candidates:
                continue

            for candidate in ordered_candidates:
                candidate_tracking, candidate_err, candidate_attempts = _attempt_container_lookup(
                    tracking_reference=candidate,
                    api_key=api_key,
                    shipping_line=shipping_line,
                )
                # Mark nested attempts so diagnostics make it obvious that these
                # were reached via the booking/BOL reference.
                for a in candidate_attempts:
                    a["via_bol_or_booking"] = ref
                    a["associated_container_numbers"] = associated
                attempts.extend(candidate_attempts)
                last_tracking, last_err = candidate_tracking, candidate_err
                if candidate_err is None:
                    if isinstance(candidate_tracking, dict):
                        candidate_tracking = {
                            **candidate_tracking,
                            "jsoncargo_booking_fallback": {
                                "used_reference": ref,
                                "associated_container_numbers": associated,
                                "attempts": attempts,
                            },
                        }
                    return candidate_tracking, None, attempts

    return last_tracking, last_err, attempts


@transaction.atomic
def sync_one_container(
    container: OrderContainer,
    *,
    api_key: str,
) -> Tuple[str, Optional[OrderContainerTrackingUpdate]]:
    """Fetch JSONCargo, compare to current tracker, and create/update a pending record.

    Returns (result, pending_obj)
      result:
        - 'change_created' / 'change_updated'
        - 'no_change_created' / 'no_change_updated'
        - 'skipped_no_data'
        - 'error_note_created' / 'error_note_updated'
    """
    shipping_line = container.jsoncargo_shipping_line_param()
    tracking_reference = tracking_reference_for_jsoncargo(container)

    tracking, err, attempts = _attempt_container_lookup(
        tracking_reference=tracking_reference,
        api_key=api_key,
        shipping_line=shipping_line,
    )

    # If the normal container-number lookup fails, try the booking/BOL number.
    # JSONCargo's BOL endpoint usually returns associated container numbers, so
    # we then track those associated containers through the normal container
    # endpoint to obtain ETA/city fields.
    if err and _tracking_reference_candidates(container):
        booking_tracking, booking_err, booking_attempts = _attempt_booking_lookup_then_container(
            container=container,
            api_key=api_key,
            shipping_line=shipping_line,
            original_container_number=tracking_reference,
        )
        attempts.extend(booking_attempts)
        if booking_err is None:
            tracking = booking_tracking
            err = None
        else:
            tracking = booking_tracking
            err = booking_err

    if err:
        # Create a pending "error" note so the user sees that tracking did not run.
        msg = f"JSONCargo error ({err.status_code}): {err.message}"

        payload: Dict[str, Any] = {
            "tracking_reference": tracking_reference,
            "selected_shipping_line": shipping_line,
            "booking_number": (getattr(container, "booking_number", "") or "").strip(),
            "bill_of_lading_number": (getattr(container, "bill_of_lading_number", "") or "").strip(),
            "attempts": attempts,
            "final_attempt": attempts[-1] if attempts else {
                "shipping_line": shipping_line,
                "status_code": err.status_code,
                "message": err.message,
                "payload": err.payload or {},
            },
        }

        if len(attempts) > 1:
            msg = (
                f"JSONCargo error after {len(attempts)} attempt(s) ({err.status_code}): {err.message}. "
                "The app tried the selected carrier, carrier auto-detect where appropriate, and any booking/BOL reference available with its required shipping line."
            )
        elif err.status_code == 404:
            if shipping_line:
                msg += f". Not found under shipping line '{shipping_line}'."
            else:
                msg += ". Try setting a Carrier (shipping line) for this container and re-sync."
        elif err.status_code == 400 and "prefix not found" in (err.message or "").lower():
            msg += ". JSONCargo does not recognize this container prefix for the selected carrier."
        elif err.status_code == 500:
            msg += ". JSONCargo returned an internal/provider error for this container."

        return _save_jsoncargo_error(container=container, msg=msg, payload=payload)

    data: Dict[str, Any] = _jsoncargo_data(tracking)

    # Auto-learn shipping line id from JSONCargo when available.
    resp_line_id = str(data.get("shipping_line_id") or "").strip()
    if resp_line_id and not (container.shipping_line_id or "").strip():
        container.shipping_line_id = resp_line_id
        container.save(update_fields=["shipping_line_id", "updated_at"])

    # Prefer ETA to final destination when present; fall back to next destination
    # and other common ETA fields. This fixes cases where the diagnostic payload
    # has an ETA but the app was only reading a different JSONCargo field.
    proposed_eta = _extract_eta(data)

    # Choose a destination label for display. JSONCargo sometimes returns a
    # discharge/transshipment port when the final delivery city is blank, so we
    # try final-destination fields first, then next_location, then discharge.
    proposed_city = _extract_city(data)
    source_last_updated = _parse_dt(data.get("last_updated"))

    if proposed_eta is None and not proposed_city:
        payload: Dict[str, Any] = {
            "tracking_reference": tracking_reference,
            "selected_shipping_line": shipping_line,
            "booking_number": (getattr(container, "booking_number", "") or "").strip(),
            "bill_of_lading_number": (getattr(container, "bill_of_lading_number", "") or "").strip(),
            "attempts": attempts,
            "final_attempt": attempts[-1] if attempts else None,
            "tracking_response": tracking or {},
            "extracted_data": data,
        }
        msg = (
            "JSONCargo returned a successful response, but the app could not find "
            "a usable ETA or destination city in the response."
        )
        if attempts:
            msg += f" The app made {len(attempts)} lookup attempt(s), including any available booking/BOL reference."
        return _save_jsoncargo_no_data_note(container=container, msg=msg, payload=payload)

    same_eta = proposed_eta == container.eta
    same_city = (proposed_city or "") == (container.eta_city or "")

    pending = (
        OrderContainerTrackingUpdate.objects.filter(
            container=container,
            status=OrderContainerTrackingUpdate.STATUS_PENDING,
        )
        .order_by("-created_at", "-id")
        .first()
    )

    if same_eta and same_city:
        note_text = "Last API check was the same as current in tracker."
        if pending and pending.kind == OrderContainerTrackingUpdate.KIND_NO_CHANGE:
            pending.note = note_text
            pending.source_last_updated = source_last_updated
            pending.source_payload = tracking or {}
            pending.proposed_eta = proposed_eta
            pending.proposed_eta_city = proposed_city
            pending.save(
                update_fields=[
                    "note",
                    "source_last_updated",
                    "source_payload",
                    "proposed_eta",
                    "proposed_eta_city",
                    "updated_at",
                ]
            )
            return ("no_change_updated", pending)

        # If there is a change-pending record but the API now matches current,
        # we still show a note (and leave the old change pending record alone).
        if pending and pending.kind == OrderContainerTrackingUpdate.KIND_CHANGE:
            # create a new no-change note instead of overwriting a real pending change
            pending = None

        new_obj = OrderContainerTrackingUpdate.objects.create(
            container=container,
            kind=OrderContainerTrackingUpdate.KIND_NO_CHANGE,
            note=note_text,
            proposed_eta=proposed_eta,
            proposed_eta_city=proposed_city,
            source_last_updated=source_last_updated,
            source_payload=tracking or {},
            status=OrderContainerTrackingUpdate.STATUS_PENDING,
        )
        return ("no_change_created", new_obj)

    # There is a proposed change.
    if pending and pending.kind == OrderContainerTrackingUpdate.KIND_CHANGE:
        pending.proposed_eta = proposed_eta
        pending.proposed_eta_city = proposed_city
        pending.source_last_updated = source_last_updated
        pending.source_payload = tracking or {}
        pending.note = ""  # clear
        pending.save(
            update_fields=[
                "proposed_eta",
                "proposed_eta_city",
                "source_last_updated",
                "source_payload",
                "note",
                "updated_at",
            ]
        )
        return ("change_updated", pending)

    new_obj = OrderContainerTrackingUpdate.objects.create(
        container=container,
        kind=OrderContainerTrackingUpdate.KIND_CHANGE,
        proposed_eta=proposed_eta,
        proposed_eta_city=proposed_city,
        source_last_updated=source_last_updated,
        source_payload=tracking or {},
        status=OrderContainerTrackingUpdate.STATUS_PENDING,
    )
    return ("change_created", new_obj)





























