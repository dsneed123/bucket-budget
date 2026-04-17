import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from banking.models import BankAccount
from transactions.models import Transaction
from .models import AutoSaveRule, SavingsContribution, SavingsGoal, SavingsMilestone
from .views import _calculate_projected_completion, _get_emergency_fund_coverage, _get_milestone_data, _get_monthly_avg_expenses
from .management.commands.process_auto_saves import _advance_next_run

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


class AdvanceNextRunTest(TestCase):
    def test_weekly(self):
        d = datetime.date(2026, 4, 16)
        self.assertEqual(_advance_next_run(d, 'weekly'), datetime.date(2026, 4, 23))

    def test_biweekly(self):
        d = datetime.date(2026, 4, 16)
        self.assertEqual(_advance_next_run(d, 'biweekly'), datetime.date(2026, 4, 30))

    def test_monthly(self):
        d = datetime.date(2026, 4, 16)
        self.assertEqual(_advance_next_run(d, 'monthly'), datetime.date(2026, 5, 16))

    def test_monthly_year_rollover(self):
        d = datetime.date(2026, 12, 15)
        self.assertEqual(_advance_next_run(d, 'monthly'), datetime.date(2027, 1, 15))

    def test_monthly_clamps_short_month(self):
        d = datetime.date(2026, 1, 31)
        self.assertEqual(_advance_next_run(d, 'monthly'), datetime.date(2026, 2, 28))


class AutoSaveRuleViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='auto@example.com',
            password='testpass',
            first_name='Auto',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Car',
            target_amount=Decimal('10000.00'),
            current_amount=Decimal('0.00'),
        )
        self.client.login(email='auto@example.com', password='testpass')
        self.list_url = reverse('savings:auto_save_rules')

    def test_list_view_renders(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)

    def test_create_rule(self):
        response = self.client.post(self.list_url, {
            'amount': '200.00',
            'goal': self.goal.pk,
            'frequency': 'monthly',
            'source_account': self.account.pk,
            'next_run': '2026-05-01',
        })
        self.assertRedirects(response, self.list_url)
        self.assertEqual(AutoSaveRule.objects.count(), 1)
        rule = AutoSaveRule.objects.get()
        self.assertEqual(rule.amount, Decimal('200.00'))
        self.assertEqual(rule.frequency, 'monthly')
        self.assertTrue(rule.is_active)

    def test_create_rule_missing_amount(self):
        response = self.client.post(self.list_url, {
            'goal': self.goal.pk,
            'frequency': 'monthly',
            'source_account': self.account.pk,
            'next_run': '2026-05-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('amount', response.context['errors'])
        self.assertEqual(AutoSaveRule.objects.count(), 0)

    def test_create_rule_invalid_frequency(self):
        response = self.client.post(self.list_url, {
            'amount': '100.00',
            'goal': self.goal.pk,
            'frequency': 'daily',
            'source_account': self.account.pk,
            'next_run': '2026-05-01',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('frequency', response.context['errors'])

    def test_toggle_rule(self):
        rule = AutoSaveRule.objects.create(
            user=self.user,
            goal=self.goal,
            amount=Decimal('100.00'),
            frequency='monthly',
            source_account=self.account,
            next_run=datetime.date(2026, 5, 1),
        )
        toggle_url = reverse('savings:auto_save_rule_toggle', kwargs={'rule_id': rule.pk})
        self.client.post(toggle_url)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)

        self.client.post(toggle_url)
        rule.refresh_from_db()
        self.assertTrue(rule.is_active)

    def test_toggle_requires_post(self):
        rule = AutoSaveRule.objects.create(
            user=self.user,
            goal=self.goal,
            amount=Decimal('100.00'),
            frequency='monthly',
            source_account=self.account,
            next_run=datetime.date(2026, 5, 1),
        )
        toggle_url = reverse('savings:auto_save_rule_toggle', kwargs={'rule_id': rule.pk})
        response = self.client.get(toggle_url)
        self.assertEqual(response.status_code, 405)

    def test_delete_rule(self):
        rule = AutoSaveRule.objects.create(
            user=self.user,
            goal=self.goal,
            amount=Decimal('100.00'),
            frequency='monthly',
            source_account=self.account,
            next_run=datetime.date(2026, 5, 1),
        )
        delete_url = reverse('savings:auto_save_rule_delete', kwargs={'rule_id': rule.pk})
        response = self.client.post(delete_url)
        self.assertRedirects(response, self.list_url)
        self.assertEqual(AutoSaveRule.objects.count(), 0)

    def test_delete_confirm_page(self):
        rule = AutoSaveRule.objects.create(
            user=self.user,
            goal=self.goal,
            amount=Decimal('100.00'),
            frequency='monthly',
            source_account=self.account,
            next_run=datetime.date(2026, 5, 1),
        )
        delete_url = reverse('savings:auto_save_rule_delete', kwargs={'rule_id': rule.pk})
        response = self.client.get(delete_url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('rule', response.context)

    def test_other_user_rule_returns_404(self):
        other_user = User.objects.create_user(
            email='other2@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        other_goal = SavingsGoal.objects.create(
            user=other_user,
            name='Other Goal',
            target_amount=Decimal('500.00'),
        )
        other_account = BankAccount.objects.create(
            user=other_user,
            name='Other Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        rule = AutoSaveRule.objects.create(
            user=other_user,
            goal=other_goal,
            amount=Decimal('50.00'),
            frequency='weekly',
            source_account=other_account,
            next_run=datetime.date(2026, 5, 1),
        )
        toggle_url = reverse('savings:auto_save_rule_toggle', kwargs={'rule_id': rule.pk})
        response = self.client.post(toggle_url)
        self.assertEqual(response.status_code, 404)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)


class ProcessAutoSavesCommandTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='cmd@example.com',
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
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('2000.00'),
            current_amount=Decimal('0.00'),
        )

    def _make_rule(self, next_run, frequency='monthly', is_active=True, amount=Decimal('200.00')):
        return AutoSaveRule.objects.create(
            user=self.user,
            goal=self.goal,
            amount=amount,
            frequency=frequency,
            source_account=self.account,
            next_run=next_run,
            is_active=is_active,
        )

    def test_processes_due_rule(self):
        from django.core.management import call_command
        rule = self._make_rule(next_run=datetime.date(2026, 4, 1))
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        self.assertEqual(SavingsContribution.objects.count(), 1)
        contribution = SavingsContribution.objects.get()
        self.assertEqual(contribution.amount, Decimal('200.00'))
        self.assertEqual(contribution.goal, self.goal)

    def test_advances_next_run_after_processing(self):
        from django.core.management import call_command
        rule = self._make_rule(next_run=datetime.date(2026, 4, 1), frequency='monthly')
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        rule.refresh_from_db()
        self.assertEqual(rule.next_run, datetime.date(2026, 5, 1))

    def test_skips_future_rule(self):
        from django.core.management import call_command
        self._make_rule(next_run=datetime.date(2026, 5, 1))
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        self.assertEqual(SavingsContribution.objects.count(), 0)

    def test_skips_inactive_rule(self):
        from django.core.management import call_command
        self._make_rule(next_run=datetime.date(2026, 4, 1), is_active=False)
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        self.assertEqual(SavingsContribution.objects.count(), 0)

    def test_skips_achieved_goal(self):
        from django.core.management import call_command
        self.goal.is_achieved = True
        self.goal.save()
        self._make_rule(next_run=datetime.date(2026, 4, 1))
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        self.assertEqual(SavingsContribution.objects.count(), 0)

    def test_dry_run_makes_no_changes(self):
        from django.core.management import call_command
        self._make_rule(next_run=datetime.date(2026, 4, 1))
        call_command('process_auto_saves', date='2026-04-16', dry_run=True, verbosity=0)
        self.assertEqual(SavingsContribution.objects.count(), 0)

    def test_marks_goal_achieved_when_target_reached(self):
        from django.core.management import call_command
        self.goal.target_amount = Decimal('200.00')
        self.goal.save()
        self._make_rule(next_run=datetime.date(2026, 4, 1), amount=Decimal('200.00'))
        call_command('process_auto_saves', date='2026-04-16', verbosity=0)
        self.goal.refresh_from_db()
        self.assertTrue(self.goal.is_achieved)


class SavingsMilestoneTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='ms@example.com',
            password='testpass',
            first_name='Mile',
            last_name='Stone',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='New Laptop',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('0.00'),
        )

    def _contribute(self, amount):
        SavingsContribution.objects.create(
            goal=self.goal,
            amount=amount,
            source_account=self.account,
            date=datetime.date.today(),
        )
        self.goal.refresh_from_db()

    def test_no_milestones_below_25_percent(self):
        self._contribute(Decimal('200.00'))  # 20%
        self.assertEqual(SavingsMilestone.objects.filter(goal=self.goal).count(), 0)

    def test_25_percent_milestone_created(self):
        self._contribute(Decimal('250.00'))  # exactly 25%
        self.assertTrue(SavingsMilestone.objects.filter(goal=self.goal, percentage=25).exists())

    def test_50_percent_milestone_created(self):
        self._contribute(Decimal('500.00'))  # exactly 50%
        self.assertTrue(SavingsMilestone.objects.filter(goal=self.goal, percentage=25).exists())
        self.assertTrue(SavingsMilestone.objects.filter(goal=self.goal, percentage=50).exists())
        self.assertFalse(SavingsMilestone.objects.filter(goal=self.goal, percentage=75).exists())

    def test_100_percent_creates_all_milestones(self):
        self._contribute(Decimal('1000.00'))  # 100%
        percentages = set(SavingsMilestone.objects.filter(goal=self.goal).values_list('percentage', flat=True))
        self.assertEqual(percentages, {25, 50, 75, 100})

    def test_milestones_not_duplicated_on_further_contributions(self):
        self._contribute(Decimal('300.00'))  # 30% → only 25% milestone
        self._contribute(Decimal('200.00'))  # 50% → 25%, 50% milestones
        self.assertEqual(SavingsMilestone.objects.filter(goal=self.goal, percentage=25).count(), 1)

    def test_milestone_not_created_for_zero_target(self):
        zero_goal = SavingsGoal.objects.create(
            user=self.user,
            name='Zero Target',
            target_amount=Decimal('0.00'),
        )
        # Saving to SavingsGoal with zero target should not raise or create milestones
        zero_goal.current_amount = Decimal('100.00')
        zero_goal.save()
        self.assertEqual(SavingsMilestone.objects.filter(goal=zero_goal).count(), 0)

    def test_get_milestone_data_returns_all_tiers(self):
        data = _get_milestone_data(self.goal)
        self.assertEqual(len(data), 4)
        percentages = [d['percentage'] for d in data]
        self.assertEqual(percentages, [25, 50, 75, 100])

    def test_get_milestone_data_achieved_flag(self):
        self._contribute(Decimal('500.00'))  # 50%
        data = _get_milestone_data(self.goal)
        achieved = {d['percentage']: d['achieved'] for d in data}
        self.assertTrue(achieved[25])
        self.assertTrue(achieved[50])
        self.assertFalse(achieved[75])
        self.assertFalse(achieved[100])

    def test_get_milestone_data_reached_at_populated(self):
        self._contribute(Decimal('750.00'))  # 75%
        data = _get_milestone_data(self.goal)
        for d in data:
            if d['percentage'] <= 75:
                self.assertIsNotNone(d['reached_at'])
            else:
                self.assertIsNone(d['reached_at'])

    def test_detail_view_includes_milestones(self):
        self.client.login(email='ms@example.com', password='testpass')
        self._contribute(Decimal('500.00'))
        url = reverse('savings:savings_goal_detail', kwargs={'goal_id': self.goal.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('milestones', response.context)
        self.assertEqual(len(response.context['milestones']), 4)

    def test_str(self):
        SavingsMilestone.objects.create(goal=self.goal, percentage=50)
        m = SavingsMilestone.objects.get(goal=self.goal, percentage=50)
        self.assertEqual(str(m), 'New Laptop — 50% milestone')


class SavingsGoalSharingTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='share@example.com',
            password='testpass',
            first_name='Share',
            last_name='User',
        )
        self.other_user = User.objects.create_user(
            email='other@example.com',
            password='testpass',
            first_name='Other',
            last_name='User',
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation Fund',
            target_amount=Decimal('2000.00'),
            current_amount=Decimal('500.00'),
        )

    def test_is_private_default_true(self):
        self.assertTrue(self.goal.is_private)

    def test_share_uuid_is_set(self):
        self.assertIsNotNone(self.goal.share_uuid)

    def test_share_uuid_unique(self):
        other_goal = SavingsGoal.objects.create(
            user=self.user,
            name='Emergency Fund',
            target_amount=Decimal('5000.00'),
        )
        self.assertNotEqual(self.goal.share_uuid, other_goal.share_uuid)

    def test_shared_view_returns_404_when_private(self):
        url = reverse('savings:savings_goal_shared', kwargs={'share_uuid': self.goal.share_uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_shared_view_returns_200_when_public(self):
        self.goal.is_private = False
        self.goal.save()
        url = reverse('savings:savings_goal_shared', kwargs={'share_uuid': self.goal.share_uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_shared_view_accessible_without_login(self):
        self.goal.is_private = False
        self.goal.save()
        url = reverse('savings:savings_goal_shared', kwargs={'share_uuid': self.goal.share_uuid})
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_shared_view_accessible_by_other_user(self):
        self.goal.is_private = False
        self.goal.save()
        self.client.login(email='other@example.com', password='testpass')
        url = reverse('savings:savings_goal_shared', kwargs={'share_uuid': self.goal.share_uuid})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_shared_view_shows_goal_name(self):
        self.goal.is_private = False
        self.goal.save()
        url = reverse('savings:savings_goal_shared', kwargs={'share_uuid': self.goal.share_uuid})
        response = self.client.get(url)
        self.assertContains(response, 'Vacation Fund')

    def test_edit_view_saves_is_private_false(self):
        self.client.login(email='share@example.com', password='testpass')
        url = reverse('savings:savings_goal_edit', kwargs={'goal_id': self.goal.pk})
        response = self.client.post(url, {
            'name': self.goal.name,
            'target_amount': '2000.00',
            'priority': 'medium',
            'color': '#00d4aa',
            'icon': '🎯',
            'is_private': 'false',
        })
        self.goal.refresh_from_db()
        self.assertFalse(self.goal.is_private)

    def test_edit_view_saves_is_private_true(self):
        self.goal.is_private = False
        self.goal.save()
        self.client.login(email='share@example.com', password='testpass')
        url = reverse('savings:savings_goal_edit', kwargs={'goal_id': self.goal.pk})
        self.client.post(url, {
            'name': self.goal.name,
            'target_amount': '2000.00',
            'priority': 'medium',
            'color': '#00d4aa',
            'icon': '🎯',
            'is_private': 'true',
        })
        self.goal.refresh_from_db()
        self.assertTrue(self.goal.is_private)


class SavingsGoalTypeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='type@example.com',
            password='testpass',
            first_name='Type',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('5000.00'),
        )
        self.client.login(email='type@example.com', password='testpass')
        self.today = datetime.date(2026, 4, 16)

    def _make_goal(self, goal_type='general', current=Decimal('0.00')):
        return SavingsGoal.objects.create(
            user=self.user,
            name='Test Goal',
            target_amount=Decimal('1000.00'),
            current_amount=current,
            goal_type=goal_type,
        )

    def _add_expense(self, amount, days_ago=10):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=amount,
            transaction_type='expense',
            description='Test expense',
            date=self.today - datetime.timedelta(days=days_ago),
        )

    def test_default_goal_type_is_general(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='Default Goal',
            target_amount=Decimal('500.00'),
        )
        self.assertEqual(goal.goal_type, 'general')

    def test_can_set_all_goal_types(self):
        expected_types = ['general', 'emergency_fund', 'vacation', 'purchase', 'debt_payoff', 'investment', 'education', 'other']
        for gt in expected_types:
            goal = SavingsGoal.objects.create(
                user=self.user,
                name=f'Goal {gt}',
                target_amount=Decimal('100.00'),
                goal_type=gt,
            )
            self.assertEqual(goal.goal_type, gt)

    def test_add_view_saves_goal_type(self):
        url = reverse('savings:savings_goal_add')
        self.client.post(url, {
            'name': 'Emergency Fund',
            'target_amount': '5000.00',
            'priority': 'high',
            'goal_type': 'emergency_fund',
            'color': '#00d4aa',
            'icon': '🛡️',
        })
        goal = SavingsGoal.objects.get(name='Emergency Fund')
        self.assertEqual(goal.goal_type, 'emergency_fund')

    def test_add_view_invalid_goal_type_falls_back_to_general(self):
        url = reverse('savings:savings_goal_add')
        self.client.post(url, {
            'name': 'Invalid Type Goal',
            'target_amount': '500.00',
            'priority': 'medium',
            'goal_type': 'invalid_type',
            'color': '#00d4aa',
            'icon': '🎯',
        })
        goal = SavingsGoal.objects.get(name='Invalid Type Goal')
        self.assertEqual(goal.goal_type, 'general')

    def test_edit_view_saves_goal_type(self):
        goal = self._make_goal(goal_type='general')
        url = reverse('savings:savings_goal_edit', kwargs={'goal_id': goal.pk})
        self.client.post(url, {
            'name': goal.name,
            'target_amount': '1000.00',
            'priority': 'medium',
            'goal_type': 'vacation',
            'color': '#00d4aa',
            'icon': '🎯',
            'is_private': 'true',
        })
        goal.refresh_from_db()
        self.assertEqual(goal.goal_type, 'vacation')

    def test_get_monthly_avg_expenses_returns_avg(self):
        self._add_expense(Decimal('300.00'), days_ago=10)
        self._add_expense(Decimal('300.00'), days_ago=40)
        self._add_expense(Decimal('300.00'), days_ago=70)
        avg = _get_monthly_avg_expenses(self.user, self.today)
        self.assertIsNotNone(avg)
        self.assertEqual(avg, Decimal('300'))

    def test_get_monthly_avg_expenses_excludes_old_transactions(self):
        self._add_expense(Decimal('500.00'), days_ago=100)  # outside 91-day window
        avg = _get_monthly_avg_expenses(self.user, self.today)
        self.assertIsNone(avg)

    def test_get_monthly_avg_expenses_excludes_income(self):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('3000.00'),
            transaction_type='income',
            description='Salary',
            date=self.today - datetime.timedelta(days=10),
        )
        avg = _get_monthly_avg_expenses(self.user, self.today)
        self.assertIsNone(avg)

    def test_get_emergency_fund_coverage_returns_months(self):
        coverage = _get_emergency_fund_coverage(Decimal('900.00'), Decimal('300.00'))
        self.assertAlmostEqual(coverage, 3.0)

    def test_get_emergency_fund_coverage_none_when_no_avg(self):
        coverage = _get_emergency_fund_coverage(Decimal('500.00'), None)
        self.assertIsNone(coverage)

    def test_detail_view_includes_emergency_coverage_for_emergency_fund(self):
        goal = self._make_goal(goal_type='emergency_fund', current=Decimal('900.00'))
        self._add_expense(Decimal('300.00'), days_ago=10)
        self._add_expense(Decimal('300.00'), days_ago=40)
        self._add_expense(Decimal('300.00'), days_ago=70)
        url = reverse('savings:savings_goal_detail', kwargs={'goal_id': goal.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('emergency_coverage', response.context)
        self.assertIsNotNone(response.context['emergency_coverage'])
        self.assertAlmostEqual(response.context['emergency_coverage'], 3.0)

    def test_detail_view_emergency_coverage_none_for_general_goal(self):
        goal = self._make_goal(goal_type='general', current=Decimal('500.00'))
        self._add_expense(Decimal('300.00'), days_ago=10)
        url = reverse('savings:savings_goal_detail', kwargs={'goal_id': goal.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['emergency_coverage'])

    def test_list_view_includes_emergency_coverage(self):
        goal = self._make_goal(goal_type='emergency_fund', current=Decimal('600.00'))
        self._add_expense(Decimal('300.00'), days_ago=10)
        self._add_expense(Decimal('300.00'), days_ago=40)
        self._add_expense(Decimal('300.00'), days_ago=70)
        url = reverse('savings:savings_list')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        goal_data = response.context['goal_data']
        self.assertEqual(len(goal_data), 1)
        self.assertIn('emergency_coverage', goal_data[0])
        self.assertIsNotNone(goal_data[0]['emergency_coverage'])
        self.assertAlmostEqual(goal_data[0]['emergency_coverage'], 2.0)

    def test_add_view_provides_goal_type_choices(self):
        url = reverse('savings:savings_goal_add')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('goal_type_choices', response.context)
        choice_values = [c[0] for c in response.context['goal_type_choices']]
        self.assertIn('emergency_fund', choice_values)
        self.assertIn('general', choice_values)

    def test_edit_view_provides_goal_type_choices(self):
        goal = self._make_goal()
        url = reverse('savings:savings_goal_edit', kwargs={'goal_id': goal.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('goal_type_choices', response.context)


class SavingsListSortTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='sort@example.com',
            password='testpass',
            first_name='Sort',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('10000.00'),
        )
        self.client.login(email='sort@example.com', password='testpass')
        self.url = reverse('savings:savings_list')

    def _make_goal(self, name, priority='medium', deadline=None, target=Decimal('1000.00'), current=Decimal('0.00')):
        return SavingsGoal.objects.create(
            user=self.user,
            name=name,
            priority=priority,
            deadline=deadline,
            target_amount=target,
            current_amount=current,
        )

    def test_default_sort_is_priority(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['sort'], 'priority')

    def test_invalid_sort_falls_back_to_priority(self):
        response = self.client.get(self.url + '?sort=bogus')
        self.assertEqual(response.context['sort'], 'priority')

    def test_priority_sort_critical_first(self):
        low = self._make_goal('Low Goal', priority='low')
        high = self._make_goal('High Goal', priority='high')
        critical = self._make_goal('Critical Goal', priority='critical')
        medium = self._make_goal('Medium Goal', priority='medium')

        response = self.client.get(self.url + '?sort=priority')
        names = [item['goal'].name for item in response.context['goal_data']]
        self.assertEqual(names.index('Critical Goal') < names.index('High Goal'), True)
        self.assertEqual(names.index('High Goal') < names.index('Medium Goal'), True)
        self.assertEqual(names.index('Medium Goal') < names.index('Low Goal'), True)

    def test_deadline_sort_soonest_first(self):
        far = self._make_goal('Far Goal', deadline=datetime.date(2030, 1, 1))
        near = self._make_goal('Near Goal', deadline=datetime.date(2026, 6, 1))
        no_dl = self._make_goal('No Deadline Goal')

        response = self.client.get(self.url + '?sort=deadline')
        names = [item['goal'].name for item in response.context['goal_data']]
        self.assertLess(names.index('Near Goal'), names.index('Far Goal'))
        # Goals with no deadline appear after those with deadlines
        self.assertLess(names.index('Far Goal'), names.index('No Deadline Goal'))

    def test_progress_sort_lowest_first(self):
        high_progress = self._make_goal('High Progress', target=Decimal('1000.00'), current=Decimal('800.00'))
        low_progress = self._make_goal('Low Progress', target=Decimal('1000.00'), current=Decimal('100.00'))
        mid_progress = self._make_goal('Mid Progress', target=Decimal('1000.00'), current=Decimal('500.00'))

        response = self.client.get(self.url + '?sort=progress')
        names = [item['goal'].name for item in response.context['goal_data']]
        self.assertLess(names.index('Low Progress'), names.index('Mid Progress'))
        self.assertLess(names.index('Mid Progress'), names.index('High Progress'))

    def test_sort_context_passed_to_template(self):
        for sort_val in ('priority', 'deadline', 'progress'):
            response = self.client.get(self.url + f'?sort={sort_val}')
            self.assertEqual(response.context['sort'], sort_val)


class SavingsGoalModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='goalmodel@example.com',
            password='testpass',
            first_name='Goal',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Savings',
            account_type='savings',
            balance=Decimal('5000.00'),
        )

    def test_create_savings_goal(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='Emergency Fund',
            target_amount=Decimal('10000.00'),
        )
        self.assertEqual(goal.name, 'Emergency Fund')
        self.assertEqual(goal.target_amount, Decimal('10000.00'))
        self.assertEqual(goal.current_amount, Decimal('0'))

    def test_is_achieved_default_false(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('2000.00'),
        )
        self.assertFalse(goal.is_achieved)

    def test_is_private_default_true(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='Private Goal',
            target_amount=Decimal('500.00'),
        )
        self.assertTrue(goal.is_private)

    def test_contribution_updates_current_amount(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='Car Fund',
            target_amount=Decimal('5000.00'),
        )
        SavingsContribution.objects.create(
            goal=goal,
            amount=Decimal('500.00'),
            source_account=self.account,
            date=datetime.date.today(),
        )
        goal.refresh_from_db()
        self.assertEqual(goal.current_amount, Decimal('500.00'))

    def test_multiple_contributions_accumulate(self):
        goal = SavingsGoal.objects.create(
            user=self.user,
            name='House Down Payment',
            target_amount=Decimal('20000.00'),
        )
        for _ in range(3):
            SavingsContribution.objects.create(
                goal=goal,
                amount=Decimal('1000.00'),
                source_account=self.account,
                date=datetime.date.today(),
            )
        goal.refresh_from_db()
        self.assertEqual(goal.current_amount, Decimal('3000.00'))

    def test_goal_types(self):
        for goal_type in ('general', 'emergency_fund', 'vacation', 'purchase', 'debt_payoff'):
            goal = SavingsGoal.objects.create(
                user=self.user,
                name=f'{goal_type} goal',
                target_amount=Decimal('1000.00'),
                goal_type=goal_type,
            )
            self.assertEqual(goal.goal_type, goal_type)
