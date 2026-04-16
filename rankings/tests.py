from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket
from transactions.models import Transaction

User = get_user_model()


class RankingsViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='rankings@example.com',
            password='testpass',
            first_name='Test',
            last_name='User',
        )
        self.client.login(email='rankings@example.com', password='testpass')
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.bucket = Bucket.objects.get(user=self.user, is_uncategorized=True)

    def test_rankings_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('rankings'))
        self.assertRedirects(response, '/login/?next=/rankings/', fetch_redirect_response=False)

    def test_rankings_returns_200(self):
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.status_code, 200)

    def test_rankings_no_transactions_shows_none_score(self):
        response = self.client.get(reverse('rankings'))
        self.assertIsNone(response.context['current_score'])

    def test_rankings_score_from_transactions(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='Test',
            date=today,
            necessity_score=8,
        )
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('30.00'),
            transaction_type='expense',
            description='Test 2',
            date=today,
            necessity_score=6,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['current_score'], Decimal('7.0'))
        self.assertEqual(response.context['current_count'], 2)
        self.assertEqual(response.context['current_color'], 'green')

    def test_rankings_ignores_transactions_without_score(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('50.00'),
            transaction_type='expense',
            description='No score',
            date=today,
            necessity_score=None,
        )
        response = self.client.get(reverse('rankings'))
        self.assertIsNone(response.context['current_score'])

    def test_rankings_ignores_income_transactions(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('1000.00'),
            transaction_type='income',
            description='Salary',
            date=today,
            necessity_score=9,
        )
        response = self.client.get(reverse('rankings'))
        self.assertIsNone(response.context['current_score'])

    def test_score_color_green(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='High necessity',
            date=today,
            necessity_score=9,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['current_color'], 'green')

    def test_score_color_gold(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='Medium necessity',
            date=today,
            necessity_score=5,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['current_color'], 'gold')

    def test_score_color_red(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            bucket=self.bucket,
            amount=Decimal('20.00'),
            transaction_type='expense',
            description='Low necessity',
            date=today,
            necessity_score=2,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['current_color'], 'red')

    def test_rankings_isolates_users(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        other_bucket = Bucket.objects.get(user=other_user, is_uncategorized=True)
        today = date.today()
        Transaction.objects.create(
            user=other_user,
            account=other_account,
            bucket=other_bucket,
            amount=Decimal('100.00'),
            transaction_type='expense',
            description='Other user',
            date=today,
            necessity_score=9,
        )
        response = self.client.get(reverse('rankings'))
        self.assertIsNone(response.context['current_score'])
