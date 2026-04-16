from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Bucket

User = get_user_model()


class BucketSpendingMethodsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('500.00'),
        )

    def test_spent_this_month_returns_zero(self):
        self.assertEqual(self.bucket.spent_this_month(), Decimal('0'))

    def test_remaining_this_month_equals_allocation_when_nothing_spent(self):
        self.assertEqual(self.bucket.remaining_this_month(), Decimal('500.00'))

    def test_percentage_used_returns_zero_when_nothing_spent(self):
        self.assertEqual(self.bucket.percentage_used(), 0)

    def test_percentage_used_returns_zero_for_zero_allocation(self):
        self.bucket.monthly_allocation = Decimal('0')
        self.assertEqual(self.bucket.percentage_used(), 0)

    def test_percentage_used_capped_at_100(self):
        # Simulate overspend by temporarily patching spent_this_month
        original = self.bucket.spent_this_month
        self.bucket.spent_this_month = lambda: Decimal('600.00')
        self.assertEqual(self.bucket.percentage_used(), 100)
        self.bucket.spent_this_month = original

    def test_percentage_used_midpoint(self):
        self.bucket.spent_this_month = lambda: Decimal('250.00')
        self.assertEqual(self.bucket.percentage_used(), 50)
