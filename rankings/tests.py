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

    def test_impulse_purchases_returned_for_score_1_to_3(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('25.00'), transaction_type='expense',
            description='Impulse buy', vendor='Store', date=today, necessity_score=2,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('10.00'), transaction_type='expense',
            description='High necessity', vendor='Grocery', date=today, necessity_score=8,
        )
        response = self.client.get(reverse('rankings'))
        impulse = response.context['impulse_purchases']
        self.assertEqual(len(impulse), 1)
        self.assertEqual(impulse[0]['description'], 'Impulse buy')
        self.assertEqual(impulse[0]['necessity_score'], 2)

    def test_impulse_total_sums_only_score_1_to_3(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('15.00'), transaction_type='expense',
            description='Want A', date=today, necessity_score=1,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('20.00'), transaction_type='expense',
            description='Want B', date=today, necessity_score=3,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('50.00'), transaction_type='expense',
            description='Need', date=today, necessity_score=9,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['impulse_total'], Decimal('35.00'))

    def test_impulse_purchases_capped_at_10(self):
        today = date.today()
        for i in range(15):
            Transaction.objects.create(
                user=self.user, account=self.account, bucket=self.bucket,
                amount=Decimal('5.00'), transaction_type='expense',
                description=f'Impulse {i}', date=today, necessity_score=2,
            )
        response = self.client.get(reverse('rankings'))
        self.assertLessEqual(len(response.context['impulse_purchases']), 10)

    def test_impulse_purchases_empty_when_none(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('40.00'), transaction_type='expense',
            description='Essential', date=today, necessity_score=7,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(len(response.context['impulse_purchases']), 0)
        self.assertEqual(response.context['impulse_total'], Decimal('0'))

    def test_essential_purchases_returned_for_score_8_to_10(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('60.00'), transaction_type='expense',
            description='Rent', vendor='Landlord', date=today, necessity_score=9,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('15.00'), transaction_type='expense',
            description='Impulse buy', vendor='Store', date=today, necessity_score=2,
        )
        response = self.client.get(reverse('rankings'))
        essential = response.context['essential_purchases']
        self.assertEqual(len(essential), 1)
        self.assertEqual(essential[0]['description'], 'Rent')
        self.assertEqual(essential[0]['necessity_score'], 9)

    def test_essential_total_sums_only_score_8_to_10(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('40.00'), transaction_type='expense',
            description='Groceries', date=today, necessity_score=8,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('80.00'), transaction_type='expense',
            description='Utilities', date=today, necessity_score=10,
        )
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('25.00'), transaction_type='expense',
            description='Want item', date=today, necessity_score=2,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(response.context['essential_total'], Decimal('120.00'))

    def test_essential_purchases_capped_at_10(self):
        today = date.today()
        for i in range(15):
            Transaction.objects.create(
                user=self.user, account=self.account, bucket=self.bucket,
                amount=Decimal('10.00'), transaction_type='expense',
                description=f'Essential {i}', date=today, necessity_score=9,
            )
        response = self.client.get(reverse('rankings'))
        self.assertLessEqual(len(response.context['essential_purchases']), 10)

    def test_essential_purchases_empty_when_none(self):
        today = date.today()
        Transaction.objects.create(
            user=self.user, account=self.account, bucket=self.bucket,
            amount=Decimal('20.00'), transaction_type='expense',
            description='Impulse', date=today, necessity_score=2,
        )
        response = self.client.get(reverse('rankings'))
        self.assertEqual(len(response.context['essential_purchases']), 0)
        self.assertEqual(response.context['essential_total'], Decimal('0'))

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
