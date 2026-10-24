"""JSONCargo demo bulk sync worker: writes ONLY to a temporary status file."""
import json
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from core.models import Company, OrderContainer
from core.services.jsoncargo_accounts import api_key_for_user
from core.services.jsoncargo_order_tracker import (
    _attempt_container_lookup, _jsoncargo_data, _extract_eta_city,
    tracking_reference_for_jsoncargo,
)


def save_status(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data), encoding='utf-8')
    os.replace(temp, path)


class Command(BaseCommand):
    help = 'Track demo containers without writing to production order/tracking tables.'

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
                        tracking, err, _ = _attempt_container_lookup(
                            tracking_reference=tracking_reference_for_jsoncargo(container),
                            api_key=api_key,
                            shipping_line=container.jsoncargo_shipping_line_param(),
                        )
                        if err:
                            result = {'kind': 'error', 'status': 'pending', 'eta': '', 'city': '',
                                      'message': 'Tracking lookup returned an error.', 'record_id': 0}
                            status['errors'] += 1
                        else:
                            eta, city = _extract_eta_city(_jsoncargo_data(tracking))
                            result = {'kind': 'change', 'status': 'pending',
                                      'eta': str(eta) if eta else '', 'city': str(city or '')[:160],
                                      'message': '', 'record_id': 0,
                                      'container_status': str(_jsoncargo_data(tracking).get('container_status') or '')[:120]}
                            status['updated'] += 1
                        result['demo_only'] = True
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
            status['message'] = 'Demo tracking failed. Check the background job log.'
        save_status(path, status)
