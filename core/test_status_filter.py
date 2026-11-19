"""Regression tests for the free-text status filter across spelling variants."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Company, OrderContainer
from .services.status_filter import filter_by_status, normalize_status


class StatusFilterTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="status_filter_test")
        self.company = Company.objects.create(name="Status filter company", owner=user)
        for status in ("In Transit", "in-transit", "IN_TRANSIT", "In/Transit", "Booked"):
            OrderContainer.objects.create(company=self.company, customer_name=status, status=status)

    def test_spaced_search_matches_all_transit_variants(self):
        results = filter_by_status(OrderContainer.objects.all(), "in transit")
        self.assertEqual(results.count(), 4)

    def test_hyphenated_search_matches_all_transit_variants(self):
        results = filter_by_status(OrderContainer.objects.all(), "in-transit")
        self.assertEqual(results.count(), 4)

    def test_partial_search_and_other_statuses(self):
        self.assertEqual(filter_by_status(OrderContainer.objects.all(), "trans").count(), 4)
        self.assertEqual(filter_by_status(OrderContainer.objects.all(), "booked").count(), 1)

    def test_normalized_demo_comparison(self):
        self.assertEqual(normalize_status("in transit"), normalize_status("IN-TRANSIT"))
        self.assertEqual(normalize_status("customs / hold"), normalize_status("Customs-Hold"))
