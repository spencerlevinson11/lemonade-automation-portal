from __future__ import annotations

from typing import Any, Dict, Optional

from django.db import transaction

from ..models import Company, OrderContainer, OrderContainerLine
from ..rpc_generation import BUCKET_FIELD_MAP, PER_PALLET


CONTACT_TO_OWNER = {
    "spencer": "Spencer",
    "jaime": "Jaime",
}

# Elite and Sunshine use a common description in the Order Tracker / recaps for
# these five classic bucket variants. The generated RPC workbook keeps the
# original, more specific bucket type selected by the user.
CLASSIC_TRACKER_CUSTOMER_BUCKETS = {
    "10 Wide Standard Classic x 2520",
    "10 Wide Standard Classic x 2660",
    "10 Wide Standard Classic x 2800",
    "10 liter classic N6+ 2520",
    "10 liter wide classic + x 2800",
}
CLASSIC_TRACKER_DESCRIPTION = "10 liter wide classic"

NIR_GREY_RPC_DESCRIPTION = "10 liter wide NIR Grey classic x 2800"
NIR_GREY_TRACKER_DESCRIPTION = "10 liter wide classic NIR grey x 2800"


def order_tracker_bucket_description(bucket_name: str, customer_name: str) -> str:
    """Return the bucket description that should be stored in Order Tracker.

    RPC generation still uses the canonical RPC bucket name. These aliases are
    intentionally tracker-only so the RPC workbook remains unchanged.
    """
    bucket_name = (bucket_name or "").strip()
    customer_lower = (customer_name or "").strip().lower()

    if (
        ("elite" in customer_lower or "sunshine" in customer_lower)
        and bucket_name in CLASSIC_TRACKER_CUSTOMER_BUCKETS
    ):
        return CLASSIC_TRACKER_DESCRIPTION

    if bucket_name == NIR_GREY_RPC_DESCRIPTION:
        return NIR_GREY_TRACKER_DESCRIPTION

    return bucket_name


@transaction.atomic
def upsert_container_from_rpc_order(
    *,
    company: Company,
    created_by,
    rpc_data: Dict[str, Any],
) -> OrderContainer:
    """Create or update an OrderContainer based on an RPC Order submission.

    Mapping rules (per your spec):
    - RPC form `nld` -> OrderTracker `loading_date`
    - RPC form `delivery` -> OrderTracker `requested_date`
    - RPC form `company` -> OrderTracker `customer_name`
    - RPC form `city_state` -> OrderTracker `location_name`
    - RPC form `po` -> OrderTracker `po_number`
    - RPC form `rpc_info` -> OrderTracker `rpc_number`
    - RPC form `contact_person` -> OrderTracker `assigned_to`

    Content lines are inferred from the bucket pallet counts on the RPC form.
    Tracker-only display aliases are applied here without changing the RPC file.
    """

    rpc_number = (rpc_data.get("rpc_info") or "").strip()
    customer_name = (rpc_data.get("company") or "").strip()
    location_name = (rpc_data.get("city_state") or "").strip()

    # Header values
    po_number = (rpc_data.get("po") or "").strip()
    requested_date = rpc_data.get("delivery")
    loading_date = rpc_data.get("nld")
    assigned_to = CONTACT_TO_OWNER.get((rpc_data.get("contact_person") or "").strip().lower(), "")

    # Prefer matching by (company, rpc_number) since rpc_number is required on the RPC form.
    container: Optional[OrderContainer] = None
    if rpc_number:
        container = (
            OrderContainer.objects.filter(company=company, rpc_number=rpc_number)
            .order_by("-updated_at", "-id")
            .first()
        )

    if container is None:
        container = OrderContainer(
            company=company,
            created_by=created_by,
            rpc_number=rpc_number,
        )

    # Update the fields we can confidently infer.
    container.customer_name = customer_name or container.customer_name
    container.location_name = location_name
    container.po_number = po_number
    container.requested_date = requested_date
    container.loading_date = loading_date

    # Only set assigned_to if blank; don't overwrite if user changed it later.
    if assigned_to and not (container.assigned_to or "").strip():
        container.assigned_to = assigned_to

    # Do NOT overwrite status/ETD/ETA/estimated_delivery_date/booking/BOL/notes
    # because those are tracked over time in the order tracker.

    container.save()

    # Build desired tracker lines. Use (description, pieces-per-pallet) as the
    # identity so two classic variants can both display as "10 liter wide classic"
    # without losing their different 2520/2660/2800 pack sizes.
    desired: Dict[tuple[str, int], int] = {}
    for field_name, bucket_name in BUCKET_FIELD_MAP.items():
        pallets = rpc_data.get(field_name) or 0
        try:
            pallets_int = int(pallets)
        except Exception:
            pallets_int = 0
        if pallets_int <= 0:
            continue

        units = int(PER_PALLET.get(bucket_name, 0) or 0)
        tracker_name = order_tracker_bucket_description(bucket_name, customer_name)
        key = (tracker_name, units)
        desired[key] = desired.get(key, 0) + pallets_int

    known_rpc_bucket_names = set(PER_PALLET.keys())
    known_tracker_descriptions = {
        order_tracker_bucket_description(name, customer_name)
        for name in known_rpc_bucket_names
    }

    existing_lines = list(container.lines.all().order_by("id"))
    kept_line_ids: set[int] = set()

    for (tracker_name, units), pallets in desired.items():
        line = None
        for candidate in existing_lines:
            if candidate.id in kept_line_ids:
                continue
            candidate_name = (candidate.item_description or "").strip()
            normalized_candidate_name = order_tracker_bucket_description(
                candidate_name, customer_name
            )
            if normalized_candidate_name == tracker_name and int(candidate.units_per_pallet or 0) == units:
                line = candidate
                break

        if line is None:
            line = OrderContainerLine.objects.create(
                container=container,
                item_description=tracker_name,
                pallets=pallets,
                units_per_pallet=units,
            )
            existing_lines.append(line)
        else:
            line.item_description = tracker_name
            line.pallets = pallets
            line.units_per_pallet = units
            line.save()

        kept_line_ids.add(line.id)

    # Remove previously auto-imported bucket lines that are no longer selected.
    # Custom/manual lines are left untouched.
    for line in existing_lines:
        if line.id in kept_line_ids:
            continue
        desc = (line.item_description or "").strip()
        if desc in known_rpc_bucket_names or desc in known_tracker_descriptions:
            line.delete()

    return container
