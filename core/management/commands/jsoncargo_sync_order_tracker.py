from __future__ import annotations

import json
import os
import re
import traceback
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import OrderContainer
from core.services.jsoncargo_order_tracker import sync_one_container


def normalize_filter_text(value):
    value = str(value or "").casefold().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalized_match(needle, haystack):
    needle = normalize_filter_text(needle)
    haystack = normalize_filter_text(haystack)
    if not needle:
        return True
    if not haystack:
        return False
    return needle == haystack or needle in haystack


class Command(BaseCommand):
    help = (
        "Sync JSONCargo container tracking for Order Tracker containers and create pending updates "
        "(does NOT auto-apply; user must approve in UI)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company-id", type=int, default=None, help="Only sync containers for this company id.")
        parser.add_argument("--container-id", type=int, default=None, help="Only sync a single OrderContainer id.")
        parser.add_argument("--limit", type=int, default=500, help="Max number of containers to sync.")
        parser.add_argument("--sync-scope", default="all", choices=["all", "owner", "customer_city"])
        parser.add_argument("--owner", default="", help="Assigned owner to sync when --sync-scope=owner.")
        parser.add_argument("--customer", default="", help="Customer text filter when --sync-scope=customer_city.")
        parser.add_argument("--city", default="", help="City/location text filter when --sync-scope=customer_city.")
        parser.add_argument("--label", default="JSONCargo sync", help="Human-readable job label for progress display.")
        parser.add_argument("--status-file", default="", help="Optional JSON file used by the web progress page.")

    def _write_status(self, status_file, payload):
        if not status_file:
            return
        path = Path(status_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(payload)
        payload["updated_at"] = timezone.now().isoformat()
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, default=str), encoding="utf-8")
        tmp_path.replace(path)

    def handle(self, *args, **options):
        api_key = os.getenv("JSONCARGO_API_KEY", "").strip()
        status_file = options.get("status_file") or ""
        label = options.get("label") or "JSONCargo sync"
        state = {
            "state": "running",
            "label": label,
            "message": "Starting JSONCargo sync...",
            "total": 0,
            "checked": 0,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "current": "",
        }
        self._write_status(status_file, state)

        if not api_key:
            state.update({"state": "error", "message": "JSONCARGO_API_KEY is not set on the server."})
            self._write_status(status_file, state)
            self.stderr.write(state["message"])
            return

        try:
            qs = OrderContainer.objects.all()

            company_id = options.get("company_id")
            if company_id:
                qs = qs.filter(company_id=company_id)

            container_id = options.get("container_id")
            if container_id:
                qs = qs.filter(id=container_id)

            # Match the web button behavior: only active, non-delivered containers with a container number.
            qs = qs.filter(is_archived=False)
            qs = qs.exclude(status__iexact="Delivered")
            qs = qs.exclude(container_number__isnull=True).exclude(container_number__exact="")
            qs = qs.exclude(container_number__regex=r"^\s*$")

            sync_scope = options.get("sync_scope") or "all"
            owner = (options.get("owner") or "").strip()
            customer = (options.get("customer") or "").strip()
            city = (options.get("city") or "").strip()

            if sync_scope == "owner" and owner:
                qs = qs.filter(assigned_to__iexact=owner)
            elif sync_scope == "customer_city":
                matching_ids = []
                for container in qs.only("id", "customer_name", "location_name"):
                    if customer and not normalized_match(customer, getattr(container, "customer_name", "")):
                        continue
                    if city and not normalized_match(city, getattr(container, "location_name", "")):
                        continue
                    matching_ids.append(container.id)
                qs = OrderContainer.objects.filter(id__in=matching_ids)

            limit = int(options.get("limit") or 500)
            containers = list(qs.order_by("-updated_at", "-created_at")[:limit])
            state.update({"total": len(containers), "message": f"Found {len(containers)} container(s) to check."})
            self._write_status(status_file, state)

            for container in containers:
                label_current = (container.container_number or f"Order {container.id}").strip()
                state.update({
                    "checked": state["checked"] + 1,
                    "current": label_current,
                    "message": f"Checking {label_current} ({state['checked']} of {state['total']})...",
                })
                self._write_status(status_file, state)

                try:
                    result, _pending = sync_one_container(container, api_key=api_key)
                except Exception as exc:
                    state["errors"] += 1
                    state["message"] = f"Error checking {label_current}: {type(exc).__name__}: {exc}"
                    self._write_status(status_file, state)
                    self.stderr.write(state["message"])
                    continue

                if result in ("error_note_created", "error_note_updated", "error"):
                    state["errors"] += 1
                elif result == "skipped_no_data":
                    state["skipped"] += 1
                elif result in ("change_created", "no_change_created"):
                    state["created"] += 1
                elif result in ("change_updated", "no_change_updated"):
                    state["updated"] += 1
                else:
                    state["skipped"] += 1

                state["message"] = f"Finished {label_current}."
                self._write_status(status_file, state)

            state.update({
                "state": "complete",
                "current": "",
                "message": (
                    f"Complete. Checked {state['checked']} container(s). "
                    f"Created {state['created']}, updated {state['updated']}, "
                    f"skipped {state['skipped']}, errors {state['errors']}."
                ),
            })
            self._write_status(status_file, state)
            self.stdout.write(state["message"])
        except Exception as exc:
            state.update({
                "state": "error",
                "message": f"JSONCargo sync failed: {type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc()[-4000:],
            })
            self._write_status(status_file, state)
            self.stderr.write(state["message"])
            raise
