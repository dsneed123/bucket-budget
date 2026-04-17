import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.template import Context, Template
from django.urls import reverse

from accounts.models import CustomUser
from accounts.signals import DEFAULT_BUCKETS
from accounts.utils import get_current_fiscal_month, get_fiscal_month_range, get_user_fiscal_start
from buckets.models import Bucket

User = get_user_model()


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
        self.assertEqual(self._render(1234, 'JPY'), '¥1,234')

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

    def test_negative_usd(self):
        self.assertEqual(self._render(-500, 'USD'), '($500.00)')

    def test_negative_usd_large(self):
        self.assertEqual(self._render(-1234.56, 'USD'), '($1,234.56)')

    def test_negative_jpy(self):
        self.assertEqual(self._render(-1234, 'JPY'), '(¥1,234)')

    def test_negative_eur(self):
        self.assertEqual(self._render(-99.99, 'EUR'), '(€99.99)')

    def test_negative_unknown_currency(self):
        self.assertEqual(self._render(-100, 'XYZ'), '(XYZ 100.00)')

    def test_negative_decimal(self):
        from decimal import Decimal
        self.assertEqual(self._render(Decimal('-250.00'), 'USD'), '($250.00)')


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
        return self.client.post(reverse('accounts:profile'), data)

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


class FiscalMonthRangeTest(TestCase):
    def test_calendar_month_when_start_is_1(self):
        start, end = get_fiscal_month_range(2026, 4, 1)
        self.assertEqual(start, datetime.date(2026, 4, 1))
        self.assertEqual(end, datetime.date(2026, 4, 30))

    def test_fiscal_month_mid_month_start(self):
        start, end = get_fiscal_month_range(2026, 4, 15)
        self.assertEqual(start, datetime.date(2026, 4, 15))
        self.assertEqual(end, datetime.date(2026, 5, 14))

    def test_fiscal_month_december_wraps_to_next_year(self):
        start, end = get_fiscal_month_range(2026, 12, 15)
        self.assertEqual(start, datetime.date(2026, 12, 15))
        self.assertEqual(end, datetime.date(2027, 1, 14))

    def test_fiscal_month_february_leap_year(self):
        start, end = get_fiscal_month_range(2024, 1, 15)
        self.assertEqual(start, datetime.date(2024, 1, 15))
        self.assertEqual(end, datetime.date(2024, 2, 14))

    def test_calendar_month_february_end(self):
        start, end = get_fiscal_month_range(2026, 2, 1)
        self.assertEqual(start, datetime.date(2026, 2, 1))
        self.assertEqual(end, datetime.date(2026, 2, 28))

    def test_days_in_fiscal_month_matches_calendar_month(self):
        start, end = get_fiscal_month_range(2026, 4, 1)
        self.assertEqual((end - start).days + 1, 30)

    def test_days_in_fiscal_month_non_calendar(self):
        start, end = get_fiscal_month_range(2026, 4, 15)
        self.assertEqual((end - start).days + 1, 30)


class GetCurrentFiscalMonthTest(TestCase):
    def test_start_of_1_always_returns_calendar_month(self):
        today = datetime.date(2026, 4, 1)
        self.assertEqual(get_current_fiscal_month(today, 1), (2026, 4))

    def test_on_or_after_start_day_returns_current_month(self):
        today = datetime.date(2026, 4, 15)
        self.assertEqual(get_current_fiscal_month(today, 15), (2026, 4))

    def test_on_start_day_returns_current_month(self):
        today = datetime.date(2026, 4, 15)
        self.assertEqual(get_current_fiscal_month(today, 15), (2026, 4))

    def test_before_start_day_returns_previous_month(self):
        today = datetime.date(2026, 4, 14)
        self.assertEqual(get_current_fiscal_month(today, 15), (2026, 3))

    def test_january_before_start_wraps_to_december_previous_year(self):
        today = datetime.date(2026, 1, 10)
        self.assertEqual(get_current_fiscal_month(today, 15), (2025, 12))

    def test_first_day_of_month_with_start_1(self):
        today = datetime.date(2026, 4, 1)
        self.assertEqual(get_current_fiscal_month(today, 1), (2026, 4))


class GetUserFiscalStartTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='fiscal@example.com',
            password='testpass',
            first_name='Fiscal',
        )

    def test_returns_default_1_when_no_preferences(self):
        self.assertEqual(get_user_fiscal_start(self.user), 1)

    def test_returns_saved_fiscal_month_start(self):
        from accounts.models import UserPreferences
        UserPreferences.objects.create(user=self.user, fiscal_month_start=15)
        self.assertEqual(get_user_fiscal_start(self.user), 15)


class TimezoneFilterTest(TestCase):
    def _render(self, dt, tz_name):
        from django.template import Context, Template
        tmpl = Template(
            '{% load timezone_tags %}{{ dt|in_timezone:tz_name|date:"Y-m-d H:i" }}'
        )
        return tmpl.render(Context({'dt': dt, 'tz_name': tz_name}))

    def test_converts_utc_to_eastern(self):
        import pytz
        from django.utils import timezone
        utc_dt = datetime.datetime(2024, 6, 15, 18, 0, 0, tzinfo=pytz.UTC)
        result = self._render(utc_dt, 'America/New_York')
        self.assertEqual(result, '2024-06-15 14:00')

    def test_converts_utc_to_pacific(self):
        import pytz
        utc_dt = datetime.datetime(2024, 6, 15, 18, 0, 0, tzinfo=pytz.UTC)
        result = self._render(utc_dt, 'America/Los_Angeles')
        self.assertEqual(result, '2024-06-15 11:00')

    def test_returns_value_unchanged_for_unknown_timezone(self):
        import pytz
        utc_dt = datetime.datetime(2024, 6, 15, 18, 0, 0, tzinfo=pytz.UTC)
        from django.template import Context, Template
        tmpl = Template('{% load timezone_tags %}{{ dt|in_timezone:tz_name }}')
        result = tmpl.render(Context({'dt': utc_dt, 'tz_name': 'Invalid/Zone'}))
        self.assertIn('2024', result)

    def test_returns_none_unchanged(self):
        from accounts.templatetags.timezone_tags import in_timezone
        self.assertIsNone(in_timezone(None, 'UTC'))


class TimezoneSettingTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            email='tzuser@example.com',
            password='testpass',
            first_name='TZ',
        )
        self.client = Client()
        self.client.login(username='tzuser@example.com', password='testpass')

    def test_default_timezone_is_utc(self):
        from accounts.models import UserPreferences
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        self.assertEqual(prefs.timezone, 'UTC')

    def test_save_valid_timezone(self):
        from accounts.models import UserPreferences
        response = self.client.post('/settings/#preferences', {
            'tab': 'preferences',
            'timezone': 'America/New_York',
            'start_of_week': 'monday',
            'fiscal_month_start': '1',
            'theme': 'dark',
            'default_transaction_type': 'expense',
        })
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.timezone, 'America/New_York')

    def test_invalid_timezone_falls_back_to_utc(self):
        from accounts.models import UserPreferences
        self.client.post('/settings/#preferences', {
            'tab': 'preferences',
            'timezone': 'Not/ATimezone',
            'start_of_week': 'monday',
            'fiscal_month_start': '1',
            'theme': 'dark',
            'default_transaction_type': 'expense',
        })
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.timezone, 'UTC')


class CustomUserModelTest(TestCase):
    def test_create_user_with_email(self):
        user = User.objects.create_user(
            email='model@example.com',
            password='pass123',
            first_name='Model',
            last_name='Test',
        )
        self.assertEqual(user.email, 'model@example.com')
        self.assertEqual(user.first_name, 'Model')
        self.assertTrue(user.check_password('pass123'))

    def test_email_required(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='pass', first_name='Test')

    def test_default_currency_is_usd(self):
        user = User.objects.create_user(
            email='currency@example.com',
            password='pass',
            first_name='Test',
        )
        self.assertEqual(user.currency, 'USD')

    def test_email_is_username_field(self):
        self.assertEqual(CustomUser.USERNAME_FIELD, 'email')

    def test_create_superuser(self):
        admin = User.objects.create_superuser(
            email='admin@example.com',
            password='adminpass',
            first_name='Admin',
        )
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)

    def test_zero_based_budgeting_default_false(self):
        user = User.objects.create_user(
            email='zb@example.com',
            password='pass',
            first_name='ZB',
        )
        self.assertFalse(user.zero_based_budgeting)

    def test_monthly_income_default_zero(self):
        from decimal import Decimal
        user = User.objects.create_user(
            email='income@example.com',
            password='pass',
            first_name='Income',
        )
        self.assertEqual(user.monthly_income, Decimal('0'))
