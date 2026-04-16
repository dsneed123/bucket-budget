from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from .context_processors import net_worth
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


class NetWorthContextProcessorTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )

    def _request(self, authenticated=True):
        request = self.factory.get('/')
        if authenticated:
            request.user = self.user
        else:
            from django.contrib.auth.models import AnonymousUser
            request.user = AnonymousUser()
        return request

    def test_unauthenticated_returns_empty(self):
        result = net_worth(self._request(authenticated=False))
        self.assertEqual(result, {})

    def test_no_accounts_returns_zero(self):
        result = net_worth(self._request())
        self.assertEqual(result['net_worth'], 0)

    def test_sums_active_account_balances(self):
        BankAccount.objects.create(user=self.user, name='Checking', account_type='checking', balance=Decimal('1000.00'))
        BankAccount.objects.create(user=self.user, name='Savings', account_type='savings', balance=Decimal('500.00'))
        result = net_worth(self._request())
        self.assertEqual(result['net_worth'], Decimal('1500.00'))

    def test_excludes_inactive_accounts(self):
        BankAccount.objects.create(user=self.user, name='Checking', account_type='checking', balance=Decimal('1000.00'))
        BankAccount.objects.create(user=self.user, name='Closed', account_type='savings', balance=Decimal('500.00'), is_active=False)
        result = net_worth(self._request())
        self.assertEqual(result['net_worth'], Decimal('1000.00'))

    def test_negative_net_worth(self):
        BankAccount.objects.create(user=self.user, name='Credit', account_type='credit', balance=Decimal('-2000.00'))
        result = net_worth(self._request())
        self.assertEqual(result['net_worth'], Decimal('-2000.00'))
