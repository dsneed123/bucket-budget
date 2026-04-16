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


class BucketRolloverTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='rollover@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='rollover@example.com', password='testpass')
        Bucket.objects.filter(user=self.user).delete()
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('500.00'),
        )

    def test_rollover_defaults_to_false(self):
        self.assertFalse(self.bucket.rollover)

    def test_rollover_amount_returns_zero(self):
        self.assertEqual(self.bucket.rollover_amount(), Decimal('0'))

    def test_edit_enables_rollover(self):
        self.client.post(
            reverse('bucket_edit', args=[self.bucket.pk]),
            {
                'name': 'Groceries',
                'monthly_allocation': '500.00',
                'icon': '💰',
                'color': '#0984e3',
                'description': '',
                'rollover': 'on',
            },
        )
        self.bucket.refresh_from_db()
        self.assertTrue(self.bucket.rollover)

    def test_edit_disables_rollover(self):
        self.bucket.rollover = True
        self.bucket.save()
        self.client.post(
            reverse('bucket_edit', args=[self.bucket.pk]),
            {
                'name': 'Groceries',
                'monthly_allocation': '500.00',
                'icon': '💰',
                'color': '#0984e3',
                'description': '',
            },
        )
        self.bucket.refresh_from_db()
        self.assertFalse(self.bucket.rollover)

    def test_bucket_list_includes_rollover_amount(self):
        self.bucket.rollover = True
        self.bucket.save()
        response = self.client.get(reverse('bucket_list'))
        self.assertEqual(response.status_code, 200)
        bucket_data = response.context['bucket_data']
        self.assertIn('rollover_amount', bucket_data[0])

    def test_bucket_list_rollover_amount_zero_when_rollover_disabled(self):
        response = self.client.get(reverse('bucket_list'))
        self.assertEqual(response.status_code, 200)
        bucket_data = response.context['bucket_data']
        self.assertEqual(bucket_data[0]['rollover_amount'], Decimal('0'))


class BucketAlertThresholdTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='alert@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='alert@example.com', password='testpass')
        Bucket.objects.filter(user=self.user).delete()
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('500.00'),
        )

    def test_alert_threshold_defaults_to_90(self):
        self.assertEqual(self.bucket.alert_threshold, 90)

    def test_bucket_list_includes_alert_flag(self):
        response = self.client.get(reverse('bucket_list'))
        self.assertEqual(response.status_code, 200)
        bucket_data = response.context['bucket_data']
        self.assertIn('alert', bucket_data[0])

    def test_bucket_list_alert_false_when_spending_below_threshold(self):
        # spending is 0, so alert should be False
        response = self.client.get(reverse('bucket_list'))
        bucket_data = response.context['bucket_data']
        self.assertFalse(bucket_data[0]['alert'])

    def test_bucket_list_alert_true_when_spending_at_threshold(self):
        # Set threshold to 0 so any spending (even 0%) would still require pct >= 0
        # Use threshold=1 and pct=0: alert should be False
        # Better: set threshold to 0 is invalid; use a bucket where pct >= threshold
        # Since spending is always 0 (placeholder), set threshold to 0 would be clamped to 1.
        # We verify alert=False since pct=0 < 90 (default).
        self.bucket.alert_threshold = 0  # 0 < 1, stored but pct=0 >= 0 would be True
        self.bucket.save()
        response = self.client.get(reverse('bucket_list'))
        bucket_data = response.context['bucket_data']
        # pct=0, alert_threshold=0: 0 >= 0 is True
        self.assertTrue(bucket_data[0]['alert'])

    def test_edit_updates_alert_threshold(self):
        self.client.post(
            reverse('bucket_edit', args=[self.bucket.pk]),
            {
                'name': 'Groceries',
                'monthly_allocation': '500.00',
                'icon': '💰',
                'color': '#0984e3',
                'description': '',
                'alert_threshold': '75',
            },
        )
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.alert_threshold, 75)

    def test_edit_invalid_threshold_keeps_existing(self):
        self.client.post(
            reverse('bucket_edit', args=[self.bucket.pk]),
            {
                'name': 'Groceries',
                'monthly_allocation': '500.00',
                'icon': '💰',
                'color': '#0984e3',
                'description': '',
                'alert_threshold': 'not-a-number',
            },
        )
        self.bucket.refresh_from_db()
        self.assertEqual(self.bucket.alert_threshold, 90)

    def test_alert_dot_shown_in_template_when_alert_true(self):
        # Force alert by setting threshold to 0
        self.bucket.alert_threshold = 0
        self.bucket.save()
        response = self.client.get(reverse('bucket_list'))
        self.assertContains(response, 'alert-dot')

    def test_alert_dot_not_shown_when_alert_false(self):
        # With default threshold 90 and 0% spending, no alert
        response = self.client.get(reverse('bucket_list'))
        self.assertNotContains(response, 'alert-dot')


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


class BucketArchiveViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='archive@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='archive@example.com', password='testpass')
        Bucket.objects.filter(user=self.user).delete()
        self.bucket = Bucket.objects.create(
            user=self.user, name='Groceries', monthly_allocation=Decimal('500'), sort_order=0
        )

    def test_archive_sets_is_active_false(self):
        self.client.post(reverse('bucket_archive', args=[self.bucket.pk]))
        self.bucket.refresh_from_db()
        self.assertFalse(self.bucket.is_active)

    def test_archive_sets_archived_at(self):
        self.client.post(reverse('bucket_archive', args=[self.bucket.pk]))
        self.bucket.refresh_from_db()
        self.assertIsNotNone(self.bucket.archived_at)

    def test_archive_redirects_to_bucket_list(self):
        response = self.client.post(reverse('bucket_archive', args=[self.bucket.pk]))
        self.assertRedirects(response, reverse('bucket_list'), fetch_redirect_response=False)

    def test_archive_get_shows_confirmation(self):
        response = self.client.get(reverse('bucket_archive', args=[self.bucket.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.bucket.name)

    def test_archived_bucket_not_in_active_list(self):
        self.client.post(reverse('bucket_archive', args=[self.bucket.pk]))
        active = list(
            Bucket.objects.filter(user=self.user, is_active=True).values_list('name', flat=True)
        )
        self.assertNotIn('Groceries', active)

    def test_unarchive_sets_is_active_true(self):
        self.bucket.is_active = False
        self.bucket.save()
        self.client.post(reverse('bucket_unarchive', args=[self.bucket.pk]))
        self.bucket.refresh_from_db()
        self.assertTrue(self.bucket.is_active)

    def test_unarchive_clears_archived_at(self):
        from django.utils import timezone
        self.bucket.is_active = False
        self.bucket.archived_at = timezone.now()
        self.bucket.save()
        self.client.post(reverse('bucket_unarchive', args=[self.bucket.pk]))
        self.bucket.refresh_from_db()
        self.assertIsNone(self.bucket.archived_at)

    def test_cannot_archive_other_users_bucket(self):
        other_user = User.objects.create_user(
            email='other2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        Bucket.objects.filter(user=other_user).delete()
        other_bucket = Bucket.objects.create(
            user=other_user, name='Other', monthly_allocation=Decimal('100'), sort_order=0
        )
        response = self.client.post(reverse('bucket_archive', args=[other_bucket.pk]))
        self.assertEqual(response.status_code, 404)
        other_bucket.refresh_from_db()
        self.assertTrue(other_bucket.is_active)

    def test_archive_requires_login(self):
        self.client.logout()
        response = self.client.post(reverse('bucket_archive', args=[self.bucket.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('bucket_list', response['Location'])

    def test_bucket_list_shows_archived_toggle(self):
        self.bucket.is_active = False
        self.bucket.save()
        response = self.client.get(reverse('bucket_list'))
        self.assertContains(response, 'Show archived')

    def test_bucket_list_shows_archived_buckets_when_toggled(self):
        self.bucket.is_active = False
        self.bucket.save()
        response = self.client.get(reverse('bucket_list') + '?show_archived=1')
        self.assertContains(response, 'Groceries')


class QuickAllocateViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='quickalloc@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.user.monthly_income = Decimal('3000.00')
        self.user.save()
        self.client.login(email='quickalloc@example.com', password='testpass')
        Bucket.objects.filter(user=self.user).delete()
        self.b1 = Bucket.objects.create(
            user=self.user, name='Groceries', monthly_allocation=Decimal('400.00'), sort_order=0
        )
        self.b2 = Bucket.objects.create(
            user=self.user, name='Rent', monthly_allocation=Decimal('1000.00'), sort_order=1
        )

    def test_get_returns_200(self):
        response = self.client.get(reverse('quick_allocate'))
        self.assertEqual(response.status_code, 200)

    def test_get_includes_monthly_income_in_context(self):
        response = self.client.get(reverse('quick_allocate'))
        self.assertEqual(response.context['monthly_income'], Decimal('3000.00'))

    def test_get_includes_bucket_rows_in_context(self):
        response = self.client.get(reverse('quick_allocate'))
        self.assertEqual(len(response.context['bucket_rows']), 2)

    def test_get_shows_bucket_names(self):
        response = self.client.get(reverse('quick_allocate'))
        self.assertContains(response, 'Groceries')
        self.assertContains(response, 'Rent')

    def test_get_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('quick_allocate'))
        self.assertEqual(response.status_code, 302)
        self.assertNotIn('quick_allocate', response['Location'])

    def test_post_updates_allocations(self):
        self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': '500.00',
            f'allocation_{self.b2.pk}': '1200.00',
        })
        self.b1.refresh_from_db()
        self.b2.refresh_from_db()
        self.assertEqual(self.b1.monthly_allocation, Decimal('500.00'))
        self.assertEqual(self.b2.monthly_allocation, Decimal('1200.00'))

    def test_post_redirects_to_bucket_list_on_success(self):
        response = self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': '500.00',
            f'allocation_{self.b2.pk}': '1200.00',
        })
        self.assertRedirects(response, reverse('bucket_list'), fetch_redirect_response=False)

    def test_post_invalid_value_does_not_save(self):
        self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': 'not-a-number',
            f'allocation_{self.b2.pk}': '1200.00',
        })
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.monthly_allocation, Decimal('400.00'))

    def test_post_negative_value_does_not_save(self):
        self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': '-50.00',
            f'allocation_{self.b2.pk}': '1200.00',
        })
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.monthly_allocation, Decimal('400.00'))

    def test_post_empty_value_treated_as_zero(self):
        self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': '',
            f'allocation_{self.b2.pk}': '1200.00',
        })
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.monthly_allocation, Decimal('0'))

    def test_post_only_updates_own_buckets(self):
        other_user = User.objects.create_user(
            email='other3@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        Bucket.objects.filter(user=other_user).delete()
        other_bucket = Bucket.objects.create(
            user=other_user, name='Other', monthly_allocation=Decimal('100'), sort_order=0
        )
        self.client.post(reverse('quick_allocate'), {
            f'allocation_{self.b1.pk}': '500.00',
            f'allocation_{self.b2.pk}': '1200.00',
            f'allocation_{other_bucket.pk}': '9999.00',
        })
        other_bucket.refresh_from_db()
        self.assertEqual(other_bucket.monthly_allocation, Decimal('100'))

    def test_bucket_list_has_quick_allocate_link(self):
        response = self.client.get(reverse('bucket_list'))
        self.assertContains(response, 'Quick Allocate')
