from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .models import SavingsGoal


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
                from datetime import datetime
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
