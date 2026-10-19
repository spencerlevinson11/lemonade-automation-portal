from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Company, OrderContainer


class BulkArchiveDeliveredTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.a = User.objects.create_user(username="archive_customer_a", password="test-password")
        self.b = User.objects.create_user(username="archive_customer_b", password="test-password")
        self.superuser = User.objects.create_superuser(username="archive_admin", email="admin@example.com", password="test-password")
        self.company_a = Company.objects.create(name="Company A", owner=self.a)
        self.company_b = Company.objects.create(name="Company B", owner=self.b)
        self.a_delivered = OrderContainer.objects.create(company=self.company_a, customer_name="A done", status="Delivered")
        self.a_active = OrderContainer.objects.create(company=self.company_a, customer_name="A active", status="In transit")
        self.b_delivered = OrderContainer.objects.create(company=self.company_b, customer_name="B done", status="Delivered")
        self.a_already_archived = OrderContainer.objects.create(company=self.company_a, customer_name="A archived", status="Delivered", is_archived=True)
        self.url = reverse("order_tracker_archive_all_delivered")

    def test_post_customer_archives_only_own_delivered(self):
        self.client.force_login(self.a)
        self.assertRedirects(self.client.post(self.url), reverse("order_tracker"))
        self.a_delivered.refresh_from_db()
        self.a_active.refresh_from_db()
        self.b_delivered.refresh_from_db()
        self.a_already_archived.refresh_from_db()
        self.assertTrue(self.a_delivered.is_archived)
        self.assertIsNotNone(self.a_delivered.archived_at)
        self.assertFalse(self.a_active.is_archived)
        self.assertFalse(self.b_delivered.is_archived)
        self.assertIsNone(self.a_already_archived.archived_at)

    def test_get_not_allowed(self):
        self.client.force_login(self.a)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.a_delivered.refresh_from_db()
        self.assertFalse(self.a_delivered.is_archived)

    def test_requires_login(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.a_delivered.refresh_from_db()
        self.assertFalse(self.a_delivered.is_archived)

    def test_superuser_cannot_bulk_archive_any_company(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.a_delivered.refresh_from_db()
        self.b_delivered.refresh_from_db()
        self.assertFalse(self.a_delivered.is_archived)
        self.assertFalse(self.b_delivered.is_archived)

    def test_second_company_archives_only_own_delivered(self):
        self.client.force_login(self.b)
        self.assertRedirects(self.client.post(self.url), reverse("order_tracker"))
        self.a_delivered.refresh_from_db()
        self.b_delivered.refresh_from_db()
        self.assertFalse(self.a_delivered.is_archived)
        self.assertTrue(self.b_delivered.is_archived)
