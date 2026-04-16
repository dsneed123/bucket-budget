import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from banking.models import BankAccount
from .models import SavingsContribution, SavingsGoal
from .views import _calculate_projected_completion

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


class ProjectedCompletionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='proj@example.com',
            password='testpass',
            first_name='Proj',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('10000.00'),
        )
        self.today = datetime.date(2026, 4, 16)

    def _make_goal(self, target=Decimal('1200.00'), current=Decimal('0.00'), deadline=None):
        return SavingsGoal.objects.create(
            user=self.user,
            name='Test Goal',
            target_amount=target,
            current_amount=current,
            deadline=deadline,
        )

    def _add_contribution(self, goal, amount, days_ago):
        contrib_date = self.today - datetime.timedelta(days=days_ago)
        SavingsContribution.objects.create(
            goal=goal,
            amount=amount,
            source_account=self.account,
            date=contrib_date,
        )

    def test_no_recent_contributions_returns_none(self):
        goal = self._make_goal()
        # Contribution older than 91 days
        self._add_contribution(goal, Decimal('300.00'), 95)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNone(result)

    def test_achieved_goal_returns_none(self):
        goal = self._make_goal(target=Decimal('500.00'), current=Decimal('500.00'))
        goal.is_achieved = True
        goal.save()
        self._add_contribution(goal, Decimal('500.00'), 10)
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNone(result)

    def test_projects_future_date(self):
        goal = self._make_goal(target=Decimal('1200.00'), current=Decimal('0.00'))
        # $300/month for last 3 months = $900 total, avg $300/month
        self._add_contribution(goal, Decimal('300.00'), 10)
        self._add_contribution(goal, Decimal('300.00'), 40)
        self._add_contribution(goal, Decimal('300.00'), 70)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNotNone(result)
        self.assertIsInstance(result['projected_date'], datetime.date)
        self.assertGreater(result['projected_date'], self.today)

    def test_meets_deadline_true_when_on_track(self):
        # $400/month avg → $2400 target, $1200 contributed → $1200 remaining → 3 months
        # Set deadline 6 months out
        deadline = self.today + datetime.timedelta(days=180)
        goal = self._make_goal(target=Decimal('2400.00'), current=Decimal('0.00'), deadline=deadline)
        self._add_contribution(goal, Decimal('400.00'), 10)
        self._add_contribution(goal, Decimal('400.00'), 40)
        self._add_contribution(goal, Decimal('400.00'), 70)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNotNone(result)
        self.assertTrue(result['meets_deadline'])

    def test_meets_deadline_false_when_behind(self):
        # $100/month → $1200 remaining → 12 months
        # Deadline only 2 months out
        deadline = self.today + datetime.timedelta(days=60)
        goal = self._make_goal(target=Decimal('1200.00'), current=Decimal('0.00'), deadline=deadline)
        self._add_contribution(goal, Decimal('100.00'), 10)
        self._add_contribution(goal, Decimal('100.00'), 40)
        self._add_contribution(goal, Decimal('100.00'), 70)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNotNone(result)
        self.assertFalse(result['meets_deadline'])

    def test_no_deadline_always_meets(self):
        goal = self._make_goal(target=Decimal('1200.00'), deadline=None)
        self._add_contribution(goal, Decimal('100.00'), 10)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNotNone(result)
        self.assertTrue(result['meets_deadline'])

    def test_monthly_avg_in_result(self):
        goal = self._make_goal(target=Decimal('1200.00'))
        self._add_contribution(goal, Decimal('300.00'), 10)
        self._add_contribution(goal, Decimal('300.00'), 40)
        self._add_contribution(goal, Decimal('300.00'), 70)
        goal.refresh_from_db()
        result = _calculate_projected_completion(goal, self.today)
        self.assertIsNotNone(result)
        self.assertEqual(result['monthly_avg'], Decimal('300'))

    def test_detail_view_includes_projected(self):
        self.client.login(email='proj@example.com', password='testpass')
        # target $1200, contribute $600 → $600 remaining → projection available
        goal = self._make_goal(target=Decimal('1200.00'))
        self._add_contribution(goal, Decimal('200.00'), 10)
        self._add_contribution(goal, Decimal('200.00'), 40)
        self._add_contribution(goal, Decimal('200.00'), 70)
        goal.refresh_from_db()
        url = reverse('savings:savings_goal_detail', kwargs={'goal_id': goal.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('projected', response.context)
        self.assertIsNotNone(response.context['projected'])

    def test_list_view_includes_projected(self):
        self.client.login(email='proj@example.com', password='testpass')
        # target $1200, contribute $600 → $600 remaining → projection available
        goal = self._make_goal(target=Decimal('1200.00'))
        self._add_contribution(goal, Decimal('200.00'), 10)
        self._add_contribution(goal, Decimal('200.00'), 40)
        self._add_contribution(goal, Decimal('200.00'), 70)
        goal.refresh_from_db()
        url = reverse('savings:savings_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        goal_data = response.context['goal_data']
        self.assertEqual(len(goal_data), 1)
        self.assertIn('projected', goal_data[0])
        self.assertIsNotNone(goal_data[0]['projected'])


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
