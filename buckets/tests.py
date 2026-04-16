from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

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


class BucketReorderViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='reorder@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='reorder@example.com', password='testpass')
        # Remove default buckets created by the post_save signal so tests are isolated
        Bucket.objects.filter(user=self.user).delete()
        self.b1 = Bucket.objects.create(
            user=self.user, name='Alpha', monthly_allocation=Decimal('100'), sort_order=0
        )
        self.b2 = Bucket.objects.create(
            user=self.user, name='Beta', monthly_allocation=Decimal('100'), sort_order=1
        )
        self.b3 = Bucket.objects.create(
            user=self.user, name='Gamma', monthly_allocation=Decimal('100'), sort_order=2
        )

    def _order(self):
        return list(
            Bucket.objects.filter(user=self.user, is_active=True)
            .order_by('sort_order', 'name')
            .values_list('name', flat=True)
        )

    def test_move_down(self):
        self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b1.pk, 'direction': 'down'},
        )
        self.assertEqual(self._order(), ['Beta', 'Alpha', 'Gamma'])

    def test_move_up(self):
        self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b3.pk, 'direction': 'up'},
        )
        self.assertEqual(self._order(), ['Alpha', 'Gamma', 'Beta'])

    def test_move_first_up_is_noop(self):
        self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b1.pk, 'direction': 'up'},
        )
        self.assertEqual(self._order(), ['Alpha', 'Beta', 'Gamma'])

    def test_move_last_down_is_noop(self):
        self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b3.pk, 'direction': 'down'},
        )
        self.assertEqual(self._order(), ['Alpha', 'Beta', 'Gamma'])

    def test_redirects_to_bucket_list(self):
        response = self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b2.pk, 'direction': 'up'},
        )
        self.assertRedirects(response, reverse('bucket_list'), fetch_redirect_response=False)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': self.b1.pk, 'direction': 'down'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('bucket_list', response['Location'])

    def test_cannot_reorder_other_users_buckets(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        Bucket.objects.filter(user=other_user).delete()
        other_bucket = Bucket.objects.create(
            user=other_user, name='Other', monthly_allocation=Decimal('100'), sort_order=0
        )
        self.client.post(
            reverse('bucket_reorder'),
            {'bucket_id': other_bucket.pk, 'direction': 'down'},
        )
        # self.user's order should be unchanged
        self.assertEqual(self._order(), ['Alpha', 'Beta', 'Gamma'])
