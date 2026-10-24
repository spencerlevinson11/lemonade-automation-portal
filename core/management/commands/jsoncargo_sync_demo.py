"""JSONCargo demo bulk sync worker: shares source tracking updates, never demo edits."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from core.models import Company, OrderContainer
from core.services.jsoncargo_accounts import api_key_for_user
from core.services.jsoncargo_order_tracker import sync_one_container


def save_status(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temp, path)


class Command(BaseCommand):
    help = 'Sync demo-selected source containers through the shared Retriever JSONCargo tracking pipeline.'

    def add_arguments(self, parser):
        parser.add_argument('--status-file', required=True)

    def handle(self, *args, **options):
        path = Path(options['status_file'])"""JSONCargo demo bulk sync worker: shares source tracking updates, never demo edits."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from core.models import Company, OrderContainer
from core.services.jsoncargo_accounts import api_key_for_user
from core.services.jsoncargo_order_tracker import sync_one_container


def save_status(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temp, path)


class Command(BaseCommand):
    help = 'Sync demo-selected source containers through the shared Retriever JSONCargo tracking pipeline.'

    def add_arguments(self, parser):
        parser.add_argument('--status-file', required=True)

    def handle(self, *args, **options):
        path = Path(options['status_file'])
        status = json.loads(path.read_text(encoding='utf-8'))
        if not status.get('demo_only'):
            raise ValueError('Not a demo-only job')
        try:
            source = Company.objects.select_related('owner').get(pk=status['source_company_id'])
            if source.owner.username.casefold() != 'retrieverpackaging':
                raise ValueError('Invalid demo source')
            api_key = api_key_for_user(source.owner)
            status['state'] = 'running'
            status['message'] = 'Checking containers...'
            save_status(path, status)
            for pk in status.get('container_ids', []):
                try:
                    container = OrderContainer.objects.get(pk=pk, company=source, is_archived=False)
                    if container.status.casefold() == 'delivered' or not (container.container_number or '').strip():
                        status['skipped'] += 1
                    else:
                        status['current'] = container.container_number
                        save_status(path, status)
                        # Same source object, credentials, retry/fallback rules,
                        # persistence and per-container advisory lock as Retriever.
                        outcome, update = sync_one_container(container, api_key=api_key)
                        if outcome == 'skipped_in_progress':
                            status['skipped'] += 1
                            continue
                        if update is None:
                            status['skipped'] += 1
                            continue
                        if update.kind == 'error':
                            status['errors'] += 1
                        elif outcome in ('skipped_no_data',):
                            status['skipped'] += 1
                        else:
                            status['updated'] += 1
                        result = {
                            'kind': update.kind, 'status': update.status,
                            'eta': str(update.proposed_eta or ''),
                            'city': str(update.proposed_eta_city or '')[:160],
                            'message': '', 'record_id': update.pk,
                        }
                        status['results'][str(pk)] = result
                except Exception:
                    status['errors'] += 1
                finally:
                    status['checked'] += 1
                    save_status(path, status)
            status['state'] = 'complete'
            status['message'] = 'Demo tracking completed. Return to the tracker to review updates.'
        except Exception:
            status['state'] = 'error'
            status['message'] = 'Tracking currently unavailable'
        save_status(path, status)

