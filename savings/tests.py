import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from banking.models import BankAccount
from .models import SavingsContribution, SavingsGoal

User = get_user_model()


class SavingsContributionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('2000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('0.00'),
        )

    def test_contribution_deducts_from_account(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1800.00'))

    def test_contribution_adds_to_goal(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('300.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('300.00'))

    def test_contribution_creates_balance_history(self):
        from banking.models import BalanceHistory
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        history = BalanceHistory.objects.get(account=self.account)
        self.assertEqual(history.change_reason, 'savings_contribution')
        self.assertEqual(history.reference_id, str(contribution.pk))
        self.assertEqual(history.change_amount, Decimal('-100.00'))

    def test_delete_reverses_account_balance(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('500.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1500.00'))

        contribution.delete()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('2000.00'))

    def test_delete_reverses_goal_amount(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('400.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('400.00'))

        contribution.delete()
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('0.00'))

    def test_update_adjusts_account_balance(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1800.00'))

        contribution.amount = Decimal('300.00')
        contribution.save()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1700.00'))

    def test_update_adjusts_goal_amount(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('200.00'))

        contribution.amount = Decimal('350.00')
        contribution.save()
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('350.00'))

    def test_str(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date(2026, 4, 16),
        )
        self.assertEqual(str(contribution), 'Vacation +100.00 on 2026-04-16')

    def test_note_optional(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('50.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.assertEqual(contribution.note, '')

    def test_multiple_contributions_accumulate(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('150.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.goal.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1750.00'))
        self.assertEqual(self.goal.current_amount, Decimal('250.00'))
