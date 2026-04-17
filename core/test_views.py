import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import UserPreferences
from banking.models import BankAccount
from buckets.models import Bucket
from savings.models import SavingsGoal
from transactions.models import Transaction

User = get_user_model()


def _make_user(email='user@example.com', password='testpass', first_name='Test'):
    return User.objects.create_user(email=email, password=password, first_name=first_name)


def _make_account(user, name='Checking', balance=Decimal('1000.00')):
    return BankAccount.objects.create(
        user=user,
        name=name,
        account_type='checking',
        balance=balance,
        is_active=True,
    )


def _make_bucket(user, name='Groceries', allocation=Decimal('300.00')):
    return Bucket.objects.create(
        user=user,
        name=name,
        monthly_allocation=allocation,
        icon='🛒',
        color='#e17055',
        sort_order=99,
    )


def _make_transaction(user, account, bucket=None, amount=Decimal('50.00'), txn_type='expense'):
    return Transaction.objects.create(
        user=user,
        account=account,
        bucket=bucket,
        amount=amount,
        transaction_type=txn_type,
        description='Test transaction',
        date=datetime.date.today(),
    )


def _make_goal(user, name='Emergency Fund', target=Decimal('5000.00')):
    return SavingsGoal.objects.create(
        user=user,
        name=name,
        target_amount=target,
        current_amount=Decimal('0.00'),
        priority='medium',
        goal_type='general',
        icon='🎯',
        color='#00d4aa',
    )


# ---------------------------------------------------------------------------
# Login / Register
# ---------------------------------------------------------------------------

class LoginViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user()

    def test_get_login_page_returns_200(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 200)

    def test_post_valid_credentials_redirects(self):
        response = self.client.post(reverse('accounts:login'), {
            'email': 'user@example.com',
            'password': 'testpass',
        })
        self.assertIn(response.status_code, (301, 302))

    def test_post_invalid_password_shows_error(self):
        response = self.client.post(reverse('accounts:login'), {
            'email': 'user@example.com',
            'password': 'wrongpass',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('form', response.context['errors'])

    def test_post_nonexistent_email_shows_error(self):
        response = self.client.post(reverse('accounts:login'), {
            'email': 'nobody@example.com',
            'password': 'testpass',
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['errors'])

    def test_authenticated_user_redirected_away_from_login(self):
        self.client.login(email='user@example.com', password='testpass')
        response = self.client.get(reverse('accounts:login'))
        self.assertEqual(response.status_code, 302)


class RegisterViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_get_register_page_returns_200(self):
        response = self.client.get(reverse('accounts:register'))
        self.assertEqual(response.status_code, 200)

    def test_post_valid_data_creates_user_and_redirects(self):
        response = self.client.post(reverse('accounts:register'), {
            'email': 'new@example.com',
            'first_name': 'New',
            'password': 'Securepass1!',
            'password_confirm': 'Securepass1!',
        })
        self.assertIn(response.status_code, (301, 302))
        self.assertTrue(User.objects.filter(email='new@example.com').exists())

    def test_post_duplicate_email_shows_error(self):
        _make_user(email='existing@example.com')
        response = self.client.post(reverse('accounts:register'), {
            'email': 'existing@example.com',
            'first_name': 'Dup',
            'password': 'Securepass1!',
            'password_confirm': 'Securepass1!',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('email', response.context['errors'])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class DashboardViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user(email='dash@example.com')
        self.client.login(email='dash@example.com', password='testpass')
        prefs, _ = UserPreferences.objects.get_or_create(user=self.user)
        prefs.onboarding_complete = True
        prefs.save()

    def test_dashboard_loads_for_authenticated_user(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_dashboard_context_has_expected_keys(self):
        response = self.client.get(reverse('dashboard'))
        for key in ('total_income', 'total_expenses', 'net', 'recent_transactions'):
            self.assertIn(key, response.context)

    def test_dashboard_requires_login(self):
        anon = Client()
        response = anon.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])


# ---------------------------------------------------------------------------
# Transaction CRUD
# ---------------------------------------------------------------------------

class TransactionViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user(email='txn@example.com')
        self.other = _make_user(email='other@example.com')
        self.client.login(email='txn@example.com', password='testpass')
        self.account = _make_account(self.user)
        self.txn = _make_transaction(self.user, self.account)

    def test_transaction_list_requires_login(self):
        anon = Client()
        response = anon.get(reverse('transaction_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_transaction_list_loads_for_authenticated_user(self):
        response = self.client.get(reverse('transaction_list'))
        self.assertEqual(response.status_code, 200)

    def test_transaction_list_shows_own_transactions_only(self):
        other_account = _make_account(self.other, name='Other Checking')
        _make_transaction(self.other, other_account, amount=Decimal('999.00'))
        response = self.client.get(reverse('transaction_list'))
        page_ids = [t.pk for t in response.context['page_obj'].object_list]
        self.assertIn(self.txn.pk, page_ids)
        other_txns = Transaction.objects.filter(user=self.other)
        for ot in other_txns:
            self.assertNotIn(ot.pk, page_ids)

    def test_transaction_add_get_returns_200(self):
        response = self.client.get(reverse('transaction_add'))
        self.assertEqual(response.status_code, 200)

    def test_transaction_add_requires_login(self):
        anon = Client()
        response = anon.get(reverse('transaction_add'))
        self.assertEqual(response.status_code, 302)

    def test_transaction_add_post_creates_transaction(self):
        count_before = Transaction.objects.filter(user=self.user).count()
        self.client.post(reverse('transaction_add'), {
            'amount': '75.00',
            'transaction_type': 'expense',
            'description': 'Lunch',
            'date': datetime.date.today().isoformat(),
            'account': self.account.pk,
            'force_save': '1',
        })
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), count_before + 1)

    def test_transaction_detail_shows_own_transaction(self):
        response = self.client.get(reverse('transaction_detail', args=[self.txn.pk]))
        self.assertEqual(response.status_code, 200)

    def test_transaction_detail_other_user_returns_404(self):
        other_account = _make_account(self.other, name='Other Bank')
        other_txn = _make_transaction(self.other, other_account)
        response = self.client.get(reverse('transaction_detail', args=[other_txn.pk]))
        self.assertEqual(response.status_code, 404)

    def test_transaction_delete_get_shows_confirmation(self):
        response = self.client.get(reverse('transaction_delete', args=[self.txn.pk]))
        self.assertEqual(response.status_code, 200)

    def test_transaction_delete_post_removes_transaction(self):
        txn_id = self.txn.pk
        self.client.post(reverse('transaction_delete', args=[txn_id]))
        self.assertFalse(Transaction.objects.filter(pk=txn_id).exists())

    def test_transaction_delete_other_user_returns_404(self):
        other_account = _make_account(self.other, name='Other Acct')
        other_txn = _make_transaction(self.other, other_account)
        response = self.client.post(reverse('transaction_delete', args=[other_txn.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Transaction.objects.filter(pk=other_txn.pk).exists())

    def test_transaction_edit_requires_login(self):
        anon = Client()
        response = anon.get(reverse('transaction_edit', args=[self.txn.pk]))
        self.assertEqual(response.status_code, 302)


# ---------------------------------------------------------------------------
# Bucket CRUD
# ---------------------------------------------------------------------------

class BucketViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user(email='bucket@example.com')
        self.other = _make_user(email='other_bucket@example.com')
        self.client.login(email='bucket@example.com', password='testpass')
        self.bucket = _make_bucket(self.user)

    def test_bucket_list_requires_login(self):
        anon = Client()
        response = anon.get(reverse('bucket_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_bucket_list_loads_for_authenticated_user(self):
        response = self.client.get(reverse('bucket_list'))
        self.assertEqual(response.status_code, 200)

    def test_bucket_list_shows_own_buckets_only(self):
        other_bucket = _make_bucket(self.other, name='Other Groceries')
        response = self.client.get(reverse('bucket_list'))
        bucket_ids = [item['bucket'].pk for item in response.context['bucket_data']]
        self.assertIn(self.bucket.pk, bucket_ids)
        self.assertNotIn(other_bucket.pk, bucket_ids)

    def test_bucket_add_get_returns_200(self):
        response = self.client.get(reverse('bucket_add'))
        self.assertEqual(response.status_code, 200)

    def test_bucket_add_requires_login(self):
        anon = Client()
        response = anon.get(reverse('bucket_add'))
        self.assertEqual(response.status_code, 302)

    def test_bucket_add_post_creates_bucket(self):
        count_before = Bucket.objects.filter(user=self.user).count()
        self.client.post(reverse('bucket_add'), {
            'name': 'Utilities',
            'monthly_allocation': '150.00',
            'icon': '💡',
            'color': '#fdcb6e',
            'description': '',
            'alert_threshold': '90',
        })
        self.assertEqual(Bucket.objects.filter(user=self.user).count(), count_before + 1)

    def test_bucket_edit_own_returns_200(self):
        response = self.client.get(reverse('bucket_edit', args=[self.bucket.pk]))
        self.assertEqual(response.status_code, 200)

    def test_bucket_edit_other_user_returns_404(self):
        other_bucket = _make_bucket(self.other, name='Other Rent')
        response = self.client.get(reverse('bucket_edit', args=[other_bucket.pk]))
        self.assertEqual(response.status_code, 404)

    def test_bucket_delete_get_shows_confirmation(self):
        response = self.client.get(reverse('bucket_delete', args=[self.bucket.pk]))
        self.assertEqual(response.status_code, 200)

    def test_bucket_delete_post_removes_bucket(self):
        bucket_id = self.bucket.pk
        self.client.post(reverse('bucket_delete', args=[bucket_id]))
        self.assertFalse(Bucket.objects.filter(pk=bucket_id).exists())

    def test_bucket_delete_other_user_returns_404(self):
        other_bucket = _make_bucket(self.other, name='Other Entertainment')
        response = self.client.post(reverse('bucket_delete', args=[other_bucket.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Bucket.objects.filter(pk=other_bucket.pk).exists())

    def test_bucket_detail_own_returns_200(self):
        response = self.client.get(reverse('bucket_detail', args=[self.bucket.pk]))
        self.assertEqual(response.status_code, 200)

    def test_bucket_detail_other_user_returns_404(self):
        other_bucket = _make_bucket(self.other, name='Other Savings')
        response = self.client.get(reverse('bucket_detail', args=[other_bucket.pk]))
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# Savings Goal CRUD
# ---------------------------------------------------------------------------

class SavingsGoalViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = _make_user(email='savings@example.com')
        self.other = _make_user(email='other_savings@example.com')
        self.client.login(email='savings@example.com', password='testpass')
        self.goal = _make_goal(self.user)

    def test_savings_list_requires_login(self):
        anon = Client()
        response = anon.get(reverse('savings:savings_list'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])

    def test_savings_list_loads_for_authenticated_user(self):
        response = self.client.get(reverse('savings:savings_list'))
        self.assertEqual(response.status_code, 200)

    def test_savings_list_shows_own_goals_only(self):
        other_goal = _make_goal(self.other, name='Other Vacation')
        response = self.client.get(reverse('savings:savings_list'))
        goal_ids = [item['goal'].pk for item in response.context['goal_data']]
        self.assertIn(self.goal.pk, goal_ids)
        self.assertNotIn(other_goal.pk, goal_ids)

    def test_savings_goal_add_get_returns_200(self):
        response = self.client.get(reverse('savings:savings_goal_add'))
        self.assertEqual(response.status_code, 200)

    def test_savings_goal_add_requires_login(self):
        anon = Client()
        response = anon.get(reverse('savings:savings_goal_add'))
        self.assertEqual(response.status_code, 302)

    def test_savings_goal_add_post_creates_goal(self):
        count_before = SavingsGoal.objects.filter(user=self.user).count()
        self.client.post(reverse('savings:savings_goal_add'), {
            'name': 'New Car',
            'target_amount': '20000.00',
            'priority': 'high',
            'goal_type': 'purchase',
            'icon': '🚗',
            'color': '#0984e3',
            'description': '',
        })
        self.assertEqual(SavingsGoal.objects.filter(user=self.user).count(), count_before + 1)

    def test_savings_goal_detail_own_returns_200(self):
        response = self.client.get(reverse('savings:savings_goal_detail', args=[self.goal.pk]))
        self.assertEqual(response.status_code, 200)

    def test_savings_goal_detail_other_user_returns_404(self):
        other_goal = _make_goal(self.other, name='Other Emergency')
        response = self.client.get(reverse('savings:savings_goal_detail', args=[other_goal.pk]))
        self.assertEqual(response.status_code, 404)

    def test_savings_goal_edit_own_returns_200(self):
        response = self.client.get(reverse('savings:savings_goal_edit', args=[self.goal.pk]))
        self.assertEqual(response.status_code, 200)

    def test_savings_goal_edit_other_user_returns_404(self):
        other_goal = _make_goal(self.other, name='Other Retirement')
        response = self.client.get(reverse('savings:savings_goal_edit', args=[other_goal.pk]))
        self.assertEqual(response.status_code, 404)

    def test_savings_goal_edit_post_updates_goal(self):
        self.client.post(reverse('savings:savings_goal_edit', args=[self.goal.pk]), {
            'name': 'Updated Fund',
            'target_amount': '7500.00',
            'priority': 'high',
            'goal_type': 'emergency_fund',
            'icon': '🚨',
            'color': '#d63031',
            'description': '',
        })
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.name, 'Updated Fund')
        self.assertEqual(self.goal.target_amount, Decimal('7500.00'))

    def test_savings_goal_delete_get_shows_confirmation(self):
        response = self.client.get(reverse('savings:savings_goal_delete', args=[self.goal.pk]))
        self.assertEqual(response.status_code, 200)

    def test_savings_goal_delete_post_removes_goal(self):
        goal_id = self.goal.pk
        self.client.post(reverse('savings:savings_goal_delete', args=[goal_id]))
        self.assertFalse(SavingsGoal.objects.filter(pk=goal_id).exists())

    def test_savings_goal_delete_other_user_returns_404(self):
        other_goal = _make_goal(self.other, name='Other House')
        response = self.client.post(reverse('savings:savings_goal_delete', args=[other_goal.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SavingsGoal.objects.filter(pk=other_goal.pk).exists())

    def test_savings_goal_delete_requires_login(self):
        anon = Client()
        response = anon.get(reverse('savings:savings_goal_delete', args=[self.goal.pk]))
        self.assertEqual(response.status_code, 302)
