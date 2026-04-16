from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import BalanceHistory, BankAccount

User = get_user_model()


class BalanceHistoryModelTest(TestCase):
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
            balance=Decimal('1000.00'),
        )

    def test_no_history_on_create(self):
        self.assertEqual(BalanceHistory.objects.filter(account=self.account).count(), 0)

    def test_history_created_on_balance_change(self):
        self.account.balance = Decimal('1500.00')
        self.account.save()

        history = BalanceHistory.objects.get(account=self.account)
        self.assertEqual(history.previous_balance, Decimal('1000.00'))
        self.assertEqual(history.new_balance, Decimal('1500.00'))
        self.assertEqual(history.change_amount, Decimal('500.00'))
        self.assertEqual(history.change_reason, 'manual_update')
        self.assertIsNone(history.reference_id)

    def test_no_history_when_balance_unchanged(self):
        self.account.name = 'Updated Name'
        self.account.save()

        self.assertEqual(BalanceHistory.objects.filter(account=self.account).count(), 0)

    def test_custom_change_reason(self):
        self.account.balance = Decimal('900.00')
        self.account.save(change_reason='transaction', reference_id='txn_123')

        history = BalanceHistory.objects.get(account=self.account)
        self.assertEqual(history.change_reason, 'transaction')
        self.assertEqual(history.reference_id, 'txn_123')

    def test_negative_change_amount(self):
        self.account.balance = Decimal('750.00')
        self.account.save()

        history = BalanceHistory.objects.get(account=self.account)
        self.assertEqual(history.change_amount, Decimal('-250.00'))

    def test_multiple_balance_changes(self):
        self.account.balance = Decimal('1100.00')
        self.account.save()
        self.account.balance = Decimal('1200.00')
        self.account.save()

        self.assertEqual(BalanceHistory.objects.filter(account=self.account).count(), 2)

    def test_history_ordering(self):
        self.account.balance = Decimal('1100.00')
        self.account.save()
        self.account.balance = Decimal('1200.00')
        self.account.save()

        history = list(BalanceHistory.objects.filter(account=self.account))
        self.assertEqual(history[0].new_balance, Decimal('1200.00'))
        self.assertEqual(history[1].new_balance, Decimal('1100.00'))
