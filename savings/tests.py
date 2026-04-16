import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from banking.models import BankAccount
from .models import SavingsContribution, SavingsGoal

User = get_user_model()


class SavingsContributionModelTest(TestCase):
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
            balance=Decimal('2000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('0.00'),
        )

    def test_contribution_deducts_from_account(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1800.00'))

    def test_contribution_adds_to_goal(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('300.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('300.00'))

    def test_contribution_creates_balance_history(self):
        from banking.models import BalanceHistory
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        history = BalanceHistory.objects.get(account=self.account)
        self.assertEqual(history.change_reason, 'savings_contribution')
        self.assertEqual(history.reference_id, str(contribution.pk))
        self.assertEqual(history.change_amount, Decimal('-100.00'))

    def test_delete_reverses_account_balance(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('500.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1500.00'))

        contribution.delete()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('2000.00'))

    def test_delete_reverses_goal_amount(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('400.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('400.00'))

        contribution.delete()
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('0.00'))

    def test_update_adjusts_account_balance(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1800.00'))

        contribution.amount = Decimal('300.00')
        contribution.save()
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1700.00'))

    def test_update_adjusts_goal_amount(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('200.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('200.00'))

        contribution.amount = Decimal('350.00')
        contribution.save()
        self.goal.refresh_from_db()
        self.assertEqual(self.goal.current_amount, Decimal('350.00'))

    def test_str(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date(2026, 4, 16),
        )
        self.assertEqual(str(contribution), 'Vacation +100.00 on 2026-04-16')

    def test_note_optional(self):
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('50.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.assertEqual(contribution.note, '')

    def test_multiple_contributions_accumulate(self):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('100.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('150.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.account.refresh_from_db()
        self.goal.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1750.00'))
        self.assertEqual(self.goal.current_amount, Decimal('250.00'))


class SavingsGoalContributeViewTest(TestCase):
    def setUp(self):
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
            balance=Decimal('2000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('0.00'),
        )
        self.client.login(email='view@example.com', password='testpass')
        self.url = reverse('savings:savings_goal_contribute', kwargs={'goal_id': self.goal.pk})

    def test_contribute_creates_contribution_and_redirects(self):
        response = self.client.post(self.url, {
            'amount': '200.00',
            'source_account': self.account.pk,
            'note': 'First deposit',
        })
        self.assertRedirects(response, reverse('savings:savings_goal_detail', kwargs={'goal_id': self.goal.pk}))
        self.assertEqual(SavingsContribution.objects.count(), 1)
        contribution = SavingsContribution.objects.get()
        self.assertEqual(contribution.amount, Decimal('200.00'))
        self.assertEqual(contribution.note, 'First deposit')

    def test_contribute_deducts_from_account(self):
        self.client.post(self.url, {
            'amount': '300.00',
            'source_account': self.account.pk,
        })
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('1700.00'))

    def test_contribute_sets_achieved_when_target_reached(self):
        self.client.post(self.url, {
            'amount': '1000.00',
            'source_account': self.account.pk,
        })
        self.goal.refresh_from_db()
        self.assertTrue(self.goal.is_achieved)

    def test_contribute_no_achieved_when_target_not_reached(self):
        self.client.post(self.url, {
            'amount': '500.00',
            'source_account': self.account.pk,
        })
        self.goal.refresh_from_db()
        self.assertFalse(self.goal.is_achieved)

    def test_contribute_success_message(self):
        response = self.client.post(self.url, {
            'amount': '100.00',
            'source_account': self.account.pk,
        }, follow=True)
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('100.00', str(messages[0]))

    def test_contribute_achieved_message(self):
        response = self.client.post(self.url, {
            'amount': '1000.00',
            'source_account': self.account.pk,
        }, follow=True)
        messages = list(response.context['messages'])
        self.assertEqual(len(messages), 1)
        self.assertIn('Vacation', str(messages[0]))

    def test_contribute_missing_amount_returns_errors(self):
        response = self.client.post(self.url, {
            'source_account': self.account.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('amount', response.context['errors'])
        self.assertEqual(SavingsContribution.objects.count(), 0)

    def test_contribute_invalid_amount_returns_errors(self):
        response = self.client.post(self.url, {
            'amount': '-50',
            'source_account': self.account.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('amount', response.context['errors'])

    def test_contribute_missing_account_returns_errors(self):
        response = self.client.post(self.url, {
            'amount': '100.00',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('source_account', response.context['errors'])

    def test_contribute_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_contribute_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {
            'amount': '100.00',
            'source_account': self.account.pk,
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_contribute_other_user_goal_returns_404(self):
        other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_goal = SavingsGoal.objects.create(
            user=other_user,
            name='Other Goal',
            target_amount=Decimal('500.00'),
        )
        url = reverse('savings:savings_goal_contribute', kwargs={'goal_id': other_goal.pk})
        response = self.client.post(url, {
            'amount': '100.00',
            'source_account': self.account.pk,
        })
        self.assertEqual(response.status_code, 404)
