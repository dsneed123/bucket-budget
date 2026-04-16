from django.test import TestCase
from django.template import Context, Template


class CurrencyFilterTest(TestCase):
    def _render(self, value, currency_code):
        template = Template(
            '{% load currency_tags %}{{ value|currency:currency_code }}'
        )
        return template.render(Context({'value': value, 'currency_code': currency_code}))

    def test_usd(self):
        self.assertEqual(self._render(1234.56, 'USD'), '$1,234.56')

    def test_eur(self):
        self.assertEqual(self._render(1234.56, 'EUR'), '€1,234.56')

    def test_gbp(self):
        self.assertEqual(self._render(1234.56, 'GBP'), '£1,234.56')

    def test_cad(self):
        self.assertEqual(self._render(1234.56, 'CAD'), 'CA$1,234.56')

    def test_aud(self):
        self.assertEqual(self._render(1234.56, 'AUD'), 'A$1,234.56')

    def test_jpy(self):
        self.assertEqual(self._render(1234, 'JPY'), '¥1,234.00')

    def test_zero(self):
        self.assertEqual(self._render(0, 'USD'), '$0.00')

    def test_decimal_value(self):
        from decimal import Decimal
        self.assertEqual(self._render(Decimal('9999.99'), 'USD'), '$9,999.99')

    def test_unknown_currency(self):
        self.assertEqual(self._render(100, 'XYZ'), 'XYZ 100.00')

    def test_invalid_value(self):
        result = self._render('not-a-number', 'USD')
        self.assertEqual(result, 'not-a-number')
