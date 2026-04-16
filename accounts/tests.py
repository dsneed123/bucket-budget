from django.test import TestCase, Client
from django.template import Context, Template
from django.urls import reverse

from accounts.models import CustomUser
from accounts.signals import DEFAULT_BUCKETS
from buckets.models import Bucket


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


class DefaultBucketsSignalTest(TestCase):
    def _create_user(self, email='test@example.com'):
        return CustomUser.objects.create_user(email=email, password='pass', first_name='Test')

    def test_default_buckets_created_on_registration(self):
        user = self._create_user()
        buckets = Bucket.objects.filter(user=user).order_by('sort_order')
        self.assertEqual(buckets.count(), len(DEFAULT_BUCKETS))

    def test_default_bucket_names_and_order(self):
        user = self._create_user()
        buckets = list(Bucket.objects.filter(user=user).order_by('sort_order'))
        for i, (bucket, data) in enumerate(zip(buckets, DEFAULT_BUCKETS)):
            self.assertEqual(bucket.name, data['name'])
            self.assertEqual(bucket.icon, data['icon'])
            self.assertEqual(bucket.color, data['color'])
            self.assertEqual(bucket.sort_order, i)

    def test_no_duplicate_buckets_on_update(self):
        user = self._create_user()
        user.first_name = 'Updated'
        user.save()
        self.assertEqual(Bucket.objects.filter(user=user).count(), len(DEFAULT_BUCKETS))

    def test_each_user_gets_own_buckets(self):
        user1 = self._create_user('user1@example.com')
        user2 = self._create_user('user2@example.com')
        self.assertEqual(Bucket.objects.filter(user=user1).count(), len(DEFAULT_BUCKETS))
        self.assertEqual(Bucket.objects.filter(user=user2).count(), len(DEFAULT_BUCKETS))


class ProfileZeroBasedBudgetingTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            email='profile_zb@example.com',
            password='testpass',
            first_name='Profile',
        )
        self.client.login(email='profile_zb@example.com', password='testpass')

    def _post_profile(self, zero_based=False):
        data = {
            'first_name': 'Profile',
            'last_name': '',
            'currency': 'USD',
            'monthly_income': '5000',
        }
        if zero_based:
            data['zero_based_budgeting'] = 'on'
        return self.client.post(reverse('profile'), data)

    def test_zero_based_budgeting_enabled_on_save(self):
        self._post_profile(zero_based=True)
        self.user.refresh_from_db()
        self.assertTrue(self.user.zero_based_budgeting)

    def test_zero_based_budgeting_disabled_when_unchecked(self):
        self.user.zero_based_budgeting = True
        self.user.save()
        self._post_profile(zero_based=False)
        self.user.refresh_from_db()
        self.assertFalse(self.user.zero_based_budgeting)

    def test_zero_based_budgeting_defaults_to_false(self):
        self.assertFalse(self.user.zero_based_budgeting)
