import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
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
