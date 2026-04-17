import datetime
import math
from decimal import Decimal

from django.core.cache import cache
from django.db.models import Avg, Count, Sum

from transactions.models import Transaction

from .models import BankAccount, BalanceHistory

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

    cache_key = f'sidebar_data_{request.user.pk}'
    data = cache.get(cache_key)
    if data is not None:
        return data

    accounts = list(BankAccount.objects.filter(user=request.user, is_active=True))
    net_worth_value = sum((a.balance for a in accounts), Decimal('0'))

    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - datetime.timedelta(days=1)

    account_ids = [a.pk for a in accounts]
    all_history = (
        list(BalanceHistory.objects.filter(account_id__in=account_ids)
             .values('account_id', 'change_amount', 'created_at'))
        if account_ids else []
    )

    prev_net_worth = Decimal('0')
    for account in accounts:
        if account.created_at.date() > last_month_end:
            continue
        changes_after = sum(
            (h['change_amount'] for h in all_history
             if h['account_id'] == account.pk
             and h['created_at'].date() > last_month_end),
            Decimal('0'),
        )
        prev_net_worth += account.balance - changes_after

    net_worth_change = net_worth_value - prev_net_worth
    if net_worth_change > 0:
        net_worth_arrow = 'up'
    elif net_worth_change < 0:
        net_worth_arrow = 'down'
    else:
        net_worth_arrow = 'same'

    unscored_count = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        necessity_score__isnull=True,
    ).count()

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

    def _month_expenses(year, month):
        return Transaction.objects.filter(
            user=request.user,
            transaction_type='expense',
            date__year=year,
            date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')

    def _savings_rate(income, expenses):
        if income > 0:
            return round(float((income - expenses) / income * 100), 1)
        return None

    cur_income = _month_income(today.year, today.month)
    cur_expenses = _month_expenses(today.year, today.month)
    cur_savings_rate = _savings_rate(cur_income, cur_expenses)

    prev_income = _month_income(last_month_end.year, last_month_end.month)
    prev_expenses = _month_expenses(last_month_end.year, last_month_end.month)
    prev_savings_rate = _savings_rate(prev_income, prev_expenses)

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

    data = {
        'net_worth': net_worth_value,
        'net_worth_change': net_worth_change,
        'net_worth_change_abs': abs(net_worth_change),
        'net_worth_arrow': net_worth_arrow,
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
    cache.set(cache_key, data, 60)
    return data
