import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
from budget.models import BudgetSummary
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
