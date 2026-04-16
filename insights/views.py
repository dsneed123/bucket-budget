import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import render

from savings.models import SavingsContribution
from transactions.models import Transaction


def _score_color(score):
    if score is None:
        return 'secondary'
    if score >= 7:
        return 'green'
    if score >= 4:
        return 'gold'
    return 'red'


def _month_expenses(user, year, month):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _month_income(user, year, month):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='income',
            date__year=year, date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _month_contributions(user, year, month):
    return (
        SavingsContribution.objects.filter(
            goal__user=user, transaction_type='contribution',
            date__year=year, date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _savings_rate(contributions, income):
    if income > 0:
        return round(float(contributions / income * 100), 1)
    return None


def _spending_quality_score(user, year, month):
    result = Transaction.objects.filter(
        user=user, transaction_type='expense',
        date__year=year, date__month=month,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))
    if not result['count']:
        return None, 0
    return round(Decimal(str(result['avg'])), 1), result['count']


_TREND_CHART_H = 140  # px height for tallest bar


def _monthly_trend(user, today):
    months = []
    for i in range(11, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        amount = _month_expenses(user, year, month)
        months.append({'label': datetime.date(year, month, 1).strftime('%b'), 'amount': amount})
    trend_max = max((m['amount'] for m in months), default=Decimal('0'))
    trend_avg = sum(m['amount'] for m in months) / Decimal('12')
    for m in months:
        m['above_avg'] = trend_avg > 0 and m['amount'] > trend_avg
        m['bar_height_px'] = (
            max(2, int(float(m['amount'] / trend_max) * _TREND_CHART_H))
            if trend_max > 0 else 2
        )
    return months, trend_avg


@login_required
def insights(request):
    today = datetime.date.today()
    this_year, this_month = today.year, today.month

    first_of_month = today.replace(day=1)
    last_month_date = first_of_month - datetime.timedelta(days=1)
    last_year, last_month = last_month_date.year, last_month_date.month

    # This month vs last month spending
    this_spending = _month_expenses(request.user, this_year, this_month)
    last_spending = _month_expenses(request.user, last_year, last_month)

    if last_spending > 0:
        spending_pct_change = round(float((this_spending - last_spending) / last_spending * 100), 1)
    else:
        spending_pct_change = None

    if spending_pct_change is None:
        spending_arrow = None
        spending_arrow_color = 'secondary'
    elif spending_pct_change > 0:
        spending_arrow = 'up'
        spending_arrow_color = 'red'
    elif spending_pct_change < 0:
        spending_arrow = 'down'
        spending_arrow_color = 'green'
    else:
        spending_arrow = 'same'
        spending_arrow_color = 'secondary'

    # Savings rate
    cur_income = _month_income(request.user, this_year, this_month)
    cur_contributions = _month_contributions(request.user, this_year, this_month)
    cur_savings_rate = _savings_rate(cur_contributions, cur_income)

    prev_income = _month_income(request.user, last_year, last_month)
    prev_contributions = _month_contributions(request.user, last_year, last_month)
    prev_savings_rate = _savings_rate(prev_contributions, prev_income)

    if cur_savings_rate is None:
        savings_color = 'secondary'
    elif cur_savings_rate >= 20:
        savings_color = 'green'
    elif cur_savings_rate >= 10:
        savings_color = 'gold'
    else:
        savings_color = 'red'

    if cur_savings_rate is not None and prev_savings_rate is not None:
        if cur_savings_rate > prev_savings_rate:
            savings_arrow = 'up'
        elif cur_savings_rate < prev_savings_rate:
            savings_arrow = 'down'
        else:
            savings_arrow = 'same'
    else:
        savings_arrow = None

    # Spending quality score
    quality_score, quality_count = _spending_quality_score(request.user, this_year, this_month)
    last_quality_score, _ = _spending_quality_score(request.user, last_year, last_month)
    quality_color = _score_color(quality_score)

    if quality_score is not None and last_quality_score is not None:
        if quality_score > last_quality_score:
            quality_arrow = 'up'
        elif quality_score < last_quality_score:
            quality_arrow = 'down'
        else:
            quality_arrow = 'same'
    else:
        quality_arrow = None

    # 12-month spending trend
    trend_months, trend_avg = _monthly_trend(request.user, today)

    return render(request, 'insights/insights.html', {
        'current_month': today.strftime('%B %Y'),
        'last_month_label': last_month_date.strftime('%B %Y'),
        'this_spending': this_spending,
        'last_spending': last_spending,
        'spending_pct_change': spending_pct_change,
        'spending_arrow': spending_arrow,
        'spending_arrow_color': spending_arrow_color,
        'cur_savings_rate': cur_savings_rate,
        'prev_savings_rate': prev_savings_rate,
        'savings_color': savings_color,
        'savings_arrow': savings_arrow,
        'quality_score': quality_score,
        'quality_count': quality_count,
        'quality_color': quality_color,
        'quality_arrow': quality_arrow,
        'last_quality_score': last_quality_score,
        'trend_months': trend_months,
        'trend_avg': trend_avg,
    })
