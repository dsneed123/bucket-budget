import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket
from savings.models import SavingsContribution, SavingsGoal
from transactions.models import Transaction

from .models import Recommendation
from .recommendations import (
    refresh_recommendations,
    _over_budget_buckets,
    _savings_rate_recs,
    _spending_quality_recs,
    _vendor_recs,
)
from .views import _daily_heatmap

User = get_user_model()


class InsightsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='insights@example.com',
            password='testpass123',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='insights@example.com', password='testpass123')

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_authenticated_user(self):
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'insights/insights.html')

    def test_context_keys_present(self):
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 200)
        for key in ('this_spending', 'last_spending', 'cur_savings_rate', 'quality_score', 'recommendations'):
            self.assertIn(key, response.context)

    def test_recommendations_in_context(self):
        response = self.client.get(reverse('insights'))
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.context['recommendations'], list)


class RecommendationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='rectest@example.com',
            password='testpass123',
        )

    def test_str_representation(self):
        rec = Recommendation.objects.create(
            user=self.user,
            message='Test message',
            category=Recommendation.CATEGORY_BUDGET,
            priority=Recommendation.PRIORITY_HIGH,
        )
        self.assertIn('budget', str(rec))
        self.assertIn('high', str(rec))

    def test_default_not_dismissed(self):
        rec = Recommendation.objects.create(
            user=self.user,
            message='Test',
            category=Recommendation.CATEGORY_SAVINGS,
        )
        self.assertFalse(rec.is_dismissed)

    def test_default_priority_medium(self):
        rec = Recommendation.objects.create(
            user=self.user,
            message='Test',
            category=Recommendation.CATEGORY_QUALITY,
        )
        self.assertEqual(rec.priority, Recommendation.PRIORITY_MEDIUM)


class DismissRecommendationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='dismiss@example.com',
            password='testpass123',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass123',
        )
        self.client.login(email='dismiss@example.com', password='testpass123')

    def _make_rec(self, user=None):
        return Recommendation.objects.create(
            user=user or self.user,
            message='Test recommendation',
            category=Recommendation.CATEGORY_BUDGET,
            priority=Recommendation.PRIORITY_HIGH,
        )

    def test_dismiss_marks_is_dismissed(self):
        rec = self._make_rec()
        response = self.client.post(reverse('dismiss_recommendation', args=[rec.pk]))
        self.assertEqual(response.status_code, 302)
        rec.refresh_from_db()
        self.assertTrue(rec.is_dismissed)

    def test_dismiss_redirects_to_insights(self):
        rec = self._make_rec()
        response = self.client.post(reverse('dismiss_recommendation', args=[rec.pk]))
        self.assertRedirects(response, reverse('insights'))

    def test_cannot_dismiss_other_users_recommendation(self):
        other_rec = self._make_rec(user=self.other_user)
        response = self.client.post(reverse('dismiss_recommendation', args=[other_rec.pk]))
        self.assertEqual(response.status_code, 404)
        other_rec.refresh_from_db()
        self.assertFalse(other_rec.is_dismissed)

    def test_get_request_redirects_without_dismissing(self):
        rec = self._make_rec()
        response = self.client.get(reverse('dismiss_recommendation', args=[rec.pk]))
        self.assertEqual(response.status_code, 302)
        rec.refresh_from_db()
        self.assertFalse(rec.is_dismissed)

    def test_requires_login(self):
        self.client.logout()
        rec = self._make_rec()
        response = self.client.post(reverse('dismiss_recommendation', args=[rec.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


class RefreshRecommendationsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='refresh@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()

    def _prev_month(self, n=1):
        month = self.today.month - n
        year = self.today.year
        while month <= 0:
            month += 12
            year -= 1
        return year, month

    def test_refresh_clears_existing_undismissed(self):
        Recommendation.objects.create(
            user=self.user, message='Old', category=Recommendation.CATEGORY_BUDGET,
        )
        refresh_recommendations(self.user)
        self.assertEqual(
            Recommendation.objects.filter(user=self.user, is_dismissed=False, message='Old').count(),
            0,
        )

    def test_refresh_preserves_dismissed(self):
        rec = Recommendation.objects.create(
            user=self.user, message='Dismissed', category=Recommendation.CATEGORY_SAVINGS,
            is_dismissed=True,
        )
        refresh_recommendations(self.user)
        self.assertTrue(Recommendation.objects.filter(pk=rec.pk, is_dismissed=True).exists())

    def test_no_recs_for_empty_data(self):
        refresh_recommendations(self.user)
        self.assertEqual(Recommendation.objects.filter(user=self.user, is_dismissed=False).count(), 0)


class OverBudgetBucketRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='overbudget@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()
        self.account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking',
        )
        self.bucket = Bucket.objects.filter(user=self.user).exclude(is_uncategorized=True).first()
        if not self.bucket:
            self.bucket = Bucket.objects.create(
                user=self.user,
                name='Groceries',
                monthly_allocation=Decimal('200.00'),
                color='#00b894',
                sort_order=1,
            )
        else:
            self.bucket.monthly_allocation = Decimal('200.00')
            self.bucket.save()

    def _prev_month_date(self, n):
        month = self.today.month - n
        year = self.today.year
        while month <= 0:
            month += 12
            year -= 1
        return datetime.date(year, month, 15)

    def _make_expense(self, amount, date, bucket=None):
        Transaction.objects.create(
            user=self.user,
            transaction_type='expense',
            amount=amount,
            description='Test',
            date=date,
            bucket=bucket or self.bucket,
            account=self.account,
        )

    def test_three_consecutive_over_budget_months_triggers_rec(self):
        for i in range(1, 4):
            self._make_expense(Decimal('250.00'), self._prev_month_date(i))
        recs = _over_budget_buckets(self.user, self.today)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].category, Recommendation.CATEGORY_BUDGET)
        self.assertEqual(recs[0].priority, Recommendation.PRIORITY_HIGH)
        self.assertIn(self.bucket.name, recs[0].message)

    def test_two_consecutive_over_budget_months_no_rec(self):
        for i in range(1, 3):
            self._make_expense(Decimal('250.00'), self._prev_month_date(i))
        self._make_expense(Decimal('100.00'), self._prev_month_date(3))
        recs = _over_budget_buckets(self.user, self.today)
        self.assertEqual(len(recs), 0)

    def test_no_allocation_skips_bucket(self):
        self.bucket.monthly_allocation = Decimal('0.00')
        self.bucket.save()
        for i in range(1, 4):
            self._make_expense(Decimal('250.00'), self._prev_month_date(i))
        recs = _over_budget_buckets(self.user, self.today)
        self.assertEqual(len(recs), 0)


class SpendingQualityRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='quality@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()
        self.account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking',
        )

    def _prev_month_date(self, n):
        month = self.today.month - n
        year = self.today.year
        while month <= 0:
            month += 12
            year -= 1
        return datetime.date(year, month, 15)

    def test_quality_drop_triggers_rec(self):
        for _ in range(3):
            Transaction.objects.create(
                user=self.user, transaction_type='expense', amount=Decimal('50'),
                description='Test', date=self.today.replace(day=1),
                necessity_score=3, account=self.account,
            )
        for _ in range(3):
            Transaction.objects.create(
                user=self.user, transaction_type='expense', amount=Decimal('50'),
                description='Test', date=self._prev_month_date(1),
                necessity_score=8, account=self.account,
            )
        recs = _spending_quality_recs(self.user, self.today)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].category, Recommendation.CATEGORY_QUALITY)

    def test_small_quality_drop_no_rec(self):
        Transaction.objects.create(
            user=self.user, transaction_type='expense', amount=Decimal('50'),
            description='Test', date=self.today.replace(day=1),
            necessity_score=6, account=self.account,
        )
        Transaction.objects.create(
            user=self.user, transaction_type='expense', amount=Decimal('50'),
            description='Test', date=self._prev_month_date(1),
            necessity_score=7, account=self.account,
        )
        recs = _spending_quality_recs(self.user, self.today)
        self.assertEqual(len(recs), 0)


class SavingsRateRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='savings@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()
        self.account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking',
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Emergency Fund',
            target_amount=Decimal('1000'),
        )

    def _prev_month_date(self, n):
        month = self.today.month - n
        year = self.today.year
        while month <= 0:
            month += 12
            year -= 1
        return datetime.date(year, month, 15)

    def _make_income(self, amount, date):
        Transaction.objects.create(
            user=self.user, transaction_type='income', amount=amount,
            description='Salary', date=date, account=self.account,
        )

    def _make_contribution(self, amount, date):
        SavingsContribution.objects.create(
            goal=self.goal, amount=amount, transaction_type='contribution', date=date,
            source_account=self.account,
        )

    def test_savings_improvement_triggers_rec(self):
        self._make_income(Decimal('3000'), self.today.replace(day=1))
        self._make_contribution(Decimal('600'), self.today.replace(day=1))  # 20%
        self._make_income(Decimal('3000'), self._prev_month_date(1))
        self._make_contribution(Decimal('300'), self._prev_month_date(1))   # 10%
        recs = _savings_rate_recs(self.user, self.today)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].category, Recommendation.CATEGORY_SAVINGS)
        self.assertEqual(recs[0].priority, Recommendation.PRIORITY_LOW)

    def test_small_savings_improvement_no_rec(self):
        self._make_income(Decimal('3000'), self.today.replace(day=1))
        self._make_contribution(Decimal('330'), self.today.replace(day=1))  # 11%
        self._make_income(Decimal('3000'), self._prev_month_date(1))
        self._make_contribution(Decimal('300'), self._prev_month_date(1))   # 10%
        recs = _savings_rate_recs(self.user, self.today)
        self.assertEqual(len(recs), 0)


class DailyHeatmapTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='heatmap@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()
        self.account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking',
        )

    def _make_expense(self, amount, date):
        Transaction.objects.create(
            user=self.user, transaction_type='expense', amount=amount,
            description='Test', date=date, account=self.account,
        )

    def test_returns_weeks_covering_full_month(self):
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        import calendar
        expected_weeks = len(calendar.monthcalendar(self.today.year, self.today.month))
        self.assertEqual(len(weeks), expected_weeks)

    def test_empty_month_all_cells_none_color(self):
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        for week in weeks:
            for cell in week:
                if cell.get('is_current_month') and not cell.get('is_future'):
                    self.assertEqual(cell['color'], 'none')

    def test_color_tiers_green_yellow_red(self):
        first = datetime.date(self.today.year, self.today.month, 1)
        self._make_expense(Decimal('10'), first)
        self._make_expense(Decimal('50'), first.replace(day=min(2, 28)))
        self._make_expense(Decimal('200'), first.replace(day=min(3, 28)))
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        colors = {}
        for week in weeks:
            for cell in week:
                if cell.get('is_current_month') and cell.get('color') != 'none':
                    colors[cell['day']] = cell['color']
        self.assertIn(colors.get(1), ('green', 'yellow', 'red'))
        all_colors = set(colors.values())
        self.assertTrue(all_colors.issubset({'green', 'yellow', 'red'}))

    def test_future_days_have_none_color(self):
        tomorrow = self.today + datetime.timedelta(days=1)
        if tomorrow.month == self.today.month:
            self._make_expense(Decimal('100'), tomorrow)
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        for week in weeks:
            for cell in week:
                if cell.get('is_future'):
                    self.assertEqual(cell['color'], 'none')

    def test_today_cell_is_marked(self):
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        today_cells = [
            cell for week in weeks for cell in week
            if cell.get('is_today')
        ]
        self.assertEqual(len(today_cells), 1)
        self.assertEqual(today_cells[0]['day'], self.today.day)

    def test_date_str_format(self):
        weeks = _daily_heatmap(self.user, self.today.year, self.today.month)
        for week in weeks:
            for cell in week:
                if cell.get('is_current_month'):
                    self.assertRegex(cell['date_str'], r'^\d{4}-\d{2}-\d{2}$')

    def test_heatmap_in_view_context(self):
        client = Client()
        client.login(email='heatmap@example.com', password='testpass123')
        response = client.get(reverse('insights'))
        self.assertIn('heatmap_weeks', response.context)
        self.assertIn('heatmap_dow_labels', response.context)
        self.assertIsInstance(response.context['heatmap_weeks'], list)


class VendorRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='vendor@example.com',
            password='testpass123',
        )
        self.today = datetime.date.today()
        self.account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking',
        )

    def _make_expense(self, amount, vendor):
        Transaction.objects.create(
            user=self.user, transaction_type='expense', amount=amount,
            description='Test', date=self.today.replace(day=1), vendor=vendor,
            account=self.account,
        )

    def test_dominant_vendor_triggers_rec(self):
        self._make_expense(Decimal('400'), 'Amazon')
        self._make_expense(Decimal('100'), 'Walmart')
        self._make_expense(Decimal('100'), 'Target')
        recs = _vendor_recs(self.user, self.today)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0].category, Recommendation.CATEGORY_VENDOR)
        self.assertIn('Amazon', recs[0].message)

    def test_evenly_spread_vendors_no_rec(self):
        self._make_expense(Decimal('200'), 'Amazon')
        self._make_expense(Decimal('200'), 'Walmart')
        self._make_expense(Decimal('200'), 'Target')
        self._make_expense(Decimal('200'), 'Costco')
        recs = _vendor_recs(self.user, self.today)
        self.assertEqual(len(recs), 0)

    def test_no_named_vendor_no_rec(self):
        Transaction.objects.create(
            user=self.user, transaction_type='expense', amount=Decimal('500'),
            description='Test', date=self.today.replace(day=1), vendor='',
            account=self.account,
        )
        recs = _vendor_recs(self.user, self.today)
        self.assertEqual(len(recs), 0)
