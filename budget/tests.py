import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
from budget.models import BudgetSummary, MonthlyBudgetAllocation
from buckets.models import Bucket
from transactions.models import Transaction

User = get_user_model()


class BudgetOverviewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='budget@example.com',
            password='testpass',
            first_name='Budget',
            last_name='Tester',
            monthly_income=Decimal('5000.00'),
        )
        self.client.login(email='budget@example.com', password='testpass')
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('500.00'),
            color='#00d4aa',
            icon='🛒',
        )

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_logged_in_user(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.status_code, 200)

    def test_context_contains_summary_values(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertIn('monthly_income', response.context)
        self.assertIn('total_allocated', response.context)
        self.assertIn('unallocated', response.context)
        self.assertIn('total_spent', response.context)
        self.assertIn('remaining_budget', response.context)

    def test_monthly_income_from_user_profile(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['monthly_income'], Decimal('5000.00'))

    def test_total_allocated_sums_active_buckets(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['total_allocated'], Decimal('500.00'))

    def test_unallocated_is_income_minus_allocated(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['unallocated'], Decimal('4500.00'))

    def test_total_spent_counts_current_month_expenses(self):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('150.00'),
            transaction_type='expense',
            description='Weekly groceries',
            date=today,
        )
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['total_spent'], Decimal('150.00'))

    def test_income_transactions_not_counted_as_spent(self):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('1000.00'),
            transaction_type='income',
            description='Paycheck',
            date=today,
        )
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['total_spent'], Decimal('0.00'))

    def test_remaining_budget_is_income_minus_spent(self):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('200.00'),
            transaction_type='expense',
            description='Dinner',
            date=today,
        )
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.context['remaining_budget'], Decimal('4800.00'))

    def test_bucket_data_in_context(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertIn('bucket_data', response.context)
        bucket_names = [item['bucket'].name for item in response.context['bucket_data']]
        self.assertIn('Groceries', bucket_names)
        groceries_item = next(item for item in response.context['bucket_data'] if item['bucket'].name == 'Groceries')
        self.assertIn('spent', groceries_item)
        self.assertIn('remaining', groceries_item)
        self.assertIn('pct', groceries_item)
        self.assertIn('over', groceries_item)

    def test_over_budget_bucket_flagged(self):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('600.00'),
            transaction_type='expense',
            description='Big shop',
            date=today,
        )
        response = self.client.get(reverse('budget_overview'))
        groceries_item = next(item for item in response.context['bucket_data'] if item['bucket'].name == 'Groceries')
        self.assertTrue(groceries_item['over'])

    def test_month_url_renders_for_specific_month(self):
        from django.urls import reverse
        url = reverse('budget_overview_month', kwargs={'year': 2025, 'month': 3})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('current_month', response.context)
        self.assertEqual(response.context['current_month'], 'March 2025')

    def test_month_url_only_counts_that_months_expenses(self):
        from django.urls import reverse
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('100.00'),
            transaction_type='expense',
            description='Old expense',
            date=datetime.date(2025, 3, 15),
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('999.00'),
            transaction_type='expense',
            description='Different month',
            date=datetime.date(2025, 4, 1),
        )
        url = reverse('budget_overview_month', kwargs={'year': 2025, 'month': 3})
        response = self.client.get(url)
        self.assertEqual(response.context['total_spent'], Decimal('100.00'))

    def test_current_month_url_is_flagged(self):
        today = datetime.date.today()
        from django.urls import reverse
        url = reverse('budget_overview_month', kwargs={'year': today.year, 'month': today.month})
        response = self.client.get(url)
        self.assertTrue(response.context['is_current_month'])

    def test_past_month_is_not_flagged_as_current(self):
        from django.urls import reverse
        url = reverse('budget_overview_month', kwargs={'year': 2025, 'month': 1})
        response = self.client.get(url)
        self.assertFalse(response.context['is_current_month'])

    def test_default_route_is_current_month(self):
        today = datetime.date.today()
        response = self.client.get(reverse('budget_overview'))
        self.assertTrue(response.context['is_current_month'])
        self.assertEqual(response.context['current_month'], today.strftime('%B %Y'))

    def test_invalid_month_falls_back_to_current(self):
        today = datetime.date.today()
        from django.urls import reverse
        url = reverse('budget_overview_month', kwargs={'year': 2025, 'month': 13})
        response = self.client.get(url)
        self.assertTrue(response.context['is_current_month'])

    def test_alloc_saved_flag_in_context(self):
        response = self.client.get(reverse('budget_overview') + '?saved=1')
        self.assertTrue(response.context['alloc_saved'])

    def test_alloc_saved_flag_absent_by_default(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertFalse(response.context['alloc_saved'])

    def test_other_users_data_not_included(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
            monthly_income=Decimal('9999.00'),
        )
        Bucket.objects.create(
            user=other_user,
            name='Other Bucket',
            monthly_allocation=Decimal('9000.00'),
            color='#ff0000',
        )
        response = self.client.get(reverse('budget_overview'))
        bucket_names = [item['bucket'].name for item in response.context['bucket_data']]
        self.assertNotIn('Other Bucket', bucket_names)

    def test_bucket_data_includes_rollover_fields(self):
        response = self.client.get(reverse('budget_overview'))
        item = next(i for i in response.context['bucket_data'] if i['bucket'].name == 'Groceries')
        self.assertIn('rollover_amount', item)
        self.assertIn('effective_allocation', item)

    def test_rollover_amount_zero_when_rollover_disabled(self):
        response = self.client.get(reverse('budget_overview'))
        item = next(i for i in response.context['bucket_data'] if i['bucket'].name == 'Groceries')
        self.assertEqual(item['rollover_amount'], Decimal('0'))
        self.assertEqual(item['effective_allocation'], Decimal('500.00'))

    def test_carry_forward_added_when_rollover_enabled(self):
        self.bucket.rollover = True
        self.bucket.save()
        today = datetime.date.today()
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('300.00'),
            transaction_type='expense',
            description='Last month groceries',
            date=datetime.date(prev_year, prev_month, 15),
        )
        response = self.client.get(reverse('budget_overview'))
        item = next(i for i in response.context['bucket_data'] if i['bucket'].name == 'Groceries')
        self.assertEqual(item['rollover_amount'], Decimal('200.00'))
        self.assertEqual(item['effective_allocation'], Decimal('700.00'))

    def test_rollover_capped_at_zero_when_overspent_last_month(self):
        self.bucket.rollover = True
        self.bucket.save()
        today = datetime.date.today()
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('600.00'),
            transaction_type='expense',
            description='Overspent last month',
            date=datetime.date(prev_year, prev_month, 20),
        )
        response = self.client.get(reverse('budget_overview'))
        item = next(i for i in response.context['bucket_data'] if i['bucket'].name == 'Groceries')
        self.assertEqual(item['rollover_amount'], Decimal('0'))
        self.assertEqual(item['effective_allocation'], Decimal('500.00'))

    def test_remaining_uses_effective_allocation_with_rollover(self):
        self.bucket.rollover = True
        self.bucket.save()
        today = datetime.date.today()
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('400.00'),
            transaction_type='expense',
            description='Last month partial spend',
            date=datetime.date(prev_year, prev_month, 10),
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('100.00'),
            transaction_type='expense',
            description='This month spend',
            date=today,
        )
        response = self.client.get(reverse('budget_overview'))
        item = next(i for i in response.context['bucket_data'] if i['bucket'].name == 'Groceries')
        # rollover = 500 - 400 = 100; effective = 500 + 100 = 600; remaining = 600 - 100 = 500
        self.assertEqual(item['rollover_amount'], Decimal('100.00'))
        self.assertEqual(item['effective_allocation'], Decimal('600.00'))
        self.assertEqual(item['remaining'], Decimal('500.00'))


class SaveAllocationsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='save@example.com',
            password='testpass',
            first_name='Save',
            last_name='Tester',
            monthly_income=Decimal('4000.00'),
        )
        self.client.login(email='save@example.com', password='testpass')
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Rent',
            monthly_allocation=Decimal('1000.00'),
            color='#0984e3',
            icon='🏠',
        )

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '1200.00',
        })
        self.assertEqual(response.status_code, 302)

    def test_get_request_redirects(self):
        response = self.client.get(reverse('budget_save_allocations'))
        self.assertRedirects(response, reverse('budget_overview'), fetch_redirect_response=False)

    def test_post_updates_allocation(self):
        self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '1500.00',
        })
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.monthly_allocation, Decimal('1500.00'))

    def test_post_redirects_to_budget_with_saved_flag(self):
        response = self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '1500.00',
        })
        self.assertRedirects(
            response, reverse('budget_overview') + '?saved=1', fetch_redirect_response=False
        )

    def test_invalid_value_skips_update(self):
        response = self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': 'not-a-number',
        })
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.monthly_allocation, Decimal('1000.00'))

    def test_negative_value_skips_update(self):
        self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '-100',
        })
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.monthly_allocation, Decimal('1000.00'))

    def test_other_users_buckets_not_modified(self):
        other_user = User.objects.create_user(
            email='other2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_bucket = Bucket.objects.create(
            user=other_user,
            name='Other',
            monthly_allocation=Decimal('500.00'),
            color='#ff0000',
        )
        self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{other_bucket.pk}': '9999.00',
        })
        other_bucket.refresh_from_db()
        self.assertEqual(other_bucket.monthly_allocation, Decimal('500.00'))


class BudgetSummaryModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='summary@example.com',
            password='testpass',
            first_name='Sum',
            last_name='Mary',
            monthly_income=Decimal('4000.00'),
        )

    def test_create_budget_summary(self):
        summary = BudgetSummary.objects.create(
            user=self.user,
            month=3,
            year=2025,
            income=Decimal('4000.00'),
            total_allocated=Decimal('3000.00'),
            total_spent=Decimal('2500.00'),
            total_saved=Decimal('1500.00'),
            surplus_deficit=Decimal('1500.00'),
        )
        self.assertEqual(summary.month, 3)
        self.assertEqual(summary.year, 2025)
        self.assertEqual(summary.income, Decimal('4000.00'))

    def test_unique_together_constraint(self):
        BudgetSummary.objects.create(
            user=self.user,
            month=1,
            year=2025,
            income=Decimal('4000.00'),
            total_allocated=Decimal('3000.00'),
            total_spent=Decimal('2000.00'),
            total_saved=Decimal('2000.00'),
            surplus_deficit=Decimal('2000.00'),
        )
        with self.assertRaises(IntegrityError):
            BudgetSummary.objects.create(
                user=self.user,
                month=1,
                year=2025,
                income=Decimal('4000.00'),
                total_allocated=Decimal('3000.00'),
                total_spent=Decimal('2000.00'),
                total_saved=Decimal('2000.00'),
                surplus_deficit=Decimal('2000.00'),
            )

    def test_necessity_avg_nullable(self):
        summary = BudgetSummary.objects.create(
            user=self.user,
            month=2,
            year=2025,
            income=Decimal('4000.00'),
            total_allocated=Decimal('3000.00'),
            total_spent=Decimal('1000.00'),
            total_saved=Decimal('3000.00'),
            necessity_avg=None,
            surplus_deficit=Decimal('3000.00'),
        )
        self.assertIsNone(summary.necessity_avg)

    def test_str_representation(self):
        summary = BudgetSummary.objects.create(
            user=self.user,
            month=4,
            year=2025,
            income=Decimal('4000.00'),
            total_allocated=Decimal('3000.00'),
            total_spent=Decimal('2000.00'),
            total_saved=Decimal('2000.00'),
            surplus_deficit=Decimal('2000.00'),
        )
        self.assertIn('2025-04', str(summary))

    def test_ordering(self):
        BudgetSummary.objects.create(
            user=self.user, month=1, year=2025,
            income=Decimal('4000'), total_allocated=Decimal('3000'),
            total_spent=Decimal('2000'), total_saved=Decimal('2000'),
            surplus_deficit=Decimal('2000'),
        )
        BudgetSummary.objects.create(
            user=self.user, month=3, year=2025,
            income=Decimal('4000'), total_allocated=Decimal('3000'),
            total_spent=Decimal('2000'), total_saved=Decimal('2000'),
            surplus_deficit=Decimal('2000'),
        )
        summaries = list(BudgetSummary.objects.filter(user=self.user))
        self.assertEqual(summaries[0].month, 3)
        self.assertEqual(summaries[1].month, 1)


class BudgetHistoryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='history@example.com',
            password='testpass',
            first_name='History',
            last_name='Tester',
            monthly_income=Decimal('5000.00'),
        )
        self.client.login(email='history@example.com', password='testpass')

    def _make_summary(self, month, year, **kwargs):
        defaults = dict(
            income=Decimal('5000.00'),
            total_allocated=Decimal('3000.00'),
            total_spent=Decimal('2000.00'),
            total_saved=Decimal('3000.00'),
            surplus_deficit=Decimal('3000.00'),
        )
        defaults.update(kwargs)
        return BudgetSummary.objects.create(user=self.user, month=month, year=year, **defaults)

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_logged_in_user(self):
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(response.status_code, 200)

    def test_empty_history(self):
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(len(response.context['history']), 0)

    def test_history_contains_user_summaries(self):
        self._make_summary(1, 2025)
        self._make_summary(2, 2025)
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(len(response.context['history']), 2)

    def test_history_ordered_newest_first(self):
        self._make_summary(1, 2025)
        self._make_summary(3, 2025)
        self._make_summary(2, 2025)
        response = self.client.get(reverse('budget_history'))
        months = [row['summary'].month for row in response.context['history']]
        self.assertEqual(months, [3, 2, 1])

    def test_history_excludes_other_users(self):
        other = User.objects.create_user(
            email='other_hist@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
            monthly_income=Decimal('9000.00'),
        )
        BudgetSummary.objects.create(
            user=other, month=1, year=2025,
            income=Decimal('9000'), total_allocated=Decimal('8000'),
            total_spent=Decimal('7000'), total_saved=Decimal('2000'),
            surplus_deficit=Decimal('2000'),
        )
        self._make_summary(1, 2025)
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(len(response.context['history']), 1)
        self.assertEqual(response.context['history'][0]['summary'].user, self.user)

    def test_detail_url_points_to_correct_month(self):
        self._make_summary(4, 2025)
        response = self.client.get(reverse('budget_history'))
        row = response.context['history'][0]
        expected = reverse('budget_overview_month', kwargs={'year': 2025, 'month': 4})
        self.assertEqual(row['detail_url'], expected)

    def test_first_row_has_no_trend(self):
        self._make_summary(1, 2025)
        response = self.client.get(reverse('budget_history'))
        row = response.context['history'][0]
        for key, val in row['trends'].items():
            self.assertIsNone(val, f"trends['{key}'] should be None for first row")

    def test_trend_up_when_spent_increases(self):
        self._make_summary(1, 2025, total_spent=Decimal('1000.00'))
        self._make_summary(2, 2025, total_spent=Decimal('2000.00'))
        response = self.client.get(reverse('budget_history'))
        # history[0] is Feb (newer), history[1] is Jan (older)
        self.assertEqual(response.context['history'][0]['trends']['spent'], 'up')

    def test_trend_down_when_saved_decreases(self):
        self._make_summary(1, 2025, total_saved=Decimal('2000.00'))
        self._make_summary(2, 2025, total_saved=Decimal('1000.00'))
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(response.context['history'][0]['trends']['saved'], 'down')

    def test_trend_up_when_surplus_increases(self):
        self._make_summary(1, 2025, surplus_deficit=Decimal('500.00'))
        self._make_summary(2, 2025, surplus_deficit=Decimal('1000.00'))
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(response.context['history'][0]['trends']['surplus'], 'up')

    def test_trend_flat_when_values_equal(self):
        self._make_summary(1, 2025, total_spent=Decimal('1500.00'))
        self._make_summary(2, 2025, total_spent=Decimal('1500.00'))
        response = self.client.get(reverse('budget_history'))
        self.assertEqual(response.context['history'][0]['trends']['spent'], 'flat')

    def test_necessity_trend_none_when_either_missing(self):
        self._make_summary(1, 2025, necessity_avg=None)
        self._make_summary(2, 2025, necessity_avg=Decimal('3.5'))
        response = self.client.get(reverse('budget_history'))
        self.assertIsNone(response.context['history'][0]['trends']['necessity'])


class GenerateBudgetSummariesCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='cmd@example.com',
            password='testpass',
            first_name='Cmd',
            last_name='User',
            monthly_income=Decimal('5000.00'),
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('0.00'),
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Food',
            monthly_allocation=Decimal('600.00'),
            color='#00d4aa',
            icon='🍔',
        )

    def test_command_creates_summary_for_specific_month(self):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('400.00'),
            transaction_type='expense',
            description='Groceries',
            date=datetime.date(2025, 1, 15),
        )
        call_command('generate_budget_summaries', user=self.user.pk, month=1, year=2025)
        summary = BudgetSummary.objects.get(user=self.user, month=1, year=2025)
        self.assertEqual(summary.total_spent, Decimal('400.00'))

    def test_command_updates_existing_summary(self):
        BudgetSummary.objects.create(
            user=self.user, month=2, year=2025,
            income=Decimal('5000'), total_allocated=Decimal('600'),
            total_spent=Decimal('0'), total_saved=Decimal('5000'),
            surplus_deficit=Decimal('5000'),
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('300.00'),
            transaction_type='expense',
            description='Bill',
            date=datetime.date(2025, 2, 10),
        )
        call_command('generate_budget_summaries', user=self.user.pk, month=2, year=2025)
        summary = BudgetSummary.objects.get(user=self.user, month=2, year=2025)
        self.assertEqual(summary.total_spent, Decimal('300.00'))

    def test_surplus_deficit_calculated_correctly(self):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('1000.00'),
            transaction_type='expense',
            description='Rent',
            date=datetime.date(2025, 3, 1),
        )
        call_command('generate_budget_summaries', user=self.user.pk, month=3, year=2025)
        summary = BudgetSummary.objects.get(user=self.user, month=3, year=2025)
        # income=5000, spent=1000, surplus=4000
        self.assertEqual(summary.surplus_deficit, Decimal('4000.00'))


class BudgetAlertsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='alerts@example.com',
            password='testpass',
            first_name='Alert',
            last_name='Tester',
            monthly_income=Decimal('5000.00'),
        )
        self.client.login(email='alerts@example.com', password='testpass')
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )

    def _make_bucket(self, name, allocation, icon='💰'):
        return Bucket.objects.create(
            user=self.user,
            name=name,
            monthly_allocation=allocation,
            color='#00d4aa',
            icon=icon,
        )

    def _spend(self, bucket, amount):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=bucket,
            amount=amount,
            transaction_type='expense',
            description='test',
            date=today,
        )

    def _get_alerts(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.status_code, 200)
        return response.context['alerts']

    def test_no_alerts_when_budget_is_healthy(self):
        self._make_bucket('Groceries', Decimal('500.00'))
        alerts = self._get_alerts()
        self.assertEqual(alerts, [])

    def test_error_alert_when_total_allocation_exceeds_income(self):
        self._make_bucket('Rent', Decimal('4000.00'))
        self._make_bucket('Food', Decimal('2000.00'))
        alerts = self._get_alerts()
        error_alerts = [a for a in alerts if a['level'] == 'error']
        self.assertEqual(len(error_alerts), 1)
        self.assertIn('exceed', error_alerts[0]['message'])

    def test_no_error_alert_when_allocation_equals_income(self):
        self._make_bucket('Rent', Decimal('5000.00'))
        alerts = self._get_alerts()
        error_alerts = [a for a in alerts if a['level'] == 'error']
        self.assertEqual(len(error_alerts), 0)

    def test_warning_alert_when_bucket_exceeds_alert_threshold(self):
        bucket = self._make_bucket('Dining', Decimal('200.00'))
        self._spend(bucket, Decimal('185.00'))  # 92%
        alerts = self._get_alerts()
        warning_alerts = [a for a in alerts if a['level'] == 'warning']
        self.assertTrue(any('Dining' in a['message'] for a in warning_alerts))

    def test_no_bucket_alert_when_below_threshold(self):
        bucket = self._make_bucket('Dining', Decimal('200.00'))
        self._spend(bucket, Decimal('100.00'))  # 50%
        alerts = self._get_alerts()
        warning_alerts = [a for a in alerts if a['level'] == 'warning']
        self.assertFalse(any('Dining' in a['message'] for a in warning_alerts))

    def test_warning_alert_when_overall_spending_exceeds_80_percent(self):
        bucket = self._make_bucket('Expenses', Decimal('5000.00'))
        self._spend(bucket, Decimal('4100.00'))  # 82% of income
        alerts = self._get_alerts()
        warning_alerts = [a for a in alerts if a['level'] == 'warning']
        self.assertTrue(any('82%' in a['message'] or 'spending' in a['message'].lower() for a in warning_alerts))

    def test_no_overall_spending_alert_when_below_80_percent(self):
        bucket = self._make_bucket('Expenses', Decimal('5000.00'))
        self._spend(bucket, Decimal('3900.00'))  # 78% of income
        alerts = self._get_alerts()
        spend_alerts = [a for a in alerts if 'spending' in a['message'].lower() and 'income' in a['message'].lower()]
        self.assertEqual(len(spend_alerts), 0)

    def test_warning_alert_for_zero_allocation_bucket_with_spending(self):
        bucket = self._make_bucket('Misc', Decimal('0.00'))
        self._spend(bucket, Decimal('50.00'))
        alerts = self._get_alerts()
        warning_alerts = [a for a in alerts if a['level'] == 'warning']
        self.assertTrue(any('Misc' in a['message'] and 'no allocation' in a['message'].lower() for a in warning_alerts))

    def test_no_alert_for_zero_allocation_bucket_without_spending(self):
        self._make_bucket('Empty', Decimal('0.00'))
        alerts = self._get_alerts()
        self.assertFalse(any('Empty' in a['message'] for a in alerts))


class ZeroBasedBudgetingTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='zbb@example.com',
            password='testpass',
            first_name='Zero',
            last_name='Based',
            monthly_income=Decimal('5000.00'),
            zero_based_budgeting=True,
        )
        self.client.login(email='zbb@example.com', password='testpass')

    def _make_bucket(self, name, allocation):
        return Bucket.objects.create(
            user=self.user,
            name=name,
            monthly_allocation=allocation,
            color='#00d4aa',
            icon='💰',
        )

    def _get_context(self):
        response = self.client.get(reverse('budget_overview'))
        self.assertEqual(response.status_code, 200)
        return response.context

    def test_every_dollar_assigned_when_fully_allocated(self):
        self._make_bucket('Rent', Decimal('3000.00'))
        self._make_bucket('Food', Decimal('2000.00'))
        ctx = self._get_context()
        self.assertTrue(ctx['every_dollar_assigned'])

    def test_every_dollar_assigned_false_when_under_allocated(self):
        self._make_bucket('Rent', Decimal('3000.00'))
        ctx = self._get_context()
        self.assertFalse(ctx['every_dollar_assigned'])

    def test_every_dollar_assigned_false_when_over_allocated(self):
        self._make_bucket('Rent', Decimal('6000.00'))
        ctx = self._get_context()
        self.assertFalse(ctx['every_dollar_assigned'])

    def test_zero_based_flag_in_context(self):
        ctx = self._get_context()
        self.assertTrue(ctx['zero_based'])

    def test_warning_alert_when_unallocated_positive(self):
        self._make_bucket('Rent', Decimal('3000.00'))
        ctx = self._get_context()
        alerts = ctx['alerts']
        zb_alerts = [a for a in alerts if 'Zero-based' in a['message']]
        self.assertEqual(len(zb_alerts), 1)
        self.assertEqual(zb_alerts[0]['level'], 'warning')
        self.assertIn('unallocated', zb_alerts[0]['message'])

    def test_warning_alert_when_over_allocated_in_zb_mode(self):
        self._make_bucket('Rent', Decimal('6000.00'))
        ctx = self._get_context()
        zb_alerts = [a for a in ctx['alerts'] if 'Zero-based' in a['message']]
        self.assertEqual(len(zb_alerts), 1)
        self.assertIn('exceed', zb_alerts[0]['message'])

    def test_no_zero_based_warning_when_fully_allocated(self):
        self._make_bucket('Rent', Decimal('5000.00'))
        ctx = self._get_context()
        zb_alerts = [a for a in ctx['alerts'] if 'Zero-based' in a['message']]
        self.assertEqual(len(zb_alerts), 0)

    def test_no_zero_based_warning_when_mode_disabled(self):
        self.user.zero_based_budgeting = False
        self.user.save()
        self._make_bucket('Rent', Decimal('3000.00'))
        ctx = self._get_context()
        zb_alerts = [a for a in ctx['alerts'] if 'Zero-based' in a['message']]
        self.assertEqual(len(zb_alerts), 0)

    def test_every_dollar_assigned_false_when_mode_disabled(self):
        self.user.zero_based_budgeting = False
        self.user.save()
        self._make_bucket('Rent', Decimal('5000.00'))
        ctx = self._get_context()
        self.assertFalse(ctx['every_dollar_assigned'])

    def test_every_dollar_assigned_false_when_no_income(self):
        self.user.monthly_income = Decimal('0')
        self.user.save()
        ctx = self._get_context()
        self.assertFalse(ctx['every_dollar_assigned'])


class CopyLastMonthAllocationsTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='copy@example.com',
            password='testpass',
            first_name='Copy',
            last_name='Tester',
            monthly_income=Decimal('5000.00'),
        )
        self.client.login(email='copy@example.com', password='testpass')
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Rent',
            monthly_allocation=Decimal('1000.00'),
            color='#0984e3',
            icon='🏠',
        )

    def _save_snapshot(self, year, month, amount):
        MonthlyBudgetAllocation.objects.update_or_create(
            user=self.user,
            bucket=self.bucket,
            year=year,
            month=month,
            defaults={'amount': amount},
        )

    def test_copy_applies_prev_month_snapshot_to_bucket(self):
        self._save_snapshot(2026, 3, Decimal('1200.00'))
        self.client.post(reverse('budget_copy_last_month'), {'year': 2026, 'month': 4})
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.monthly_allocation, Decimal('1200.00'))

    def test_copy_saves_snapshot_for_target_month(self):
        self._save_snapshot(2026, 3, Decimal('900.00'))
        self.client.post(reverse('budget_copy_last_month'), {'year': 2026, 'month': 4})
        snapshot = MonthlyBudgetAllocation.objects.get(
            user=self.user, bucket=self.bucket, year=2026, month=4
        )
        self.assertEqual(snapshot.amount, Decimal('900.00'))

    def test_copy_redirects_with_copied_flag(self):
        today = datetime.date.today()
        if today.month == 1:
            prev_year, prev_month = today.year - 1, 12
        else:
            prev_year, prev_month = today.year, today.month - 1
        self._save_snapshot(prev_year, prev_month, Decimal('800.00'))
        response = self.client.post(
            reverse('budget_copy_last_month'),
            {'year': today.year, 'month': today.month},
        )
        self.assertIn('copied=1', response['Location'])

    def test_copy_does_nothing_when_no_prev_snapshot(self):
        original = self.bucket.monthly_allocation
        self.client.post(reverse('budget_copy_last_month'), {'year': 2026, 'month': 4})
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.monthly_allocation, original)

    def test_get_request_redirects(self):
        response = self.client.get(reverse('budget_copy_last_month'))
        self.assertRedirects(response, reverse('budget_overview'), fetch_redirect_response=False)

    def test_redirects_when_not_logged_in(self):
        self.client.logout()
        response = self.client.post(reverse('budget_copy_last_month'), {'year': 2026, 'month': 4})
        self.assertEqual(response.status_code, 302)

    def test_other_users_snapshot_not_applied(self):
        other_user = User.objects.create_user(
            email='other_copy@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_bucket = Bucket.objects.create(
            user=other_user,
            name='Other',
            monthly_allocation=Decimal('500.00'),
            color='#ff0000',
        )
        MonthlyBudgetAllocation.objects.create(
            user=other_user, bucket=other_bucket, year=2026, month=3, amount=Decimal('9999.00')
        )
        self.client.post(reverse('budget_copy_last_month'), {'year': 2026, 'month': 4})
        other_bucket.refresh_from_db()
        self.assertEqual(other_bucket.monthly_allocation, Decimal('500.00'))

    def test_prev_month_has_snapshot_in_context_when_snapshot_exists(self):
        self._save_snapshot(2026, 3, Decimal('500.00'))
        url = reverse('budget_overview_month', kwargs={'year': 2026, 'month': 4})
        response = self.client.get(url)
        self.assertTrue(response.context['prev_month_has_snapshot'])

    def test_prev_month_has_snapshot_false_when_no_snapshot(self):
        url = reverse('budget_overview_month', kwargs={'year': 2026, 'month': 4})
        response = self.client.get(url)
        self.assertFalse(response.context['prev_month_has_snapshot'])

    def test_save_allocations_creates_snapshot(self):
        today = datetime.date.today()
        self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '1500.00',
            'year': today.year,
            'month': today.month,
        })
        snapshot = MonthlyBudgetAllocation.objects.get(
            user=self.user, bucket=self.bucket, year=today.year, month=today.month
        )
        self.assertEqual(snapshot.amount, Decimal('1500.00'))

    def test_save_allocations_updates_existing_snapshot(self):
        today = datetime.date.today()
        self._save_snapshot(today.year, today.month, Decimal('800.00'))
        self.client.post(reverse('budget_save_allocations'), {
            f'allocation_{self.bucket.pk}': '1100.00',
            'year': today.year,
            'month': today.month,
        })
        snapshot = MonthlyBudgetAllocation.objects.get(
            user=self.user, bucket=self.bucket, year=today.year, month=today.month
        )
        self.assertEqual(snapshot.amount, Decimal('1100.00'))
