from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from banking.models import BankAccount

from .models import AutoSaveRule, SavingsContribution, SavingsGoal, SavingsMilestone

_MILESTONE_META = {
    25:  {'icon': '🌱', 'label': '25%'},
    50:  {'icon': '⚡', 'label': '50%'},
    75:  {'icon': '🔥', 'label': '75%'},
    100: {'icon': '🏆', 'label': '100%'},
}


def _get_milestone_data(goal):
    """Return a list of all milestone tiers with achieved status and reached_at."""
    achieved = {m.percentage: m.reached_at for m in goal.milestones.all()}
    return [
        {
            'percentage': pct,
            'icon': meta['icon'],
            'label': meta['label'],
            'achieved': pct in achieved,
            'reached_at': achieved.get(pct),
        }
        for pct, meta in _MILESTONE_META.items()
    ]


def _get_monthly_contributions(goal, today):
    """Return contribution totals for the last 6 months as chart data (oldest first)."""
    months = []
    for i in range(5, -1, -1):
        offset = today.month - 1 - i
        month_num = (offset % 12) + 1
        year_num = today.year + (offset // 12)
        total = goal.contributions.filter(
            date__year=year_num,
            date__month=month_num,
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        months.append({
            'label': date(year_num, month_num, 1).strftime('%b'),
            'total': total,
        })
    max_total = max((m['total'] for m in months), default=Decimal('0'))
    for m in months:
        m['bar_height'] = int(float(m['total'] / max_total) * 100) if max_total > 0 else 0
    return months


def _calculate_projected_completion(goal, today):
    """Return projected completion info based on avg monthly contributions over last 3 months.

    Returns a dict with keys: projected_date (date), meets_deadline (bool), monthly_avg (Decimal).
    Returns None if goal is achieved, already complete, or has no recent contributions.
    """
    if goal.is_achieved:
        return None

    remaining = goal.target_amount - goal.current_amount
    if remaining <= Decimal('0'):
        return None

    three_months_ago = today - timedelta(days=91)
    result = goal.contributions.filter(date__gte=three_months_ago).aggregate(total=Sum('amount'))
    total_recent = result['total'] or Decimal('0')

    if total_recent <= 0:
        return None

    monthly_avg = total_recent / Decimal('3')
    months_needed = float(remaining / monthly_avg)
    projected_date = today + timedelta(days=months_needed * 30.44)

    meets_deadline = True
    if goal.deadline:
        meets_deadline = projected_date <= goal.deadline

    return {
        'projected_date': projected_date,
        'meets_deadline': meets_deadline,
        'monthly_avg': monthly_avg,
    }


@login_required
def savings_list(request):
    goals = SavingsGoal.objects.filter(user=request.user).order_by('is_achieved', '-priority', 'deadline', 'name')

    today = date.today()
    goal_data = []
    total_saved = Decimal('0')
    total_target = Decimal('0')

    for goal in goals:
        if goal.target_amount > 0:
            pct = min(int((goal.current_amount / goal.target_amount) * 100), 100)
        else:
            pct = 0

        remaining = goal.target_amount - goal.current_amount

        days_left = None
        is_overdue = False
        if goal.deadline and not goal.is_achieved:
            delta = (goal.deadline - today).days
            if delta < 0:
                is_overdue = True
            else:
                days_left = delta

        total_saved += goal.current_amount
        total_target += goal.target_amount

        projected = _calculate_projected_completion(goal, today)

        goal_data.append({
            'goal': goal,
            'pct': pct,
            'remaining': remaining,
            'days_left': days_left,
            'is_overdue': is_overdue,
            'projected': projected,
        })

    overall_pct = int((total_saved / total_target) * 100) if total_target > 0 else 0
    achieved_count = sum(1 for g in goal_data if g['goal'].is_achieved)

    return render(request, 'savings/savings_list.html', {
        'goal_data': goal_data,
        'total_saved': total_saved,
        'total_target': total_target,
        'total_remaining': total_target - total_saved,
        'overall_pct': overall_pct,
        'achieved_count': achieved_count,
    })


@login_required
def savings_goal_add(request):
    errors = {}
    form_data = {
        'color': '#00d4aa',
        'icon': '🎯',
        'priority': 'medium',
    }

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        target_amount = request.POST.get('target_amount', '').strip()
        deadline = request.POST.get('deadline', '').strip()
        priority = request.POST.get('priority', 'medium').strip()
        color = request.POST.get('color', '#00d4aa').strip()
        icon = request.POST.get('icon', '🎯').strip()

        form_data = {
            'name': name,
            'description': description,
            'target_amount': target_amount,
            'deadline': deadline,
            'priority': priority,
            'color': color,
            'icon': icon,
        }

        if not name:
            errors['name'] = 'Goal name is required.'

        target_amount_val = None
        if not target_amount:
            errors['target_amount'] = 'Target amount is required.'
        else:
            try:
                target_amount_val = Decimal(target_amount)
                if target_amount_val <= 0:
                    errors['target_amount'] = 'Target amount must be greater than zero.'
            except Exception:
                errors['target_amount'] = 'Please enter a valid number.'

        deadline_val = None
        if deadline:
            try:
                deadline_val = datetime.strptime(deadline, '%Y-%m-%d').date()
            except ValueError:
                errors['deadline'] = 'Please enter a valid date.'

        if priority not in ('low', 'medium', 'high', 'critical'):
            priority = 'medium'

        if not errors:
            SavingsGoal.objects.create(
                user=request.user,
                name=name,
                description=description,
                target_amount=target_amount_val,
                deadline=deadline_val,
                priority=priority,
                color=color or '#00d4aa',
                icon=icon or '🎯',
            )
            return redirect('savings:savings_list')

    return render(request, 'savings/savings_goal_add.html', {
        'errors': errors,
        'form_data': form_data,
    })


@login_required
def savings_goal_detail(request, goal_id):
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')

    errors = {}
    contribution_form = {
        'date': date.today().strftime('%Y-%m-%d'),
    }

    if request.method == 'POST':
        amount_raw = request.POST.get('amount', '').strip()
        account_id = request.POST.get('source_account', '').strip()
        date_raw = request.POST.get('date', '').strip()
        note = request.POST.get('note', '').strip()

        contribution_form = {
            'amount': amount_raw,
            'source_account': account_id,
            'date': date_raw,
            'note': note,
        }

        amount_val = None
        if not amount_raw:
            errors['amount'] = 'Amount is required.'
        else:
            try:
                amount_val = Decimal(amount_raw)
                if amount_val <= 0:
                    errors['amount'] = 'Amount must be greater than zero.'
            except InvalidOperation:
                errors['amount'] = 'Please enter a valid number.'

        account_obj = None
        if not account_id:
            errors['source_account'] = 'Please select an account.'
        else:
            try:
                account_obj = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                errors['source_account'] = 'Invalid account.'

        date_val = None
        if not date_raw:
            errors['date'] = 'Date is required.'
        else:
            try:
                date_val = datetime.strptime(date_raw, '%Y-%m-%d').date()
            except ValueError:
                errors['date'] = 'Please enter a valid date.'

        if not errors:
            SavingsContribution.objects.create(
                goal=goal,
                amount=amount_val,
                source_account=account_obj,
                date=date_val,
                note=note,
            )
            return redirect('savings:savings_goal_detail', goal_id=goal.pk)

    # Refresh goal after any contribution changes
    goal.refresh_from_db()

    today = date.today()
    pct = min(int((goal.current_amount / goal.target_amount) * 100), 100) if goal.target_amount > 0 else 0
    remaining = max(goal.target_amount - goal.current_amount, Decimal('0'))

    days_left = None
    is_overdue = False
    if goal.deadline and not goal.is_achieved:
        delta = (goal.deadline - today).days
        if delta < 0:
            is_overdue = True
        else:
            days_left = delta

    contributions = goal.contributions.select_related('source_account').order_by('-date', '-created_at')
    projected = _calculate_projected_completion(goal, today)
    monthly_contributions = _get_monthly_contributions(goal, today)

    return render(request, 'savings/savings_goal_detail.html', {
        'goal': goal,
        'pct': pct,
        'remaining': remaining,
        'days_left': days_left,
        'is_overdue': is_overdue,
        'contributions': contributions,
        'accounts': accounts,
        'errors': errors,
        'contribution_form': contribution_form,
        'projected': projected,
        'monthly_contributions': monthly_contributions,
        'milestones': _get_milestone_data(goal),
    })


@login_required
def savings_goal_edit(request, goal_id):
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)
    errors = {}
    success = False

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        target_amount = request.POST.get('target_amount', '').strip()
        deadline = request.POST.get('deadline', '').strip()
        priority = request.POST.get('priority', 'medium').strip()
        color = request.POST.get('color', '#00d4aa').strip()
        icon = request.POST.get('icon', '🎯').strip()

        if not name:
            errors['name'] = 'Goal name is required.'

        target_amount_val = goal.target_amount
        if not target_amount:
            errors['target_amount'] = 'Target amount is required.'
        else:
            try:
                target_amount_val = Decimal(target_amount)
                if target_amount_val <= 0:
                    errors['target_amount'] = 'Target amount must be greater than zero.'
            except Exception:
                errors['target_amount'] = 'Please enter a valid number.'

        deadline_val = goal.deadline
        if deadline:
            try:
                deadline_val = datetime.strptime(deadline, '%Y-%m-%d').date()
            except ValueError:
                errors['deadline'] = 'Please enter a valid date.'
        else:
            deadline_val = None

        if priority not in ('low', 'medium', 'high', 'critical'):
            priority = 'medium'

        if not errors:
            goal.name = name
            goal.description = description
            goal.target_amount = target_amount_val
            goal.deadline = deadline_val
            goal.priority = priority
            goal.color = color or '#00d4aa'
            goal.icon = icon or '🎯'
            goal.save()
            success = True

        return render(request, 'savings/savings_goal_edit.html', {
            'goal': goal,
            'errors': errors,
            'success': success,
            'form_data': {
                'name': name,
                'description': description,
                'target_amount': target_amount,
                'deadline': deadline,
                'priority': priority,
                'color': color,
                'icon': icon,
            },
        })

    return render(request, 'savings/savings_goal_edit.html', {
        'goal': goal,
        'errors': errors,
        'success': success,
        'form_data': {
            'name': goal.name,
            'description': goal.description,
            'target_amount': goal.target_amount,
            'deadline': goal.deadline.strftime('%Y-%m-%d') if goal.deadline else '',
            'priority': goal.priority,
            'color': goal.color,
            'icon': goal.icon,
        },
    })


@login_required
def savings_goal_delete(request, goal_id):
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)
    contribution_count = goal.contributions.count()

    if request.method == 'POST':
        goal.delete()
        return redirect('savings:savings_list')

    return render(request, 'savings/savings_goal_delete.html', {
        'goal': goal,
        'contribution_count': contribution_count,
    })


@login_required
@require_POST
def savings_goal_contribute(request, goal_id):
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)
    accounts = BankAccount.objects.filter(user=request.user, is_active=True)

    amount_raw = request.POST.get('amount', '').strip()
    account_id = request.POST.get('source_account', '').strip()
    note = request.POST.get('note', '').strip()

    errors = {}

    amount_val = None
    if not amount_raw:
        errors['amount'] = 'Amount is required.'
    else:
        try:
            amount_val = Decimal(amount_raw)
            if amount_val <= 0:
                errors['amount'] = 'Amount must be greater than zero.'
        except InvalidOperation:
            errors['amount'] = 'Please enter a valid number.'

    account_obj = None
    if not account_id:
        errors['source_account'] = 'Please select an account.'
    else:
        try:
            account_obj = accounts.get(pk=account_id)
        except BankAccount.DoesNotExist:
            errors['source_account'] = 'Invalid account.'

    if errors:
        # Re-render detail view with errors
        goal.refresh_from_db()
        today = date.today()
        pct = min(int((goal.current_amount / goal.target_amount) * 100), 100) if goal.target_amount > 0 else 0
        remaining = max(goal.target_amount - goal.current_amount, Decimal('0'))

        days_left = None
        is_overdue = False
        if goal.deadline and not goal.is_achieved:
            delta = (goal.deadline - today).days
            if delta < 0:
                is_overdue = True
            else:
                days_left = delta

        contributions = goal.contributions.select_related('source_account').order_by('-date', '-created_at')
        all_accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
        projected = _calculate_projected_completion(goal, today)
        monthly_contributions = _get_monthly_contributions(goal, today)

        return render(request, 'savings/savings_goal_detail.html', {
            'goal': goal,
            'pct': pct,
            'remaining': remaining,
            'days_left': days_left,
            'is_overdue': is_overdue,
            'contributions': contributions,
            'accounts': all_accounts,
            'errors': errors,
            'contribution_form': {
                'amount': amount_raw,
                'source_account': account_id,
                'note': note,
                'date': today.strftime('%Y-%m-%d'),
            },
            'projected': projected,
            'monthly_contributions': monthly_contributions,
            'milestones': _get_milestone_data(goal),
        })

    SavingsContribution.objects.create(
        goal=goal,
        amount=amount_val,
        source_account=account_obj,
        date=date.today(),
        note=note,
    )

    goal.refresh_from_db()
    if goal.current_amount >= goal.target_amount and not goal.is_achieved:
        goal.is_achieved = True
        goal.save()
        messages.success(request, f'Congratulations! You\'ve reached your goal "{goal.name}"!')
    else:
        messages.success(request, f'Contribution of ${amount_val:,.2f} added successfully.')

    return redirect('savings:savings_goal_detail', goal_id=goal.pk)


@login_required
def auto_save_rules(request):
    rules = AutoSaveRule.objects.filter(user=request.user).select_related('goal', 'source_account').order_by('goal__name', 'frequency')
    goals = SavingsGoal.objects.filter(user=request.user, is_achieved=False).order_by('name')
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')

    errors = {}
    form_data = {
        'frequency': 'monthly',
        'next_run': date.today().strftime('%Y-%m-%d'),
    }

    if request.method == 'POST':
        amount_raw = request.POST.get('amount', '').strip()
        goal_id = request.POST.get('goal', '').strip()
        frequency = request.POST.get('frequency', '').strip()
        account_id = request.POST.get('source_account', '').strip()
        next_run_raw = request.POST.get('next_run', '').strip()

        form_data = {
            'amount': amount_raw,
            'goal': goal_id,
            'frequency': frequency,
            'source_account': account_id,
            'next_run': next_run_raw,
        }

        amount_val = None
        if not amount_raw:
            errors['amount'] = 'Amount is required.'
        else:
            try:
                amount_val = Decimal(amount_raw)
                if amount_val <= 0:
                    errors['amount'] = 'Amount must be greater than zero.'
            except InvalidOperation:
                errors['amount'] = 'Please enter a valid number.'

        goal_obj = None
        if not goal_id:
            errors['goal'] = 'Please select a goal.'
        else:
            try:
                goal_obj = goals.get(pk=goal_id)
            except SavingsGoal.DoesNotExist:
                errors['goal'] = 'Invalid goal.'

        if frequency not in ('weekly', 'biweekly', 'monthly'):
            errors['frequency'] = 'Please select a valid frequency.'

        account_obj = None
        if not account_id:
            errors['source_account'] = 'Please select an account.'
        else:
            try:
                account_obj = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                errors['source_account'] = 'Invalid account.'

        next_run_val = None
        if not next_run_raw:
            errors['next_run'] = 'First run date is required.'
        else:
            try:
                next_run_val = datetime.strptime(next_run_raw, '%Y-%m-%d').date()
            except ValueError:
                errors['next_run'] = 'Please enter a valid date.'

        if not errors:
            AutoSaveRule.objects.create(
                user=request.user,
                goal=goal_obj,
                amount=amount_val,
                frequency=frequency,
                source_account=account_obj,
                next_run=next_run_val,
            )
            return redirect('savings:auto_save_rules')

    return render(request, 'savings/auto_save_rules.html', {
        'rules': rules,
        'goals': goals,
        'accounts': accounts,
        'errors': errors,
        'form_data': form_data,
    })


@login_required
@require_POST
def auto_save_rule_toggle(request, rule_id):
    rule = get_object_or_404(AutoSaveRule, pk=rule_id, user=request.user)
    rule.is_active = not rule.is_active
    rule.save()
    return redirect('savings:auto_save_rules')


@login_required
def auto_save_rule_delete(request, rule_id):
    rule = get_object_or_404(AutoSaveRule, pk=rule_id, user=request.user)

    if request.method == 'POST':
        rule.delete()
        return redirect('savings:auto_save_rules')

    return render(request, 'savings/auto_save_rule_delete.html', {'rule': rule})
