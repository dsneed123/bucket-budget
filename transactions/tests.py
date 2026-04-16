import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

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
