from unittest import TestCase
from core.recap_locations import recap_city

class RecapCityNormalizationTests(TestCase):
    def test_miami_variants_merge(self):
        for text in ('Miami', 'Miami FL', 'Miami FL 33122', 'Miami, FL 33122', 'Miami, Florida', 'miami florida 33122'):
            self.assertEqual(recap_city(text).casefold(), 'miami')

    def test_multiword_cities(self):
        samples = {
            'Salt Lake City UT 84101': 'Salt Lake City',
            'New York, NY 10001': 'New York',
            'New York': 'New York',
            'Los Angeles California 90001': 'Los Angeles',
            'City of Industry, CA 91744': 'City of Industry',
            'Washington DC 20001': 'Washington',
            '': 'Unspecified Location',
        }
        for original, expected in samples.items():
            with self.subTest(original=original):
                self.assertEqual(recap_city(original), expected)
