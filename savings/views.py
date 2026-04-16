import csv
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Case, F, IntegerField, Sum, Value, When
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from banking.models import BankAccount
from transactions.models import Transaction

from .models import AutoSaveRule, SavingsContribution, SavingsGoal, SavingsMilestone

_VALID_GOAL_TYPES = {c[0] for c in SavingsGoal.GOAL_TYPE_CHOICES}

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


def _get_monthly_avg_expenses(user, today):
    """Return average monthly expenses over the last 3 months, or None if no data."""
    three_months_ago = today - timedelta(days=91)
    result = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__gte=three_months_ago,
    ).aggregate(total=Sum('amount'))
    total = result['total'] or Decimal('0')
    if total <= 0:
        return None
    return total / Decimal('3')


def _get_emergency_fund_coverage(current_amount, monthly_avg_expenses):
    """Return months of expenses covered as a float, or None if no expense data."""
    if not monthly_avg_expenses or monthly_avg_expenses <= 0:
        return None
    return float(current_amount / monthly_avg_expenses)


_PRIORITY_RANK = Case(
    When(priority='critical', then=Value(0)),
    When(priority='high', then=Value(1)),
    When(priority='medium', then=Value(2)),
    When(priority='low', then=Value(3)),
    default=Value(4),
    output_field=IntegerField(),
)

_VALID_SORTS = {'priority', 'deadline', 'progress'}


@login_required
def savings_list(request):
    sort = request.GET.get('sort', 'priority')
    if sort not in _VALID_SORTS:
        sort = 'priority'

    qs = SavingsGoal.objects.filter(user=request.user).annotate(priority_rank=_PRIORITY_RANK)

    if sort == 'deadline':
        goals = qs.order_by('is_achieved', F('deadline').asc(nulls_last=True), 'priority_rank', 'name')
    else:
        # priority sort (also used as base for progress, re-sorted in Python after pct is computed)
        goals = qs.order_by('is_achieved', 'priority_rank', F('deadline').asc(nulls_last=True), 'name')

    today = date.today()
    goal_data = []
    total_saved = Decimal('0')
    total_target = Decimal('0')

    monthly_avg_expenses = None
    if any(g.goal_type == 'emergency_fund' for g in goals):
        monthly_avg_expenses = _get_monthly_avg_expenses(request.user, today)

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

        emergency_coverage = None
        if goal.goal_type == 'emergency_fund':
            emergency_coverage = _get_emergency_fund_coverage(goal.current_amount, monthly_avg_expenses)

        goal_data.append({
            'goal': goal,
            'pct': pct,
            'remaining': remaining,
            'days_left': days_left,
            'is_overdue': is_overdue,
            'projected': projected,
            'emergency_coverage': emergency_coverage,
        })

    if sort == 'progress':
        goal_data.sort(key=lambda x: (x['goal'].is_achieved, x['pct']))

    overall_pct = int((total_saved / total_target) * 100) if total_target > 0 else 0
    achieved_count = sum(1 for g in goal_data if g['goal'].is_achieved)

    return render(request, 'savings/savings_list.html', {
        'goal_data': goal_data,
        'total_saved': total_saved,
        'total_target': total_target,
        'total_remaining': total_target - total_saved,
        'overall_pct': overall_pct,
        'achieved_count': achieved_count,
        'sort': sort,
    })


@login_required
def savings_goal_add(request):
    errors = {}
    form_data = {
        'color': '#00d4aa',
        'icon': '🎯',
        'priority': 'medium',
        'goal_type': 'general',
    }

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        target_amount = request.POST.get('target_amount', '').strip()
        deadline = request.POST.get('deadline', '').strip()
        priority = request.POST.get('priority', 'medium').strip()
        goal_type = request.POST.get('goal_type', 'general').strip()
        color = request.POST.get('color', '#00d4aa').strip()
        icon = request.POST.get('icon', '🎯').strip()

        form_data = {
            'name': name,
            'description': description,
            'target_amount': target_amount,
            'deadline': deadline,
            'priority': priority,
            'goal_type': goal_type,
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

        if goal_type not in _VALID_GOAL_TYPES:
            goal_type = 'general'

        if not errors:
            SavingsGoal.objects.create(
                user=request.user,
                name=name,
                description=description,
                target_amount=target_amount_val,
                deadline=deadline_val,
                priority=priority,
                goal_type=goal_type,
                color=color or '#00d4aa',
                icon=icon or '🎯',
            )
            return redirect('savings:savings_list')

    return render(request, 'savings/savings_goal_add.html', {
        'errors': errors,
        'form_data': form_data,
        'goal_type_choices': SavingsGoal.GOAL_TYPE_CHOICES,
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

    emergency_coverage = None
    if goal.goal_type == 'emergency_fund':
        monthly_avg = _get_monthly_avg_expenses(request.user, today)
        emergency_coverage = _get_emergency_fund_coverage(goal.current_amount, monthly_avg)

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
        'withdraw_form': {},
        'projected': projected,
        'monthly_contributions': monthly_contributions,
        'milestones': _get_milestone_data(goal),
        'emergency_coverage': emergency_coverage,
    })


@login_required
def savings_goal_export_csv(request, goal_id):
    """Download contribution history for a savings goal as a CSV file."""
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)

    # Fetch in ascending order to compute running balance
    contributions = (
        goal.contributions
        .select_related('source_account')
        .order_by('date', 'created_at')
    )

    # Pre-compute balance_after for each contribution
    rows = []
    running_balance = Decimal('0')
    for c in contributions.iterator():
        if c.transaction_type == 'withdrawal':
            running_balance -= c.amount
        else:
            running_balance += c.amount
        rows.append((
            c.date.isoformat(),
            str(c.amount),
            c.note or '',
            str(running_balance),
        ))

    # Reverse so newest entries appear first in the CSV
    rows.reverse()

    def _csv_rows():
        class _EchoBuf:
            def write(self, val):
                return val

        writer = csv.writer(_EchoBuf())
        yield writer.writerow(['date', 'amount', 'note', 'balance_after'])
        for row in rows:
            yield writer.writerow(row)

    safe_name = goal.name.replace('"', '').replace(',', '')
    response = StreamingHttpResponse(_csv_rows(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{safe_name}_contributions.csv"'
    return response


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
        goal_type = request.POST.get('goal_type', 'general').strip()
        color = request.POST.get('color', '#00d4aa').strip()
        icon = request.POST.get('icon', '🎯').strip()
        is_private = request.POST.get('is_private') != 'false'

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

        if goal_type not in _VALID_GOAL_TYPES:
            goal_type = 'general'

        if not errors:
            goal.name = name
            goal.description = description
            goal.target_amount = target_amount_val
            goal.deadline = deadline_val
            goal.priority = priority
            goal.goal_type = goal_type
            goal.color = color or '#00d4aa'
            goal.icon = icon or '🎯'
            goal.is_private = is_private
            goal.save()
            success = True

        return render(request, 'savings/savings_goal_edit.html', {
            'goal': goal,
            'errors': errors,
            'success': success,
            'goal_type_choices': SavingsGoal.GOAL_TYPE_CHOICES,
            'form_data': {
                'name': name,
                'description': description,
                'target_amount': target_amount,
                'deadline': deadline,
                'priority': priority,
                'goal_type': goal_type,
                'color': color,
                'icon': icon,
                'is_private': is_private,
            },
        })

    return render(request, 'savings/savings_goal_edit.html', {
        'goal': goal,
        'errors': errors,
        'success': success,
        'goal_type_choices': SavingsGoal.GOAL_TYPE_CHOICES,
        'form_data': {
            'name': goal.name,
            'description': goal.description,
            'target_amount': goal.target_amount,
            'deadline': goal.deadline.strftime('%Y-%m-%d') if goal.deadline else '',
            'priority': goal.priority,
            'goal_type': goal.goal_type,
            'color': goal.color,
            'icon': goal.icon,
            'is_private': goal.is_private,
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

        emergency_coverage = None
        if goal.goal_type == 'emergency_fund':
            monthly_avg = _get_monthly_avg_expenses(request.user, today)
            emergency_coverage = _get_emergency_fund_coverage(goal.current_amount, monthly_avg)

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
            'withdraw_form': {},
            'projected': projected,
            'monthly_contributions': monthly_contributions,
            'milestones': _get_milestone_data(goal),
            'emergency_coverage': emergency_coverage,
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
@require_POST
def savings_goal_withdraw(request, goal_id):
    goal = get_object_or_404(SavingsGoal, pk=goal_id, user=request.user)
    accounts = BankAccount.objects.filter(user=request.user, is_active=True)

    amount_raw = request.POST.get('amount', '').strip()
    account_id = request.POST.get('target_account', '').strip()
    note = request.POST.get('note', '').strip()

    errors = {}

    amount_val = None
    if not amount_raw:
        errors['withdraw_amount'] = 'Amount is required.'
    else:
        try:
            amount_val = Decimal(amount_raw)
            if amount_val <= 0:
                errors['withdraw_amount'] = 'Amount must be greater than zero.'
            elif amount_val > goal.current_amount:
                errors['withdraw_amount'] = f'Cannot withdraw more than the saved amount (${goal.current_amount:,.2f}).'
        except InvalidOperation:
            errors['withdraw_amount'] = 'Please enter a valid number.'

    account_obj = None
    if not account_id:
        errors['target_account'] = 'Please select an account.'
    else:
        try:
            account_obj = accounts.get(pk=account_id)
        except BankAccount.DoesNotExist:
            errors['target_account'] = 'Invalid account.'

    if errors:
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

        emergency_coverage = None
        if goal.goal_type == 'emergency_fund':
            monthly_avg = _get_monthly_avg_expenses(request.user, today)
            emergency_coverage = _get_emergency_fund_coverage(goal.current_amount, monthly_avg)

        return render(request, 'savings/savings_goal_detail.html', {
            'goal': goal,
            'pct': pct,
            'remaining': remaining,
            'days_left': days_left,
            'is_overdue': is_overdue,
            'contributions': contributions,
            'accounts': all_accounts,
            'errors': errors,
            'contribution_form': {'date': today.strftime('%Y-%m-%d')},
            'withdraw_form': {'amount': amount_raw, 'target_account': account_id, 'note': note},
            'projected': projected,
            'monthly_contributions': monthly_contributions,
            'milestones': _get_milestone_data(goal),
            'emergency_coverage': emergency_coverage,
        })

    SavingsContribution.objects.create(
        goal=goal,
        amount=amount_val,
        source_account=account_obj,
        transaction_type='withdrawal',
        date=date.today(),
        note=note,
    )

    goal.refresh_from_db()
    if goal.is_achieved and goal.current_amount < goal.target_amount:
        goal.is_achieved = False
        goal.save()

    messages.success(request, f'Withdrawal of ${amount_val:,.2f} recorded successfully.')
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


def savings_goal_shared(request, share_uuid):
    goal = get_object_or_404(SavingsGoal, share_uuid=share_uuid, is_private=False)

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

    projected = _calculate_projected_completion(goal, today)
    monthly_contributions = _get_monthly_contributions(goal, today)

    emergency_coverage = None
    if goal.goal_type == 'emergency_fund':
        monthly_avg = _get_monthly_avg_expenses(goal.user, today)
        emergency_coverage = _get_emergency_fund_coverage(goal.current_amount, monthly_avg)

    return render(request, 'savings/savings_goal_shared.html', {
        'goal': goal,
        'pct': pct,
        'remaining': remaining,
        'days_left': days_left,
        'is_overdue': is_overdue,
        'projected': projected,
        'monthly_contributions': monthly_contributions,
        'milestones': _get_milestone_data(goal),
        'emergency_coverage': emergency_coverage,
    })
