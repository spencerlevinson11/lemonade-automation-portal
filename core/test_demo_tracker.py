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
        self.assertEqual(self.client.get(reverse('order_tracker_recap_docx')).status_code, 403)
