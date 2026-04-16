from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

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
