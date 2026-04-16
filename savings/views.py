from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from banking.models import BankAccount

from .models import SavingsContribution, SavingsGoal


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

        goal_data.append({
            'goal': goal,
            'pct': pct,
            'remaining': remaining,
            'days_left': days_left,
            'is_overdue': is_overdue,
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
    })
