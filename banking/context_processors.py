import datetime
import math
from decimal import Decimal

from django.db.models import Avg, Count, Sum

from savings.models import SavingsContribution
from transactions.models import Transaction

from .models import BankAccount

_CIRCLE_RADIUS = 28
_CIRCUMFERENCE = round(2 * math.pi * _CIRCLE_RADIUS, 2)  # ~175.93


def _score_color(score):
    if score is None:
        return 'secondary'
    if score >= 7:
        return 'green'
    if score >= 4:
        return 'gold'
    return 'red'


def net_worth(request):
    if not request.user.is_authenticated:
        return {}

    total = (
        BankAccount.objects.filter(user=request.user, is_active=True)
        .values_list('balance', flat=True)
    )
    net_worth_value = sum(total, 0)
    unscored_count = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        necessity_score__isnull=True,
    ).count()

    today = datetime.date.today()
    result = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        date__year=today.year,
        date__month=today.month,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))

    if result['count']:
        avg = round(Decimal(str(result['avg'])), 1)
        progress = float(avg) / 10.0
        dashoffset = round(_CIRCUMFERENCE * (1 - progress), 2)
        color = _score_color(float(avg))
    else:
        avg = None
        dashoffset = _CIRCUMFERENCE
        color = 'secondary'

    # --- Savings Rate ---
    def _month_income(year, month):
        return Transaction.objects.filter(
            user=request.user,
            transaction_type='income',
            date__year=year,
            date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    def _month_contributions(year, month):
        return SavingsContribution.objects.filter(
            goal__user=request.user,
            transaction_type='contribution',
            date__year=year,
            date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    def _savings_rate(contributions, income):
        if income > 0:
            return round(float(contributions / income * 100), 1)
        return None

    cur_income = _month_income(today.year, today.month)
    cur_contributions = _month_contributions(today.year, today.month)
    cur_savings_rate = _savings_rate(cur_contributions, cur_income)

    first_of_month = today.replace(day=1)
    last_month = first_of_month - datetime.timedelta(days=1)
    prev_income = _month_income(last_month.year, last_month.month)
    prev_contributions = _month_contributions(last_month.year, last_month.month)
    prev_savings_rate = _savings_rate(prev_contributions, prev_income)

    if cur_savings_rate is None:
        savings_rate_color = 'secondary'
    elif cur_savings_rate >= 20:
        savings_rate_color = 'green'
    elif cur_savings_rate >= 10:
        savings_rate_color = 'gold'
    else:
        savings_rate_color = 'red'

    if cur_savings_rate is not None and prev_savings_rate is not None:
        if cur_savings_rate > prev_savings_rate:
            savings_rate_arrow = 'up'
        elif cur_savings_rate < prev_savings_rate:
            savings_rate_arrow = 'down'
        else:
            savings_rate_arrow = 'same'
    else:
        savings_rate_arrow = None

    return {
        'net_worth': net_worth_value,
        'unscored_count': unscored_count,
        'sidebar_quality_score': avg,
        'sidebar_quality_color': color,
        'sidebar_quality_dashoffset': dashoffset,
        'sidebar_quality_circumference': _CIRCUMFERENCE,
        'sidebar_savings_rate': cur_savings_rate,
        'sidebar_savings_rate_color': savings_rate_color,
        'sidebar_savings_rate_arrow': savings_rate_arrow,
        'sidebar_savings_rate_prev': prev_savings_rate,
    }
