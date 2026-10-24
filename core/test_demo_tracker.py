from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from core.models import Company, OrderContainer


class DemoTrackerSecurityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.source = user_model.objects.create_user(username='Retrieverpackaging', password='testpass')
        self.demo = user_model.objects.create_user(username='LemonadeStandEx', password='testpass')
        self.source_company = Company.objects.create(owner=self.source, name='Internal')
        self.demo_company = Company.objects.create(owner=self.demo, name='Demo')
        self.order = OrderContainer.objects.create(company=self.source_company, customer_name='Private Customer', status='In Transit', origin_country='Netherlands')
        self.client.force_login(self.demo)

    def test_demo_archived_view_redacts_and_temporary_unarchive(self):
        self.order.is_archived = True
        self.order.status = 'Delivered'
        self.order.save(update_fields=['is_archived', 'status'])
        url = reverse('order_tracker_demo_archived')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer')
        self.assertNotContains(response, 'Private Customer')
        self.assertContains(response, 'Unarchive')
        response = self.client.post(reverse('order_tracker_demo_archive', args=[self.order.pk]),
                                    {'action': 'unarchive'})
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_archived)
        self.assertContains(self.client.get(reverse('order_tracker')), 'Customer')
        self.assertNotContains(self.client.get(reverse('order_tracker_demo_archived')), 'Private Customer')

    def test_demo_archive_is_session_only(self):
        self.order.status = 'Delivered'
        self.order.save(update_fields=['status'])
        self.client.post(reverse('order_tracker_demo_archive', args=[self.order.pk]), {'action': 'archive'})
        self.order.refresh_from_db()
        self.assertFalse(self.order.is_archived)
        self.assertNotContains(self.client.get(reverse('order_tracker')), 'Private Customer')
        self.assertContains(self.client.get(reverse('order_tracker_demo_archived')), 'Customer')
        self.client.post(reverse('order_tracker_demo_reset'))
        self.assertNotContains(self.client.get(reverse('order_tracker_demo_archived')), 'Private Customer')
        self.assertEqual(OrderContainer.objects.get(pk=self.order.pk).is_archived, False)

    def test_snapshot_redacts_customer_and_does_not_write(self):
        response = self.client.get(reverse('order_tracker'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Customer 01')
        self.assertNotContains(response, 'Private Customer')
        self.assertEqual(OrderContainer.objects.filter(company=self.demo_company).count(), 0)

    def test_demo_changes_only_session(self):
        response = self.client.post(reverse('order_tracker_demo_edit', args=[self.order.pk]), {
            'status': 'Delivered', 'owner': 'Demo Owner', 'origin': 'Vietnam', 'eta': '2026-11-01'
        })
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'In Transit')
        self.assertContains(self.client.get(reverse('order_tracker')), 'Demo Owner')
        self.client.post(reverse('order_tracker_demo_reset'))
        self.assertNotContains(self.client.get(reverse('order_tracker')), 'Demo Owner')

    def test_demo_cannot_invoke_production_tracking_or_export(self):
        self.assertEqual(self.client.post(reverse('order_tracker_jsoncargo_sync')).status_code, 403)
        self.assertEqual(self.client.post(reverse('order_container_sync_jsoncargo', args=[self.order.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('order_tracker_recap_docx')).status_code, 200)

    def test_matching_dashboard_and_demo_edits_are_isolated(self):
        response = self.client.get(reverse('order_tracker'))
        self.assertContains(response, 'Estimated Shipment Progress')
        self.assertContains(response, 'Active Orders')
        self.assertContains(response, 'Customer 01')
        self.assertNotContains(response, 'Private Customer')
        self.client.post(reverse('order_tracker_demo_action'), {
            'action': 'edit', 'container_id': self.order.pk,
            'owner': 'Demo Owner', 'origin': 'Vietnam', 'status': 'On water'
        })
        self.assertContains(self.client.get(reverse('order_tracker')), 'Demo Owner')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'In Transit')
        self.assertEqual(self.order.assigned_to, '')

    def test_demo_updates_do_not_call_tracking(self):
        with patch('requests.get') as get_api, patch('requests.post') as post_api:
            self.client.post(reverse('order_tracker_demo_action'), {'action': 'refresh'})
            get_api.assert_not_called()
            post_api.assert_not_called()

    def test_demo_track_uses_source_key_exactly_once_and_keeps_edits_temporary(self):
        self.client.post(reverse('order_tracker_demo_edit', args=[self.order.pk]), {
            'status': 'Delivered', 'owner': 'Demo Owner', 'origin': 'Vietnam', 'eta': '2026-11-01'
        })
        with patch('core.services.jsoncargo_accounts.api_key_for_user', return_value='test-source-key') as key, \
             patch('core.services.jsoncargo_order_tracker.sync_one_container', return_value=('no_change_created', None)) as tracking:
            response = self.client.post(reverse('order_tracker_demo_track', args=[self.order.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(key.call_args.args[0].pk, self.source.pk)
        tracking.assert_called_once()
        self.assertEqual(tracking.call_args.args[0].pk, self.order.pk)
        self.assertEqual(tracking.call_args.kwargs['api_key'], 'test-source-key')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'In Transit')
        self.assertNotEqual(self.order.assigned_to, 'Demo Owner')

    def test_demo_cannot_track_other_company_container(self):
        other = get_user_model().objects.create_user(username='OtherUser', password='testpass')
        other_company = Company.objects.create(owner=other, name='Other')
        other_order = OrderContainer.objects.create(company=other_company, customer_name='Other')
        with patch('core.services.jsoncargo_order_tracker.sync_one_container') as tracking:
            result = self.client.post(reverse('order_tracker_demo_track', args=[other_order.pk]))
        self.assertEqual(result.status_code, 404)
        tracking.assert_not_called()

    def test_customer_alias_mapping_excludes_archived_customers(self):
        from core.demo_tracker import demo_customer_aliases
        OrderContainer.objects.create(
            company=self.source_company, customer_name='A Historic Customer',
            is_archived=True, status='Delivered', container_number='ABCD1234567',
        )
        self.order.container_number = 'WXYZ1234567'
        self.order.save(update_fields=['container_number'])
        aliases = demo_customer_aliases(self.source_company)
        self.assertEqual(aliases['Private Customer'], 'Customer 01')
        self.assertNotIn('A Historic Customer', aliases)
        self.assertContains(self.client.get(reverse('order_tracker')), 'Customer 01')

    def test_customer_alias_resolves_consistently_in_demo_bulk_sync(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        OrderContainer.objects.create(
            company=self.source_company, customer_name='A Historic Customer',
            is_archived=True, status='Delivered', container_number='ABCD1234567',
        )
        self.order.container_number = 'WXYZ1234567'
        self.order.save(update_fields=['container_number'])
        with TemporaryDirectory() as tmp, \
             patch('core.services.jsoncargo_accounts.api_key_for_user', return_value='test-key'), \
             patch('core.views._jsoncargo_sync_status_path', return_value=Path(tmp) / 'sync.json'), \
             patch('subprocess.Popen') as process:
            response = self.client.post(reverse('order_tracker_demo_sync'), {
                'sync_scope': 'customer_city', 'customer': 'Customer 01', 'city': ''
            })
            self.assertEqual(response.status_code, 302)
            args = process.call_args.args[0]
            self.assertEqual(args[args.index('--customer') + 1], 'Private Customer')
            self.assertEqual(args[args.index('--sync-scope') + 1], 'customer_city')

    def test_demo_recap_uses_session_edits_and_never_updates_source(self):
        from io import BytesIO
        from docx import Document
        from core.demo_tracker import DEMO_CREATED_KEY, SESSION_KEY
        self.client.post(reverse('order_tracker_demo_action'), {
            'action': 'edit', 'container_id': str(self.order.pk),
            'owner': 'Demo Owner', 'status': 'Demo Status',
        })
        session = self.client.session
        edits = session.get(SESSION_KEY, {})
        edits[str(self.order.pk)]['lines'] = [
            {'item_description': 'Demo-only contents', 'pallets': 2,
             'units_per_pallet': 10, 'total_units': 20}
        ]
        session[SESSION_KEY] = edits
        session[DEMO_CREATED_KEY] = {
            '2000000000': {'customer_name': 'Test Demo Customer',
                           'location_name': 'Demoville', 'po_number': 'DEMO-100',
                           'rpc_number': 'DEMO-RPC', 'status': 'Booked'}
        }
        session.save()
        response = self.client.get(reverse('order_tracker_recap_docx'))
        self.assertEqual(response.status_code, 200)
        content = b''.join(response.streaming_content)
        doc = Document(BytesIO(content))
        text = '\n'.join(p.text for p in doc.paragraphs)
        self.assertIn('Demo Status', text)
        self.assertIn('Demo-only contents', text)
        self.assertIn('DEMO-100', text)
        self.assertIn('Demoville', text)
        self.assertNotIn('Private Customer', text)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'In Transit')
        self.assertEqual(OrderContainer.objects.filter(company=self.source_company).count(), 1)
        self.assertEqual(OrderContainer.objects.filter(company=self.demo_company).count(), 0)



class DemoCheckboxSaveTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.owner = users.objects.create_user(username='Retrieverpackaging', password='test')
        self.demo = users.objects.create_user(username='LemonadeStandEx', password='test')
        self.source = Company.objects.create(owner=self.owner, name='Source Company')
        self.demo_company = Company.objects.create(owner=self.demo, name='Demo Company')
        self.order = OrderContainer.objects.create(company=self.source, customer_name='Private Customer', status='In Transit')
        self.client.force_login(self.demo)

    def test_checkbox_persists_across_dashboard_loads_without_source_write(self):
        from core.demo_tracker import SESSION_KEY
        url = reverse('order_tracker_demo_checkbox')
        response = self.client.post(url, {'container_id': str(self.order.pk), 'checked': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'checked': True})
        self.assertTrue(self.client.session[SESSION_KEY][str(self.order.pk)]['checked'])
        self.client.get(reverse('order_tracker'))
        self.assertTrue(self.client.session[SESSION_KEY][str(self.order.pk)]['checked'])
        self.order.refresh_from_db()
        self.assertFalse(self.order.tracker_checked)
        response = self.client.post(url, {'container_id': str(self.order.pk), 'checked': '0'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.json()['checked'], False)
        self.order.refresh_from_db()
        self.assertFalse(self.order.tracker_checked)

    def test_invalid_id_rejected_as_json(self):
        response = self.client.post(reverse('order_tracker_demo_checkbox'), {'container_id': 'bad', 'checked': '1'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['ok'])

