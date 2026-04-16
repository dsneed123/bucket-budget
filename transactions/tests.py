import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket

from .models import Transaction

User = get_user_model()


class TransactionModelTest(TestCase):
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
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )

    def _make_transaction(self, **kwargs):
        defaults = dict(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Test transaction',
            date=datetime.date(2026, 4, 16),
        )
        defaults.update(kwargs)
        return Transaction.objects.create(**defaults)

    def test_create_basic_transaction(self):
        txn = self._make_transaction()
        self.assertEqual(txn.transaction_type, 'expense')
        self.assertEqual(txn.amount, Decimal('50.00'))
        self.assertIsNone(txn.bucket)
        self.assertEqual(txn.vendor, '')
        self.assertEqual(txn.notes, '')
        self.assertFalse(txn.is_recurring)
        self.assertIsNone(txn.necessity_score)
        self.assertIsNotNone(txn.created_at)

    def test_create_transaction_with_bucket(self):
        txn = self._make_transaction(bucket=self.bucket)
        self.assertEqual(txn.bucket, self.bucket)

    def test_bucket_nullable(self):
        txn = self._make_transaction(bucket=None)
        self.assertIsNone(txn.bucket)

    def test_transaction_types(self):
        for txn_type in ('expense', 'income', 'transfer'):
            txn = self._make_transaction(transaction_type=txn_type)
            self.assertEqual(txn.transaction_type, txn_type)

    def test_necessity_score_valid_range(self):
        for score in (1, 5, 10):
            txn = self._make_transaction(necessity_score=score)
            txn.full_clean()
            self.assertEqual(txn.necessity_score, score)

    def test_necessity_score_below_min_fails(self):
        txn = self._make_transaction(necessity_score=0)
        with self.assertRaises(ValidationError):
            txn.full_clean()

    def test_necessity_score_above_max_fails(self):
        txn = self._make_transaction(necessity_score=11)
        with self.assertRaises(ValidationError):
            txn.full_clean()

    def test_str_representation(self):
        txn = self._make_transaction(description='Groceries run')
        self.assertIn('expense', str(txn))
        self.assertIn('Groceries run', str(txn))

    def test_ordering_by_date_desc(self):
        txn1 = self._make_transaction(date=datetime.date(2026, 4, 1))
        txn2 = self._make_transaction(date=datetime.date(2026, 4, 15))
        results = list(Transaction.objects.filter(user=self.user))
        self.assertEqual(results[0], txn2)
        self.assertEqual(results[1], txn1)


class TransactionAddViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='view@example.com',
            password='testpass',
            first_name='View',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )
        self.client.login(email='view@example.com', password='testpass')
        self.url = reverse('transaction_add')

    def _post(self, **overrides):
        data = {
            'amount': '25.00',
            'transaction_type': 'expense',
            'description': 'Test purchase',
            'vendor': 'Test Store',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'New Transaction')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_successful_expense_creates_transaction_and_reduces_balance(self):
        response = self._post()
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.transaction_type, 'expense')
        self.assertEqual(txn.amount, Decimal('25.00'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('475.00'))

    def test_successful_income_creates_transaction_and_increases_balance(self):
        response = self._post(transaction_type='income', amount='100.00')
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.transaction_type, 'income')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('600.00'))

    def test_expense_with_bucket_assigns_bucket(self):
        response = self._post(bucket=str(self.bucket.pk))
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.bucket, self.bucket)

    def test_missing_amount_shows_error(self):
        response = self._post(amount='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amount is required')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_zero_amount_shows_error(self):
        response = self._post(amount='0')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'greater than zero')

    def test_missing_description_shows_error(self):
        response = self._post(description='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Description is required')

    def test_missing_account_shows_error(self):
        response = self._post(account='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account is required')

    def test_cannot_use_another_users_account(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        response = self._post(account=str(other_account.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'valid account')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_balance_history_created_on_expense(self):
        from banking.models import BalanceHistory
        self._post()
        history = BalanceHistory.objects.filter(account=self.account).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.change_reason, 'transaction')

    def test_necessity_score_saved_for_expense(self):
        response = self._post(necessity_score='7')
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.necessity_score, 7)

    def test_necessity_score_omitted_saves_null(self):
        response = self._post()
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertIsNone(txn.necessity_score)

    def test_necessity_score_ignored_for_income(self):
        response = self._post(transaction_type='income', necessity_score='5')
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertIsNone(txn.necessity_score)

    def test_necessity_score_out_of_range_shows_error(self):
        response = self._post(necessity_score='11')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'between 1 and 10')
        self.assertEqual(Transaction.objects.count(), 0)
