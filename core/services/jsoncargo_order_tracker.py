from __future__ import annotations

import datetime as dt
import os
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from django.utils import timezone

from core.models import OrderContainer, OrderContainerTrackingUpdate
from core.services.jsoncargo import fetch_container_tracking


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
        - 'error'
    """
    shipping_line = container.jsoncargo_shipping_line_param()
    tracking_reference = tracking_reference_for_jsoncargo(container)
    tracking, err = fetch_container_tracking(
        container_number=tracking_reference,
        api_key=api_key,
        shipping_line=shipping_line,
    )
    if err:
        # Create a pending "error" note so the user sees that tracking did not run.
        # Common cause: container prefix requires shipping_line but it was missing/wrong.
        msg = f"JSONCargo error ({err.status_code}): {err.message}"
        if tracking_reference and tracking_reference != (container.container_number or "").strip():
            msg += f". Tracking reference used: {tracking_reference}."
        if err.status_code == 404:
            if shipping_line:
                msg += f". Not found under shipping line '{shipping_line}'."
            else:
                msg += ". Try setting a Carrier (shipping line) for this container and re-sync."
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
            pending.source_payload = (err.payload or {})
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
            source_payload=(err.payload or {}),
            status=OrderContainerTrackingUpdate.STATUS_PENDING,
        )
        return ("error_note_created", new_obj)

    data: Dict[str, Any] = (tracking or {}).get("data") or {}

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
        return ("skipped_no_data", None)

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










