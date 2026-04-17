import csv
import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket

from .models import CsvColumnMapping, RecurringTransaction, Tag, Transaction, VendorMapping
from .views import _csv_source_key, _resolve_tags

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

    def test_duplicate_detection_shows_warning(self):
        # Create an existing transaction with same amount, vendor, date
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('25.00'),
            transaction_type='expense',
            description='Previous purchase',
            vendor='Test Store',
            date=datetime.date(2026, 4, 16),
        )
        response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Similar transaction found')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_duplicate_detection_within_7_days(self):
        # Existing transaction 5 days before new one — should trigger warning
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('25.00'),
            transaction_type='expense',
            description='Previous purchase',
            vendor='Test Store',
            date=datetime.date(2026, 4, 11),
        )
        response = self._post(date='2026-04-16')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Similar transaction found')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_duplicate_not_triggered_beyond_7_days(self):
        # Existing transaction 8 days before — should not trigger warning
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('25.00'),
            transaction_type='expense',
            description='Old purchase',
            vendor='Test Store',
            date=datetime.date(2026, 4, 8),
        )
        response = self._post(date='2026-04-16')
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_duplicate_not_triggered_without_vendor(self):
        # No vendor — duplicate detection is skipped
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('25.00'),
            transaction_type='expense',
            description='Test purchase',
            vendor='',
            date=datetime.date(2026, 4, 16),
        )
        response = self._post(vendor='')
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_force_save_bypasses_duplicate_warning(self):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('25.00'),
            transaction_type='expense',
            description='Previous purchase',
            vendor='Test Store',
            date=datetime.date(2026, 4, 16),
        )
        response = self._post(force_save='1')
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.count(), 2)


class TransactionEditViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='edit@example.com',
            password='testpass',
            first_name='Edit',
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
        self.client.login(email='edit@example.com', password='testpass')
        # Create a transaction directly (bypassing view so balance stays at 500)
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Initial purchase',
            date=datetime.date(2026, 4, 16),
        )
        # Manually set balance to reflect the existing transaction
        self.account.balance = Decimal('450.00')
        self.account.save()
        self.url = reverse('transaction_edit', args=[self.transaction.pk])

    def _post(self, **overrides):
        data = {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Initial purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_get_renders_prepopulated_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Transaction')
        self.assertContains(response, 'Initial purchase')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_cannot_edit_other_users_transaction(self):
        other_user = User.objects.create_user(
            email='other2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('200.00'),
        )
        other_txn = Transaction.objects.create(
            user=other_user,
            account=other_account,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='Other transaction',
            date=datetime.date(2026, 4, 16),
        )
        url = reverse('transaction_edit', args=[other_txn.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_edit_updates_description(self):
        response = self._post(description='Updated purchase')
        self.assertRedirects(response, reverse('transaction_list'))
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.description, 'Updated purchase')

    def test_edit_expense_same_amount_balance_unchanged(self):
        response = self._post()
        self.assertRedirects(response, reverse('transaction_list'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('450.00'))

    def test_edit_expense_new_amount_adjusts_balance(self):
        response = self._post(amount='30.00')
        self.assertRedirects(response, reverse('transaction_list'))
        # Old: -50, reverse: +50 → 500; new: -30 → 470
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('470.00'))

    def test_edit_expense_to_income_adjusts_balance(self):
        response = self._post(transaction_type='income', amount='50.00')
        self.assertRedirects(response, reverse('transaction_list'))
        # Old expense -50, reverse: +50 → 500; new income +50 → 550
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('550.00'))

    def test_edit_to_different_account_adjusts_both_balances(self):
        second_account = BankAccount.objects.create(
            user=self.user,
            name='Savings',
            account_type='savings',
            balance=Decimal('1000.00'),
        )
        response = self._post(account=str(second_account.pk))
        self.assertRedirects(response, reverse('transaction_list'))
        # Old account: reverse expense +50 → 500
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))
        # New account: apply expense -50 → 950
        second_account.refresh_from_db()
        self.assertEqual(second_account.balance, Decimal('950.00'))

    def test_edit_balance_history_created(self):
        from banking.models import BalanceHistory
        count_before = BalanceHistory.objects.filter(account=self.account).count()
        self._post(amount='30.00')
        count_after = BalanceHistory.objects.filter(account=self.account).count()
        self.assertGreater(count_after, count_before)

    def test_missing_amount_shows_error(self):
        response = self._post(amount='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amount is required')

    def test_missing_description_shows_error(self):
        response = self._post(description='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Description is required')

    def test_cannot_use_another_users_account(self):
        other_user = User.objects.create_user(
            email='other3@example.com',
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

    def test_necessity_score_updated(self):
        response = self._post(necessity_score='8')
        self.assertRedirects(response, reverse('transaction_list'))
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.necessity_score, 8)

    def test_necessity_score_cleared_when_type_changes_to_income(self):
        self.transaction.necessity_score = 7
        self.transaction.save()
        response = self._post(transaction_type='income', necessity_score='7')
        self.assertRedirects(response, reverse('transaction_list'))
        self.transaction.refresh_from_db()
        self.assertIsNone(self.transaction.necessity_score)


class TransactionDeleteViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='delete@example.com',
            password='testpass',
            first_name='Delete',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.client.login(email='delete@example.com', password='testpass')
        self.transaction = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Purchase to delete',
            date=datetime.date(2026, 4, 16),
        )
        self.url = reverse('transaction_delete', args=[self.transaction.pk])

    def test_get_renders_confirmation_page(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Purchase to delete')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_cannot_delete_other_users_transaction(self):
        other_user = User.objects.create_user(
            email='other4@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('200.00'),
        )
        other_txn = Transaction.objects.create(
            user=other_user,
            account=other_account,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='Other transaction',
            date=datetime.date(2026, 4, 16),
        )
        url = reverse('transaction_delete', args=[other_txn.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_delete_expense_removes_transaction_and_restores_balance(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertFalse(Transaction.objects.filter(pk=self.transaction.pk).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))

    def test_delete_income_removes_transaction_and_reduces_balance(self):
        income_txn = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('100.00'),
            transaction_type='income',
            description='Income to delete',
            date=datetime.date(2026, 4, 16),
        )
        # Manually reflect the income in balance
        self.account.balance = Decimal('550.00')
        self.account.save()

        url = reverse('transaction_delete', args=[income_txn.pk])
        response = self.client.post(url)
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertFalse(Transaction.objects.filter(pk=income_txn.pk).exists())
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('450.00'))

    def test_delete_creates_balance_history(self):
        from banking.models import BalanceHistory
        count_before = BalanceHistory.objects.filter(account=self.account).count()
        self.client.post(self.url)
        count_after = BalanceHistory.objects.filter(account=self.account).count()
        self.assertGreater(count_after, count_before)


class TransactionAddSplitViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='split@example.com',
            password='testpass',
            first_name='Split',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.bucket1 = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )
        self.bucket2 = Bucket.objects.create(
            user=self.user,
            name='Shopping',
            monthly_allocation=Decimal('200.00'),
        )
        self.client.login(email='split@example.com', password='testpass')
        self.url = reverse('transaction_add_split')

    def _post(self, **overrides):
        data = {
            'transaction_type': 'expense',
            'description': 'Costco run',
            'vendor': 'Costco',
            'account': str(self.account.pk),
            'date': '2026-04-16',
            'total_amount': '100.00',
            'split_amount': ['60.00', '40.00'],
            'split_bucket': [str(self.bucket1.pk), str(self.bucket2.pk)],
        }
        data.update(overrides)
        return self.client.post(self.url, data)

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Split Transaction')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_successful_split_creates_two_transactions(self):
        response = self._post()
        self.assertRedirects(response, reverse('transaction_list'))
        txns = Transaction.objects.filter(user=self.user, description='Costco run').order_by('amount')
        self.assertEqual(txns.count(), 2)
        amounts = [t.amount for t in txns]
        self.assertIn(Decimal('40.00'), amounts)
        self.assertIn(Decimal('60.00'), amounts)

    def test_split_transactions_share_same_split_group(self):
        self._post()
        txns = Transaction.objects.filter(user=self.user, description='Costco run')
        groups = set(t.split_group for t in txns)
        self.assertEqual(len(groups), 1)
        self.assertIsNotNone(list(groups)[0])

    def test_split_reduces_account_balance_by_total(self):
        self._post()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('400.00'))

    def test_split_assigns_buckets_correctly(self):
        self._post()
        txns = {t.bucket_id: t for t in Transaction.objects.filter(user=self.user, description='Costco run')}
        self.assertIn(self.bucket1.pk, txns)
        self.assertIn(self.bucket2.pk, txns)
        self.assertEqual(txns[self.bucket1.pk].amount, Decimal('60.00'))
        self.assertEqual(txns[self.bucket2.pk].amount, Decimal('40.00'))

    def test_split_with_no_bucket_is_allowed(self):
        response = self._post(**{
            'split_amount': ['60.00', '40.00'],
            'split_bucket': ['', ''],
        })
        self.assertRedirects(response, reverse('transaction_list'))
        txns = Transaction.objects.filter(user=self.user, description='Costco run')
        self.assertEqual(txns.count(), 2)
        for t in txns:
            self.assertIsNone(t.bucket)

    def test_missing_description_shows_error(self):
        response = self._post(description='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Description is required')
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_missing_account_shows_error(self):
        response = self._post(account='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account is required')

    def test_only_one_split_row_shows_error(self):
        response = self._post(**{
            'split_amount': ['100.00'],
            'split_bucket': [''],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'At least two splits')

    def test_zero_amount_split_shows_error(self):
        response = self._post(**{
            'split_amount': ['0.00', '40.00'],
            'split_bucket': ['', ''],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_invalid_amount_shows_error(self):
        response = self._post(**{
            'split_amount': ['abc', '40.00'],
            'split_bucket': ['', ''],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_other_user_account_rejected(self):
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
            balance=Decimal('200.00'),
        )
        response = self._post(account=str(other_account.pk))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'valid account')
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_income_split_increases_balance(self):
        response = self._post(transaction_type='income')
        self.assertRedirects(response, reverse('transaction_list'))
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('600.00'))

    def test_missing_total_amount_shows_error(self):
        response = self._post(total_amount='')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Total amount is required')
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_splits_not_equal_to_total_shows_error(self):
        response = self._post(total_amount='150.00')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'unallocated')
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)

    def test_splits_over_total_shows_error(self):
        response = self._post(**{
            'total_amount': '80.00',
            'split_amount': ['60.00', '40.00'],
            'split_bucket': ['', ''],
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'over by')
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 0)


class TagModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='tags@example.com',
            password='testpass',
            first_name='Tag',
            last_name='User',
        )

    def test_create_tag(self):
        tag = Tag.objects.create(user=self.user, name='groceries', color='#00d4aa')
        self.assertEqual(tag.name, 'groceries')
        self.assertEqual(tag.color, '#00d4aa')
        self.assertEqual(tag.user, self.user)

    def test_tag_default_color(self):
        tag = Tag.objects.create(user=self.user, name='travel')
        self.assertEqual(tag.color, '#0984e3')

    def test_tag_str(self):
        tag = Tag.objects.create(user=self.user, name='recurring')
        self.assertEqual(str(tag), 'recurring')

    def test_tag_unique_per_user(self):
        from django.db import IntegrityError
        Tag.objects.create(user=self.user, name='food')
        with self.assertRaises(IntegrityError):
            Tag.objects.create(user=self.user, name='food')

    def test_tag_name_not_unique_across_users(self):
        other_user = User.objects.create_user(
            email='other_tags@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        Tag.objects.create(user=self.user, name='food')
        # Should not raise — different user
        tag2 = Tag.objects.create(user=other_user, name='food')
        self.assertEqual(tag2.name, 'food')

    def test_tag_ordering_by_name(self):
        Tag.objects.create(user=self.user, name='zebra')
        Tag.objects.create(user=self.user, name='apple')
        Tag.objects.create(user=self.user, name='mango')
        names = list(Tag.objects.filter(user=self.user).values_list('name', flat=True))
        self.assertEqual(names, sorted(names))


class ResolveTagsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='resolve@example.com',
            password='testpass',
            first_name='Resolve',
            last_name='User',
        )

    def test_creates_new_tags(self):
        tags = _resolve_tags(self.user, 'groceries, travel')
        self.assertEqual(len(tags), 2)
        names = {t.name for t in tags}
        self.assertIn('groceries', names)
        self.assertIn('travel', names)
        self.assertEqual(Tag.objects.filter(user=self.user).count(), 2)

    def test_reuses_existing_tags(self):
        existing = Tag.objects.create(user=self.user, name='food', color='#ff4757')
        tags = _resolve_tags(self.user, 'food')
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0].pk, existing.pk)
        self.assertEqual(Tag.objects.filter(user=self.user).count(), 1)

    def test_case_insensitive_lookup(self):
        existing = Tag.objects.create(user=self.user, name='groceries', color='#ff4757')
        tags = _resolve_tags(self.user, 'Groceries')
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0].pk, existing.pk)

    def test_empty_string_returns_no_tags(self):
        tags = _resolve_tags(self.user, '')
        self.assertEqual(tags, [])

    def test_blank_entries_are_skipped(self):
        tags = _resolve_tags(self.user, 'food, , ,travel')
        self.assertEqual(len(tags), 2)

    def test_assigns_color_from_palette(self):
        tags = _resolve_tags(self.user, 'first')
        self.assertIn(tags[0].color, [
            '#0984e3', '#00d4aa', '#f9ca24', '#ff4757',
            '#a29bfe', '#fd79a8', '#55efc4', '#fdcb6e',
            '#e17055', '#74b9ff',
        ])


class TagTransactionIntegrationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='tagtxn@example.com',
            password='testpass',
            first_name='Tag',
            last_name='Txn',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.client.login(email='tagtxn@example.com', password='testpass')

    def _post_add(self, **overrides):
        data = {
            'amount': '25.00',
            'transaction_type': 'expense',
            'description': 'Tagged purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
            'tags': '',
        }
        data.update(overrides)
        return self.client.post(reverse('transaction_add'), data)

    def test_add_transaction_with_tags_creates_tags(self):
        self._post_add(tags='groceries, travel')
        txn = Transaction.objects.get(user=self.user)
        tag_names = set(txn.tags.values_list('name', flat=True))
        self.assertEqual(tag_names, {'groceries', 'travel'})

    def test_add_transaction_without_tags_has_no_tags(self):
        self._post_add(tags='')
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.tags.count(), 0)

    def test_edit_transaction_updates_tags(self):
        txn = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Purchase',
            date=datetime.date(2026, 4, 16),
        )
        tag = Tag.objects.create(user=self.user, name='old-tag')
        txn.tags.set([tag])

        self.client.post(reverse('transaction_edit', args=[txn.pk]), {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
            'tags': 'new-tag',
        })
        txn.refresh_from_db()
        tag_names = set(txn.tags.values_list('name', flat=True))
        self.assertEqual(tag_names, {'new-tag'})

    def test_edit_transaction_clears_tags_when_empty(self):
        txn = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Purchase',
            date=datetime.date(2026, 4, 16),
        )
        tag = Tag.objects.create(user=self.user, name='some-tag')
        txn.tags.set([tag])

        self.client.post(reverse('transaction_edit', args=[txn.pk]), {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
            'tags': '',
        })
        txn.refresh_from_db()
        self.assertEqual(txn.tags.count(), 0)

    def test_filter_by_tag_returns_only_tagged_transactions(self):
        tag = Tag.objects.create(user=self.user, name='filtered-tag')
        txn1 = Transaction.objects.create(
            user=self.user, account=self.account, amount=Decimal('10.00'),
            transaction_type='expense', description='Tagged', date=datetime.date(2026, 4, 16),
        )
        txn1.tags.set([tag])
        Transaction.objects.create(
            user=self.user, account=self.account, amount=Decimal('20.00'),
            transaction_type='expense', description='Untagged', date=datetime.date(2026, 4, 16),
        )

        response = self.client.get(reverse('transaction_list'), {'tag': str(tag.pk)})
        self.assertEqual(response.status_code, 200)
        txns = list(response.context['page_obj'])
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].pk, txn1.pk)

    def test_filter_by_invalid_tag_shows_all(self):
        Transaction.objects.create(
            user=self.user, account=self.account, amount=Decimal('10.00'),
            transaction_type='expense', description='Some txn', date=datetime.date(2026, 4, 16),
        )
        response = self.client.get(reverse('transaction_list'), {'tag': '99999'})
        self.assertEqual(response.status_code, 200)
        # Invalid tag ID is ignored — all transactions are shown
        self.assertEqual(response.context['page_obj'].paginator.count, 1)

    def test_transaction_list_shows_tag_filter_when_tags_exist(self):
        Tag.objects.create(user=self.user, name='show-me')
        response = self.client.get(reverse('transaction_list'))
        self.assertContains(response, 'show-me')

    def test_edit_form_prepopulates_existing_tags(self):
        txn = Transaction.objects.create(
            user=self.user, account=self.account, amount=Decimal('50.00'),
            transaction_type='expense', description='Purchase',
            date=datetime.date(2026, 4, 16),
        )
        tag = Tag.objects.create(user=self.user, name='prepop-tag')
        txn.tags.set([tag])

        response = self.client.get(reverse('transaction_edit', args=[txn.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'prepop-tag')


class VendorMappingModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='vendor@example.com',
            password='testpass',
            first_name='Vendor',
            last_name='User',
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )

    def test_create_vendor_mapping(self):
        vm = VendorMapping.objects.create(user=self.user, vendor_name='Whole Foods', bucket=self.bucket)
        self.assertEqual(vm.vendor_name, 'Whole Foods')
        self.assertEqual(vm.bucket, self.bucket)
        self.assertEqual(vm.user, self.user)

    def test_create_vendor_mapping_without_bucket(self):
        vm = VendorMapping.objects.create(user=self.user, vendor_name='Unknown Store')
        self.assertIsNone(vm.bucket)

    def test_str_representation(self):
        vm = VendorMapping.objects.create(user=self.user, vendor_name='Target')
        self.assertEqual(str(vm), 'Target')

    def test_unique_per_user_and_vendor(self):
        from django.db import IntegrityError
        VendorMapping.objects.create(user=self.user, vendor_name='Costco')
        with self.assertRaises(IntegrityError):
            VendorMapping.objects.create(user=self.user, vendor_name='Costco')

    def test_same_vendor_name_allowed_for_different_users(self):
        other_user = User.objects.create_user(
            email='vendor2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        VendorMapping.objects.create(user=self.user, vendor_name='Amazon')
        vm2 = VendorMapping.objects.create(user=other_user, vendor_name='Amazon')
        self.assertEqual(vm2.vendor_name, 'Amazon')

    def test_bucket_nulled_when_bucket_deleted(self):
        vm = VendorMapping.objects.create(user=self.user, vendor_name='Store', bucket=self.bucket)
        self.bucket.delete()
        vm.refresh_from_db()
        self.assertIsNone(vm.bucket)


class VendorAutocompleteViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='autocomplete@example.com',
            password='testpass',
            first_name='Auto',
            last_name='User',
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )
        self.client.login(email='autocomplete@example.com', password='testpass')
        self.url = reverse('vendor_autocomplete')

    def test_returns_json(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

    def test_returns_user_vendors(self):
        VendorMapping.objects.create(user=self.user, vendor_name='Walmart', bucket=self.bucket)
        VendorMapping.objects.create(user=self.user, vendor_name='Target')
        response = self.client.get(self.url)
        data = response.json()
        vendor_names = [v['vendor'] for v in data['vendors']]
        self.assertIn('Walmart', vendor_names)
        self.assertIn('Target', vendor_names)

    def test_does_not_return_other_users_vendors(self):
        other_user = User.objects.create_user(
            email='other_auto@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        VendorMapping.objects.create(user=other_user, vendor_name='Secret Store')
        response = self.client.get(self.url)
        data = response.json()
        vendor_names = [v['vendor'] for v in data['vendors']]
        self.assertNotIn('Secret Store', vendor_names)

    def test_bucket_id_included_in_response(self):
        VendorMapping.objects.create(user=self.user, vendor_name='Whole Foods', bucket=self.bucket)
        response = self.client.get(self.url)
        data = response.json()
        match = next(v for v in data['vendors'] if v['vendor'] == 'Whole Foods')
        self.assertEqual(match['bucket_id'], self.bucket.pk)

    def test_no_bucket_returns_null(self):
        VendorMapping.objects.create(user=self.user, vendor_name='No Bucket Store')
        response = self.client.get(self.url)
        data = response.json()
        match = next(v for v in data['vendors'] if v['vendor'] == 'No Bucket Store')
        self.assertIsNone(match['bucket_id'])


class VendorMappingIntegrationTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='vmint@example.com',
            password='testpass',
            first_name='VM',
            last_name='Int',
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
        self.client.login(email='vmint@example.com', password='testpass')

    def _post_add(self, **overrides):
        data = {
            'amount': '25.00',
            'transaction_type': 'expense',
            'description': 'Test purchase',
            'vendor': 'Whole Foods',
            'bucket': str(self.bucket.pk),
            'account': str(self.account.pk),
            'date': '2026-04-16',
        }
        data.update(overrides)
        return self.client.post(reverse('transaction_add'), data)

    def test_adding_transaction_with_vendor_creates_mapping(self):
        self._post_add()
        self.assertTrue(VendorMapping.objects.filter(user=self.user, vendor_name='Whole Foods').exists())

    def test_mapping_stores_bucket(self):
        self._post_add()
        vm = VendorMapping.objects.get(user=self.user, vendor_name='Whole Foods')
        self.assertEqual(vm.bucket, self.bucket)

    def test_adding_transaction_without_vendor_does_not_create_mapping(self):
        self._post_add(vendor='')
        self.assertEqual(VendorMapping.objects.filter(user=self.user).count(), 0)

    def test_second_transaction_updates_existing_mapping(self):
        other_bucket = Bucket.objects.create(
            user=self.user,
            name='Shopping',
            monthly_allocation=Decimal('200.00'),
        )
        self._post_add(bucket=str(self.bucket.pk))
        # Use a different amount to avoid duplicate detection
        self._post_add(amount='30.00', bucket=str(other_bucket.pk))
        vm = VendorMapping.objects.get(user=self.user, vendor_name='Whole Foods')
        self.assertEqual(vm.bucket, other_bucket)

    def test_vendor_case_insensitive_lookup_updates_existing(self):
        self._post_add(vendor='whole foods')
        self._post_add(vendor='Whole Foods')
        self.assertEqual(VendorMapping.objects.filter(user=self.user).count(), 1)

    def test_add_form_contains_datalist(self):
        response = self.client.get(reverse('transaction_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'vendor-suggestions')

    def test_add_form_includes_vendor_mappings_json(self):
        VendorMapping.objects.create(user=self.user, vendor_name='Test Market', bucket=self.bucket)
        response = self.client.get(reverse('transaction_add'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Market')


class TransactionExportCsvViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='export@example.com',
            password='testpass',
            first_name='Export',
            last_name='User',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
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
        self.client.login(email='export@example.com', password='testpass')
        self.url = reverse('transaction_export_csv')

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

    def _get_csv_rows(self, response):
        content = b''.join(response.streaming_content).decode('utf-8')
        reader = csv.reader(io.StringIO(content))
        return list(reader)

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_returns_csv_content_type(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')

    def test_content_disposition_attachment(self):
        response = self.client.get(self.url)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertIn('transactions.csv', response['Content-Disposition'])

    def test_csv_header_row(self):
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(rows[0], ['date', 'description', 'vendor', 'amount', 'type', 'bucket', 'account', 'necessity_score', 'tags'])

    def test_csv_contains_transaction_data(self):
        self._make_transaction(vendor='Whole Foods', bucket=self.bucket)
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(len(rows), 2)  # header + 1 transaction
        data_row = rows[1]
        self.assertEqual(data_row[0], '2026-04-16')
        self.assertEqual(data_row[1], 'Test transaction')
        self.assertEqual(data_row[2], 'Whole Foods')
        self.assertEqual(data_row[3], '50.00')
        self.assertEqual(data_row[4], 'expense')
        self.assertEqual(data_row[5], 'Groceries')
        self.assertEqual(data_row[6], 'Checking')

    def test_only_exports_own_transactions(self):
        other_account = BankAccount.objects.create(
            user=self.other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('100.00'),
        )
        self._make_transaction()
        Transaction.objects.create(
            user=self.other_user,
            account=other_account,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='Other user transaction',
            date=datetime.date(2026, 4, 16),
        )
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(len(rows), 2)  # header + 1 (own transaction only)

    def test_filter_by_type(self):
        self._make_transaction(transaction_type='expense')
        self._make_transaction(transaction_type='income', amount=Decimal('100.00'))
        response = self.client.get(self.url + '?type=expense')
        rows = self._get_csv_rows(response)
        self.assertEqual(len(rows), 2)  # header + 1 expense
        self.assertEqual(rows[1][4], 'expense')

    def test_filter_by_date_range(self):
        self._make_transaction(date=datetime.date(2026, 3, 1))
        self._make_transaction(date=datetime.date(2026, 4, 16))
        response = self.client.get(self.url + '?date_from=2026-04-01&date_to=2026-04-30')
        rows = self._get_csv_rows(response)
        self.assertEqual(len(rows), 2)  # header + 1

    def test_empty_export_has_only_header(self):
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(len(rows), 1)  # header only

    def test_tags_included_in_export(self):
        txn = self._make_transaction()
        tag = Tag.objects.create(user=self.user, name='food', color='#ff0000')
        txn.tags.add(tag)
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(rows[1][8], 'food')

    def test_necessity_score_included(self):
        self._make_transaction(necessity_score=7)
        response = self.client.get(self.url)
        rows = self._get_csv_rows(response)
        self.assertEqual(rows[1][7], '7')


class TransactionImportCsvViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='import@example.com',
            password='testpass',
            first_name='Import',
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
        self.client.login(email='import@example.com', password='testpass')
        self.url = reverse('transaction_import_csv')

    def _make_csv(self, content):
        """Return an in-memory CSV file-like object."""
        return io.BytesIO(content.encode('utf-8'))

    def _upload_to_mapping(self, csv_content, account=None, filename='test.csv'):
        """Upload a CSV and return the mapping-step response."""
        if account is None:
            account = self.account
        f = self._make_csv(csv_content)
        f.name = filename
        return self.client.post(self.url, {
            'step': 'upload',
            'account': str(account.pk),
            'csv_file': f,
        })

    def _post_mapping(self, mapping_response, override_mapping=None):
        """Submit the mapping form using auto-detected fields; optionally override."""
        ctx = mapping_response.context
        post_data = {
            'step': 'mapping',
            'account_id': ctx['account_id'],
            'source_key': ctx['source_key'],
            'raw_rows_json': ctx['raw_rows_json'],
        }
        for col in ctx['columns']:
            post_data[f'map_{col["name"]}'] = col['field']
        if override_mapping:
            post_data.update(override_mapping)
        return self.client.post(self.url, post_data)

    def _upload_and_preview(self, csv_content, account=None, filename='test.csv'):
        """Full upload → mapping → preview pipeline using auto-detected column mapping."""
        mapping_response = self._upload_to_mapping(csv_content, account, filename)
        return self._post_mapping(mapping_response)

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_get_shows_upload_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Upload CSV')
        self.assertContains(response, 'csv_file')

    def test_upload_missing_file_shows_error(self):
        response = self.client.post(self.url, {
            'step': 'upload',
            'account': str(self.account.pk),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please select a CSV file')

    def test_upload_missing_account_shows_error(self):
        csv_content = 'date,description,amount\n2026-01-15,Test,-10.00\n'
        f = self._make_csv(csv_content)
        f.name = 'test.csv'
        response = self.client.post(self.url, {
            'step': 'upload',
            'csv_file': f,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Account is required')

    def test_upload_missing_required_columns_shows_error(self):
        # CSV has date and description but no amount column.
        # Upload shows mapping step; submitting without mapping 'amount' shows error.
        csv_content = 'date,description\n2026-01-15,No amount column\n'
        mapping_response = self._upload_to_mapping(csv_content)
        self.assertEqual(mapping_response.status_code, 200)
        self.assertEqual(mapping_response.context['step'], 'mapping')
        # Submit with no amount field mapped → should stay on mapping with error
        response = self._post_mapping(mapping_response)  # auto-detect maps date+description only
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['step'], 'mapping')
        self.assertContains(response, 'amount')

    def test_upload_valid_csv_shows_mapping_then_preview(self):
        csv_content = 'date,description,amount\n2026-01-15,Grocery Store,-45.99\n'
        # Upload step → mapping
        mapping_response = self._upload_to_mapping(csv_content)
        self.assertEqual(mapping_response.status_code, 200)
        self.assertEqual(mapping_response.context['step'], 'mapping')
        # Mapping step → preview
        response = self._post_mapping(mapping_response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['step'], 'preview')
        self.assertEqual(response.context['ok_count'], 1)
        self.assertEqual(response.context['error_count'], 0)

    def test_preview_negative_amount_is_expense(self):
        csv_content = 'date,description,amount\n2026-01-15,Coffee,-5.00\n'
        response = self._upload_and_preview(csv_content)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['transaction_type'], 'expense')
        self.assertEqual(row['amount'], '5.00')

    def test_preview_positive_amount_is_income(self):
        csv_content = 'date,description,amount\n2026-01-16,Paycheck,2500.00\n'
        response = self._upload_and_preview(csv_content)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['transaction_type'], 'income')

    def test_preview_category_matched_to_bucket(self):
        csv_content = 'date,description,amount,category\n2026-01-15,Groceries,-20.00,Groceries\n'
        response = self._upload_and_preview(csv_content)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['bucket_id'], self.bucket.pk)
        self.assertEqual(row['bucket_name'], 'Groceries')

    def test_preview_unmatched_category_has_no_bucket(self):
        csv_content = 'date,description,amount,category\n2026-01-15,Tech,-99.00,Electronics\n'
        response = self._upload_and_preview(csv_content)
        row = response.context['preview_rows'][0]
        self.assertIsNone(row['bucket_id'])
        self.assertEqual(row['category'], 'Electronics')

    def test_preview_invalid_date_row_is_error(self):
        csv_content = 'date,description,amount\nnot-a-date,Bad Row,-10.00\n'
        response = self._upload_and_preview(csv_content)
        self.assertEqual(response.context['error_count'], 1)
        self.assertEqual(response.context['ok_count'], 0)

    def test_confirm_imports_transactions(self):
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '2026-01-15',
            'description': 'Grocery Store',
            'vendor': '',
            'amount': '45.99',
            'transaction_type': 'expense',
            'category': 'Groceries',
            'bucket_name': 'Groceries',
            'bucket_id': self.bucket.pk,
            'status': 'ok',
            'error': '',
        }])
        response = self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(self.account.pk),
            'rows_json': rows_json,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['step'], 'done')
        self.assertEqual(response.context['imported'], 1)
        self.assertEqual(response.context['skipped'], 0)
        self.assertEqual(Transaction.objects.filter(user=self.user, description='Grocery Store').count(), 1)
        txn = Transaction.objects.get(user=self.user, description='Grocery Store')
        self.assertEqual(txn.amount, Decimal('45.99'))
        self.assertEqual(txn.transaction_type, 'expense')
        self.assertEqual(txn.bucket, self.bucket)
        self.assertEqual(txn.date, datetime.date(2026, 1, 15))

    def test_confirm_skips_error_rows(self):
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '',
            'description': 'Bad Row',
            'vendor': '',
            'amount': '',
            'transaction_type': '',
            'category': '',
            'bucket_name': '',
            'bucket_id': None,
            'status': 'error',
            'error': 'missing date',
        }])
        response = self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(self.account.pk),
            'rows_json': rows_json,
        })
        self.assertEqual(response.context['imported'], 0)
        self.assertEqual(response.context['skipped'], 1)
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())

    def test_csv_with_bom_is_parsed(self):
        # utf-8-sig encoding prepends the BOM byte sequence automatically
        csv_content = 'date,description,amount\n2026-01-15,BOM Test,-10.00\n'
        bom_bytes = csv_content.encode('utf-8-sig')
        f = SimpleUploadedFile('bom.csv', bom_bytes, content_type='text/csv')
        mapping_response = self.client.post(self.url, {
            'step': 'upload',
            'account': str(self.account.pk),
            'csv_file': f,
        })
        self.assertEqual(mapping_response.context['step'], 'mapping')
        response = self._post_mapping(mapping_response)
        self.assertEqual(response.context['ok_count'], 1)

    def test_only_imports_to_own_account(self):
        """Attempting to confirm import with another user's account_id fails gracefully."""
        other_user = User.objects.create_user(
            email='other2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('100.00'),
        )
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '2026-01-15',
            'description': 'Test',
            'vendor': '',
            'amount': '10.00',
            'transaction_type': 'expense',
            'category': '',
            'bucket_name': '',
            'bucket_id': None,
            'status': 'ok',
            'error': '',
        }])
        response = self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(other_account.pk),
            'rows_json': rows_json,
        })
        # Should redirect (account not found for this user)
        self.assertEqual(response.status_code, 302)

    def test_auto_detect_preselects_common_columns(self):
        """Known column names are pre-selected in the mapping dropdowns."""
        csv_content = 'date,memo,amount\n2026-01-15,Coffee,-5.00\n'
        mapping_response = self._upload_to_mapping(csv_content)
        self.assertEqual(mapping_response.context['step'], 'mapping')
        columns = {col['name']: col['field'] for col in mapping_response.context['columns']}
        self.assertEqual(columns['date'], 'date')
        self.assertEqual(columns['memo'], 'description')
        self.assertEqual(columns['amount'], 'amount')

    def test_remember_mapping_persists_to_db(self):
        """Submitting the mapping form with remember_mapping=1 saves a CsvColumnMapping record."""
        csv_content = 'trans date,details,transaction amount\n2026-01-15,Lunch,-12.00\n'
        mapping_response = self._upload_to_mapping(csv_content)
        source_key = mapping_response.context['source_key']
        ctx = mapping_response.context
        post_data = {
            'step': 'mapping',
            'account_id': ctx['account_id'],
            'source_key': source_key,
            'raw_rows_json': ctx['raw_rows_json'],
            'remember_mapping': '1',
        }
        for col in ctx['columns']:
            post_data[f'map_{col["name"]}'] = col['field']
        self.client.post(self.url, post_data)
        self.assertTrue(
            CsvColumnMapping.objects.filter(user=self.user, source_key=source_key).exists()
        )

    def test_saved_mapping_loaded_on_repeat_upload(self):
        """Re-uploading a CSV with the same headers loads the previously saved mapping."""
        headers = ['txn_date', 'note', 'amt']
        source_key = _csv_source_key(headers)
        CsvColumnMapping.objects.create(
            user=self.user,
            source_key=source_key,
            mapping={'txn_date': 'date', 'note': 'description', 'amt': 'amount'},
        )
        csv_content = 'txn_date,note,amt\n2026-02-01,Groceries,-30.00\n'
        mapping_response = self._upload_to_mapping(csv_content)
        self.assertEqual(mapping_response.context['step'], 'mapping')
        self.assertTrue(mapping_response.context['saved_mapping_found'])
        columns = {col['name']: col['field'] for col in mapping_response.context['columns']}
        self.assertEqual(columns['txn_date'], 'date')
        self.assertEqual(columns['note'], 'description')
        self.assertEqual(columns['amt'], 'amount')

    def test_saved_mapping_indicator_shown_in_template(self):
        """Template shows the 'Loaded saved mapping' notice when a saved mapping exists."""
        headers = ['xdate', 'xdesc', 'xamount']
        source_key = _csv_source_key(headers)
        CsvColumnMapping.objects.create(
            user=self.user,
            source_key=source_key,
            mapping={'xdate': 'date', 'xdesc': 'description', 'xamount': 'amount'},
        )
        csv_content = 'xdate,xdesc,xamount\n2026-03-01,Test,-1.00\n'
        mapping_response = self._upload_to_mapping(csv_content)
        self.assertContains(mapping_response, 'Loaded saved mapping')


class VendorMappingAutoCategorizeTest(TestCase):
    """Tests for vendor-to-bucket auto-categorization during CSV import."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='autocat@example.com',
            password='testpass',
            first_name='Auto',
            last_name='Cat',
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
        self.other_bucket = Bucket.objects.create(
            user=self.user,
            name='Dining',
            monthly_allocation=Decimal('150.00'),
        )
        VendorMapping.objects.create(
            user=self.user, vendor_name='Whole Foods', bucket=self.bucket,
        )
        self.client.login(email='autocat@example.com', password='testpass')
        self.url = reverse('transaction_import_csv')

    def _upload_to_mapping(self, csv_content, filename='test.csv'):
        f = io.BytesIO(csv_content.encode('utf-8'))
        f.name = filename
        return self.client.post(self.url, {
            'step': 'upload',
            'account': str(self.account.pk),
            'csv_file': f,
        })

    def _post_mapping(self, mapping_response):
        ctx = mapping_response.context
        post_data = {
            'step': 'mapping',
            'account_id': ctx['account_id'],
            'source_key': ctx['source_key'],
            'raw_rows_json': ctx['raw_rows_json'],
        }
        for col in ctx['columns']:
            post_data[f'map_{col["name"]}'] = col['field']
        return self.client.post(self.url, post_data)

    def test_vendor_column_auto_matches_bucket(self):
        """A vendor column value matching a VendorMapping auto-assigns the bucket."""
        csv_content = 'date,description,amount,vendor\n2026-01-15,Grocery run,-45.00,Whole Foods\n'
        mapping_response = self._upload_to_mapping(csv_content)
        response = self._post_mapping(mapping_response)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['bucket_id'], self.bucket.pk)
        self.assertEqual(row['match_source'], 'vendor')

    def test_category_column_takes_priority_over_vendor_map(self):
        """Explicit category column match wins over vendor mapping."""
        csv_content = 'date,description,amount,category,vendor\n2026-01-15,Dinner,-30.00,Dining,Whole Foods\n'
        mapping_response = self._upload_to_mapping(csv_content)
        response = self._post_mapping(mapping_response)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['bucket_id'], self.other_bucket.pk)
        self.assertEqual(row['match_source'], 'category')

    def test_unmatched_vendor_has_no_bucket(self):
        """A vendor not in VendorMapping leaves bucket_id as None."""
        csv_content = 'date,description,amount,vendor\n2026-01-15,Buy stuff,-20.00,Unknown Shop\n'
        mapping_response = self._upload_to_mapping(csv_content)
        response = self._post_mapping(mapping_response)
        row = response.context['preview_rows'][0]
        self.assertIsNone(row['bucket_id'])
        self.assertEqual(row['match_source'], '')

    def test_confirm_creates_vendor_mapping_for_imported_vendor(self):
        """Confirming import with vendor+bucket creates a VendorMapping entry."""
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '2026-01-15',
            'description': 'Grocery run',
            'vendor': 'Trader Joes',
            'amount': '30.00',
            'transaction_type': 'expense',
            'category': '',
            'bucket_name': '',
            'bucket_id': None,
            'match_source': '',
            'status': 'ok',
            'error': '',
        }])
        self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(self.account.pk),
            'rows_json': rows_json,
            f'bucket_2': str(self.bucket.pk),
        })
        self.assertTrue(
            VendorMapping.objects.filter(user=self.user, vendor_name='Trader Joes').exists()
        )
        vm = VendorMapping.objects.get(user=self.user, vendor_name='Trader Joes')
        self.assertEqual(vm.bucket, self.bucket)

    def test_confirm_no_vendor_mapping_created_without_bucket(self):
        """If bucket is not assigned, no VendorMapping is created."""
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '2026-01-15',
            'description': 'Mystery purchase',
            'vendor': 'Some Shop',
            'amount': '10.00',
            'transaction_type': 'expense',
            'category': '',
            'bucket_name': '',
            'bucket_id': None,
            'match_source': '',
            'status': 'ok',
            'error': '',
        }])
        self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(self.account.pk),
            'rows_json': rows_json,
            'bucket_2': '',  # no bucket selected
        })
        self.assertFalse(
            VendorMapping.objects.filter(user=self.user, vendor_name='Some Shop').exists()
        )

    def test_confirm_bucket_override_used_over_rows_json(self):
        """POST bucket override takes precedence over bucket_id in rows_json."""
        import json as _json
        rows_json = _json.dumps([{
            'row_num': 2,
            'date': '2026-01-15',
            'description': 'Dinner',
            'vendor': 'Nice Restaurant',
            'amount': '50.00',
            'transaction_type': 'expense',
            'category': '',
            'bucket_name': 'Groceries',
            'bucket_id': self.bucket.pk,  # auto-matched to Groceries
            'match_source': 'vendor',
            'status': 'ok',
            'error': '',
        }])
        self.client.post(self.url, {
            'step': 'confirm',
            'account_id': str(self.account.pk),
            'rows_json': rows_json,
            'bucket_2': str(self.other_bucket.pk),  # user overrides to Dining
        })
        txn = Transaction.objects.get(user=self.user, description='Dinner')
        self.assertEqual(txn.bucket, self.other_bucket)

    def test_description_used_as_vendor_fallback_for_lookup(self):
        """When no vendor column, description is checked against vendor map."""
        # VendorMapping uses the description as vendor_name
        VendorMapping.objects.create(
            user=self.user, vendor_name='Coffee Shop', bucket=self.other_bucket,
        )
        csv_content = 'date,description,amount\n2026-01-15,Coffee Shop,-5.00\n'
        mapping_response = self._upload_to_mapping(csv_content)
        response = self._post_mapping(mapping_response)
        row = response.context['preview_rows'][0]
        self.assertEqual(row['bucket_id'], self.other_bucket.pk)
        self.assertEqual(row['match_source'], 'vendor')


class RecurringListViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='recurring@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.other_account = BankAccount.objects.create(
            user=self.other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Entertainment',
            monthly_allocation=Decimal('100.00'),
        )
        self.rt = RecurringTransaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('15.99'),
            transaction_type='expense',
            description='Netflix',
            vendor='Netflix',
            frequency='monthly',
            start_date=datetime.date(2026, 1, 1),
            next_due=datetime.date(2026, 5, 1),
            is_active=True,
        )
        self.client.login(email='recurring@example.com', password='testpass')
        self.url = reverse('recurring_list')

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_list_renders(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Netflix')

    def test_only_shows_current_user_data(self):
        RecurringTransaction.objects.create(
            user=self.other_user,
            account=self.other_account,
            amount=Decimal('9.99'),
            transaction_type='expense',
            description='Other User Subscription',
            frequency='monthly',
            start_date=datetime.date(2026, 1, 1),
            next_due=datetime.date(2026, 5, 1),
        )
        response = self.client.get(self.url)
        self.assertContains(response, 'Netflix')
        self.assertNotContains(response, 'Other User Subscription')

    def test_total_monthly_cost_in_context(self):
        response = self.client.get(self.url)
        self.assertIn('total_monthly', response.context)
        self.assertAlmostEqual(float(response.context['total_monthly']), 15.99, places=1)

    def test_filter_by_frequency(self):
        RecurringTransaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('5.00'),
            transaction_type='expense',
            description='Weekly Coffee',
            frequency='weekly',
            start_date=datetime.date(2026, 1, 1),
            next_due=datetime.date(2026, 4, 20),
        )
        response = self.client.get(self.url, {'frequency': 'monthly'})
        self.assertContains(response, 'Netflix')
        self.assertNotContains(response, 'Weekly Coffee')

    def test_filter_by_status_active(self):
        inactive_rt = RecurringTransaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('8.00'),
            transaction_type='expense',
            description='Old Gym',
            frequency='monthly',
            start_date=datetime.date(2026, 1, 1),
            next_due=datetime.date(2026, 5, 1),
            is_active=False,
        )
        response = self.client.get(self.url, {'status': 'active'})
        self.assertContains(response, 'Netflix')
        self.assertNotContains(response, 'Old Gym')

        response = self.client.get(self.url, {'status': 'inactive'})
        self.assertNotContains(response, 'Netflix')
        self.assertContains(response, 'Old Gym')

    def test_toggle_active(self):
        toggle_url = reverse('recurring_toggle', args=[self.rt.pk])
        response = self.client.post(toggle_url)
        self.assertEqual(response.status_code, 302)
        self.rt.refresh_from_db()
        self.assertFalse(self.rt.is_active)

        self.client.post(toggle_url)
        self.rt.refresh_from_db()
        self.assertTrue(self.rt.is_active)

    def test_toggle_other_user_forbidden(self):
        self.client.logout()
        self.client.login(email='other@example.com', password='testpass')
        toggle_url = reverse('recurring_toggle', args=[self.rt.pk])
        response = self.client.post(toggle_url)
        self.assertEqual(response.status_code, 404)

    def test_delete(self):
        delete_url = reverse('recurring_delete', args=[self.rt.pk])
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RecurringTransaction.objects.filter(pk=self.rt.pk).exists())

    def test_delete_other_user_forbidden(self):
        self.client.logout()
        self.client.login(email='other@example.com', password='testpass')
        delete_url = reverse('recurring_delete', args=[self.rt.pk])
        response = self.client.post(delete_url)
        self.assertEqual(response.status_code, 404)


class RecurringAddViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='recadd@example.com',
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
        self.client.login(email='recadd@example.com', password='testpass')
        self.url = reverse('recurring_add')

    def test_get_renders_form(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add recurring transaction')

    def test_post_creates_recurring(self):
        response = self.client.post(self.url, {
            'description': 'Spotify',
            'vendor': 'Spotify',
            'amount': '9.99',
            'transaction_type': 'expense',
            'frequency': 'monthly',
            'account': self.account.pk,
            'start_date': '2026-01-01',
            'next_due': '2026-05-01',
            'is_active': '1',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(RecurringTransaction.objects.filter(user=self.user, description='Spotify').exists())

    def test_post_missing_required_fields(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'required')
        self.assertEqual(RecurringTransaction.objects.count(), 0)

    def test_redirect_if_not_logged_in(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


class ProcessRecurringCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='recurring_cmd@example.com',
            password='testpass',
            first_name='Cmd',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )

    def _make_recurring(self, next_due, frequency='monthly', is_active=True, end_date=None):
        return RecurringTransaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Netflix',
            frequency=frequency,
            start_date=datetime.date(2026, 1, 1),
            next_due=next_due,
            is_active=is_active,
            end_date=end_date,
        )

    def test_creates_transaction_for_due_recurring(self):
        from django.core.management import call_command
        self._make_recurring(next_due=datetime.date(2026, 4, 1))
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        self.assertEqual(Transaction.objects.count(), 1)
        txn = Transaction.objects.get()
        self.assertTrue(txn.is_recurring)
        self.assertEqual(txn.amount, Decimal('50.00'))
        self.assertEqual(txn.date, datetime.date(2026, 4, 1))

    def test_advances_next_due_monthly(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 4, 1), frequency='monthly')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2026, 5, 1))
        self.assertEqual(rt.last_generated, datetime.date(2026, 4, 1))

    def test_advances_next_due_weekly(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 4, 1), frequency='weekly')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2026, 4, 8))

    def test_advances_next_due_daily(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 4, 16), frequency='daily')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2026, 4, 17))

    def test_advances_next_due_biweekly(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 4, 1), frequency='biweekly')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2026, 4, 15))

    def test_advances_next_due_yearly(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 1, 15), frequency='yearly')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2027, 1, 15))

    def test_monthly_end_of_month_edge_case(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 1, 31), frequency='monthly')
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        rt.refresh_from_db()
        self.assertEqual(rt.next_due, datetime.date(2026, 2, 28))

    def test_skips_future_recurring(self):
        from django.core.management import call_command
        self._make_recurring(next_due=datetime.date(2026, 5, 1))
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_skips_inactive_recurring(self):
        from django.core.management import call_command
        self._make_recurring(next_due=datetime.date(2026, 4, 1), is_active=False)
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_skips_past_end_date(self):
        from django.core.management import call_command
        self._make_recurring(
            next_due=datetime.date(2026, 4, 1),
            end_date=datetime.date(2026, 3, 31),
        )
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_dry_run_makes_no_changes(self):
        from django.core.management import call_command
        self._make_recurring(next_due=datetime.date(2026, 4, 1))
        call_command('process_recurring', date='2026-04-16', dry_run=True, verbosity=0)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_transaction_fields_match_recurring(self):
        from django.core.management import call_command
        rt = self._make_recurring(next_due=datetime.date(2026, 4, 1))
        rt.vendor = 'Netflix Inc'
        rt.save()
        call_command('process_recurring', date='2026-04-16', verbosity=0)
        txn = Transaction.objects.get()
        self.assertEqual(txn.user, rt.user)
        self.assertEqual(txn.account, rt.account)
        self.assertEqual(txn.description, rt.description)
        self.assertEqual(txn.vendor, rt.vendor)
        self.assertEqual(txn.transaction_type, rt.transaction_type)


class TransactionBalanceSignalTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='balsignal@example.com',
            password='testpass',
            first_name='Signal',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )

    def _make_transaction(self, **kwargs):
        defaults = dict(
            user=self.user,
            account=self.account,
            amount=Decimal('100.00'),
            transaction_type='expense',
            description='Test',
            date=datetime.date(2026, 4, 16),
        )
        defaults.update(kwargs)
        return Transaction.objects.create(**defaults)

    def test_expense_decreases_balance(self):
        self._make_transaction(amount=Decimal('200.00'), transaction_type='expense')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('800.00'))

    def test_income_increases_balance(self):
        self._make_transaction(amount=Decimal('500.00'), transaction_type='income')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1500.00'))

    def test_delete_expense_reverses_balance(self):
        txn = self._make_transaction(amount=Decimal('150.00'), transaction_type='expense')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('850.00'))
        txn.delete()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_delete_income_reverses_balance(self):
        txn = self._make_transaction(amount=Decimal('300.00'), transaction_type='income')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1300.00'))
        txn.delete()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1000.00'))

    def test_multiple_expenses_accumulate(self):
        self._make_transaction(amount=Decimal('100.00'), transaction_type='expense')
        self._make_transaction(amount=Decimal('50.00'), transaction_type='expense')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('850.00'))


class RecurringTransactionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='recurmodel@example.com',
            password='testpass',
            first_name='Recur',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )

    def _make_recurring(self, **kwargs):
        defaults = dict(
            user=self.user,
            account=self.account,
            amount=Decimal('15.99'),
            transaction_type='expense',
            description='Netflix',
            frequency='monthly',
            start_date=datetime.date(2026, 1, 1),
            next_due=datetime.date(2026, 5, 1),
        )
        defaults.update(kwargs)
        return RecurringTransaction.objects.create(**defaults)

    def test_create_recurring_transaction(self):
        rt = self._make_recurring()
        self.assertEqual(rt.description, 'Netflix')
        self.assertEqual(rt.frequency, 'monthly')
        self.assertEqual(rt.amount, Decimal('15.99'))

    def test_is_active_by_default(self):
        rt = self._make_recurring()
        self.assertTrue(rt.is_active)

    def test_is_subscription_default_false(self):
        rt = self._make_recurring()
        self.assertFalse(rt.is_subscription)

    def test_frequency_choices(self):
        for freq in ('daily', 'weekly', 'biweekly', 'monthly', 'yearly'):
            rt = self._make_recurring(frequency=freq, description=f'{freq} payment')
            self.assertEqual(rt.frequency, freq)

    def test_next_due_stored(self):
        due = datetime.date(2026, 6, 15)
        rt = self._make_recurring(next_due=due)
        self.assertEqual(rt.next_due, due)

    def test_str_representation(self):
        rt = self._make_recurring(description='Spotify')
        self.assertIn('monthly', str(rt))
        self.assertIn('Spotify', str(rt))
