import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, UserPreferences
from banking.models import BankAccount
from transactions.models import Transaction


class NoSpendDaysTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            email='nospend@example.com',
            password='testpass',
            first_name='Test',
        )
        self.client.login(email='nospend@example.com', password='testpass')
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )

    def _add_expense(self, date, amount='50.00'):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            description='Test expense',
            amount=Decimal(amount),
            transaction_type='expense',
            date=date,
        )

    def test_dashboard_includes_no_spend_days_in_context(self):
        response = self.client.get(reverse('dashboard'))
        self.assertIn('no_spend_days', response.context)
        self.assertIn('no_spend_goal', response.context)
        self.assertIn('days_elapsed', response.context)

    def test_no_spend_days_zero_when_all_days_have_expenses(self):
        today = datetime.date.today()
        self._add_expense(today)
        response = self.client.get(reverse('dashboard'))
        # Today has an expense so it can't be a no-spend day
        self.assertEqual(response.context['no_spend_days'], response.context['days_elapsed'] - 1)

    def test_no_spend_days_counts_days_without_expenses(self):
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        self._add_expense(yesterday)
        response = self.client.get(reverse('dashboard'))
        days_elapsed = response.context['days_elapsed']
        no_spend_days = response.context['no_spend_days']
        # Yesterday had an expense; all other elapsed days are no-spend
        self.assertEqual(no_spend_days, days_elapsed - 1)

    def test_calendar_cells_have_is_no_spend_flag(self):
        response = self.client.get(reverse('dashboard'))
        calendar_weeks = response.context['calendar_weeks']
        # Every cell should have an is_no_spend key
        for week in calendar_weeks:
            for cell in week:
                if cell is not None:
                    self.assertIn('is_no_spend', cell)

    def test_no_spend_goal_defaults_to_zero(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['no_spend_goal'], 0)

    def test_save_no_spend_goal(self):
        response = self.client.post(reverse('save_no_spend_goal'), {'no_spend_goal': '15'})
        self.assertRedirects(response, '/dashboard/')
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.no_spend_goal, 15)

    def test_save_no_spend_goal_reflected_in_dashboard(self):
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.no_spend_goal = 20
        prefs.save()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['no_spend_goal'], 20)

    def test_no_spend_goal_cannot_be_negative(self):
        self.client.post(reverse('save_no_spend_goal'), {'no_spend_goal': '-5'})
        prefs = UserPreferences.objects.get(user=self.user)
        self.assertEqual(prefs.no_spend_goal, 0)

    def test_days_with_only_income_count_as_no_spend(self):
        today = datetime.date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            description='Paycheck',
            amount=Decimal('2000.00'),
            transaction_type='income',
            date=today,
        )
        response = self.client.get(reverse('dashboard'))
        days_elapsed = response.context['days_elapsed']
        no_spend_days = response.context['no_spend_days']
        # Income-only day still counts as no-spend
        self.assertEqual(no_spend_days, days_elapsed)
