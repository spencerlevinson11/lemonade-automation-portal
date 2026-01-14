from __future__ import annotations

from typing import Any, Dict, Optional

from django.db import transaction

from ..models import Company, OrderContainer, OrderContainerLine
from ..rpc_generation import BUCKET_FIELD_MAP, PER_PALLET


CONTACT_TO_OWNER = {
    "spencer": "Spencer",
    "jaime": "Jaime",
}


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
    We upsert only the "known bucket" lines (bucket-name descriptions), leaving
    any manually-added/custom lines untouched.
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

    # Build desired bucket lines from the RPC form.
    desired: Dict[str, int] = {}
    for field_name, bucket_name in BUCKET_FIELD_MAP.items():
        pallets = rpc_data.get(field_name) or 0
        try:
            pallets_int = int(pallets)
        except Exception:
            pallets_int = 0
        if pallets_int > 0:
            desired[bucket_name] = pallets_int

    known_bucket_names = set(PER_PALLET.keys())

    # Upsert known bucket lines.
    for bucket_name, pallets in desired.items():
        units = int(PER_PALLET.get(bucket_name, 0) or 0)
        line = (
            container.lines.filter(item_description=bucket_name)
            .order_by("id")
            .first()
        )
        if line is None:
            OrderContainerLine.objects.create(
                container=container,
                item_description=bucket_name,
                pallets=pallets,
                units_per_pallet=units,
            )
        else:
            line.pallets = pallets
            line.units_per_pallet = units
            line.save()

    # Remove bucket lines that were previously imported but are now zero.
    for line in container.lines.all():
        if line.item_description in known_bucket_names and line.item_description not in desired:
            line.delete()

    return container
