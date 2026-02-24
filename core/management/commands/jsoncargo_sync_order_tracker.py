from __future__ import annotations

import datetime as dt
import os

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import OrderContainer
from core.services.jsoncargo_order_tracker import sync_one_container


def _parse_date(val: str | None) -> dt.date | None:
    """Parse JSONCargo timestamps like '2026-02-22 07:00' into a date."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Common formats seen:
    # - 2026-02-22 07:00
    # - 2026-02-22 07:00:00
    # - 2026-02-22
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
    # Try date-only
    try:
        naive = dt.datetime.strptime(s, "%Y-%m-%d")
        return timezone.make_aware(naive, timezone.get_current_timezone())
    except Exception:
        return None


class Command(BaseCommand):
    help = (
        "Sync JSONCargo container tracking for Order Tracker containers and create pending updates "
        "(does NOT auto-apply; user must approve in UI)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--company-id",
            type=int,
            default=None,
            help="Only sync containers for this company id.",
        )
        parser.add_argument(
            "--container-id",
            type=int,
            default=None,
            help="Only sync a single OrderContainer id.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=250,
            help="Max number of containers to sync.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        api_key = os.getenv("JSONCARGO_API_KEY", "").strip()
        if not api_key:
            self.stderr.write("JSONCARGO_API_KEY is not set. Aborting.")
            return

        qs = OrderContainer.objects.all().order_by("-updated_at", "-created_at")

        company_id = options.get("company_id")
        if company_id:
            qs = qs.filter(company_id=company_id)

        container_id = options.get("container_id")
        if container_id:
            qs = qs.filter(id=container_id)

        # Only containers that have a container number.
        qs = qs.exclude(container_number__isnull=True).exclude(container_number__exact="")

        limit = int(options.get("limit") or 250)
        qs = qs[:limit]

        total = 0
        created = 0
        updated = 0
        skipped = 0
        errors = 0

        for c in qs:
            total += 1

            result, pending = sync_one_container(c, api_key=api_key)

            if result == "error":
                errors += 1
                self.stderr.write(f"[{c.id}] {c.container_number}: error while fetching tracking")
                continue
            if result == "skipped_no_data":
                skipped += 1
                continue
            if result in ("change_created", "no_change_created"):
                created += 1
                continue
            if result in ("change_updated", "no_change_updated"):
                updated += 1
                continue

            skipped += 1
self.stdout.write(
            f"Done. scanned={total} created={created} updated={updated} skipped={skipped} errors={errors}"
        )
