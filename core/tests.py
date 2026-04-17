import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, UserPreferences
from banking.models import BankAccount
from transactions.models import Transaction, RecurringTransaction


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
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.onboarding_complete = True
        prefs.save()

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
        response = self.client.post(reverse('accounts:save_no_spend_goal'), {'no_spend_goal': '15'})
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
        self.client.post(reverse('accounts:save_no_spend_goal'), {'no_spend_goal': '-5'})
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


class BillCountdownTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            email='bills@example.com',
            password='testpass',
            first_name='Test',
        )
        self.client.login(email='bills@example.com', password='testpass')
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.onboarding_complete = True
        prefs.save()
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )

    def _add_recurring(self, description, amount, next_due, transaction_type='expense', is_active=True):
        return RecurringTransaction.objects.create(
            user=self.user,
            account=self.account,
            description=description,
            amount=Decimal(str(amount)),
            transaction_type=transaction_type,
            frequency='monthly',
            start_date=next_due,
            next_due=next_due,
            is_active=is_active,
        )

    def test_dashboard_includes_bill_countdown_in_context(self):
        response = self.client.get(reverse('dashboard'))
        self.assertIn('bill_countdown', response.context)

    def test_bill_above_threshold_appears_in_countdown(self):
        today = datetime.date.today()
        self._add_recurring('Rent', '1500.00', today + datetime.timedelta(days=5))
        response = self.client.get(reverse('dashboard'))
        entries = response.context['bill_countdown']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['item'].description, 'Rent')
        self.assertEqual(entries[0]['days_until'], 5)

    def test_bill_below_threshold_excluded(self):
        today = datetime.date.today()
        self._add_recurring('Streaming', '15.00', today + datetime.timedelta(days=3))
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(len(response.context['bill_countdown']), 0)

    def test_bill_exactly_at_threshold_included(self):
        today = datetime.date.today()
        self._add_recurring('Internet', '50.00', today + datetime.timedelta(days=10))
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(len(response.context['bill_countdown']), 1)

    def test_income_recurring_excluded_from_countdown(self):
        today = datetime.date.today()
        self._add_recurring('Salary', '3000.00', today + datetime.timedelta(days=5), transaction_type='income')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(len(response.context['bill_countdown']), 0)

    def test_inactive_recurring_excluded(self):
        today = datetime.date.today()
        self._add_recurring('Gym', '60.00', today + datetime.timedelta(days=5), is_active=False)
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(len(response.context['bill_countdown']), 0)

    def test_bill_beyond_30_days_excluded(self):
        today = datetime.date.today()
        self._add_recurring('Car Payment', '350.00', today + datetime.timedelta(days=31))
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(len(response.context['bill_countdown']), 0)

    def test_bills_ordered_by_due_date(self):
        today = datetime.date.today()
        self._add_recurring('Car Payment', '350.00', today + datetime.timedelta(days=12))
        self._add_recurring('Rent', '1500.00', today + datetime.timedelta(days=5))
        response = self.client.get(reverse('dashboard'))
        entries = response.context['bill_countdown']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['item'].description, 'Rent')
        self.assertEqual(entries[1]['item'].description, 'Car Payment')

    def test_bill_due_tomorrow_has_one_day_until(self):
        today = datetime.date.today()
        self._add_recurring('Rent', '1500.00', today + datetime.timedelta(days=1))
        response = self.client.get(reverse('dashboard'))
        entries = response.context['bill_countdown']
        self.assertEqual(entries[0]['days_until'], 1)


class IncomeReceivedTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = CustomUser.objects.create_user(
            email='income@example.com',
            password='testpass',
            first_name='Test',
        )
        self.client.login(email='income@example.com', password='testpass')
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.onboarding_complete = True
        prefs.save()
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )

    def _add_income(self, date, amount):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            description='Paycheck',
            amount=Decimal(str(amount)),
            transaction_type='income',
            date=date,
        )

    def test_dashboard_includes_income_context(self):
        response = self.client.get(reverse('dashboard'))
        self.assertIn('total_income', response.context)
        self.assertIn('monthly_income', response.context)
        self.assertIn('income_pct', response.context)

    def test_income_pct_zero_when_no_expected_income(self):
        self.user.monthly_income = Decimal('0')
        self.user.save()
        self._add_income(datetime.date.today(), '2000.00')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_pct'], 0)

    def test_income_pct_calculated_correctly(self):
        self.user.monthly_income = Decimal('5000.00')
        self.user.save()
        self._add_income(datetime.date.today(), '3000.00')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_pct'], 60)

    def test_income_pct_capped_at_100(self):
        self.user.monthly_income = Decimal('1000.00')
        self.user.save()
        self._add_income(datetime.date.today(), '2000.00')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_pct'], 100)

    def test_income_pct_100_when_fully_received(self):
        self.user.monthly_income = Decimal('5000.00')
        self.user.save()
        self._add_income(datetime.date.today(), '5000.00')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['income_pct'], 100)

    def test_expenses_do_not_count_toward_income(self):
        self.user.monthly_income = Decimal('5000.00')
        self.user.save()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            description='Groceries',
            amount=Decimal('200.00'),
            transaction_type='expense',
            date=datetime.date.today(),
        )
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['total_income'], Decimal('0'))
        self.assertEqual(response.context['income_pct'], 0)

    def test_monthly_income_reflects_user_setting(self):
        self.user.monthly_income = Decimal('4500.00')
        self.user.save()
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.context['monthly_income'], Decimal('4500.00'))
