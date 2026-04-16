import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.db.models.functions import ExtractWeekDay
from django.shortcuts import render

from buckets.models import Bucket
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
_BUCKET_BAR_MAX_W = 100  # % width for largest bucket bar
_MERCHANT_BAR_MAX_W = 100
_DOW_CHART_H = 100
_INCOME_EXPENSE_CHART_H = 140
_INCOME_EXPENSE_MONTHS = 6
_SAVINGS_TREND_CHART_H = 140
_SAVINGS_TREND_LABEL_H = 24
_SAVINGS_RATE_NATIONAL_AVG = 20.0


def _top_merchants(user, year, month):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        )
        .exclude(vendor='')
        .values('vendor')
        .annotate(total=Sum('amount'), count=Count('id'), avg_necessity=Avg('necessity_score'))
        .order_by('-total')[:10]
    )

    rows = []
    for entry in qs:
        avg = entry['avg_necessity']
        avg_rounded = round(Decimal(str(avg)), 1) if avg is not None else None
        rows.append({
            'vendor': entry['vendor'],
            'total': entry['total'] or Decimal('0'),
            'count': entry['count'],
            'avg_necessity': avg_rounded,
            'necessity_color': _score_color(float(avg_rounded) if avg_rounded is not None else None),
        })

    if rows:
        max_total = rows[0]['total']
        for row in rows:
            row['bar_width_pct'] = (
                int(float(row['total'] / max_total) * _MERCHANT_BAR_MAX_W)
                if max_total > 0 else 0
            )
    return rows


def _bucket_breakdown(user, year, month):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        )
        .values('bucket_id')
        .annotate(total=Sum('amount'))
        .order_by('-total')
    )

    bucket_map = {b.pk: b for b in Bucket.objects.filter(user=user)}

    rows = []
    for entry in qs:
        bid = entry['bucket_id']
        amount = entry['total'] or Decimal('0')
        if bid is None:
            name, color = 'Uncategorized', '#888888'
        else:
            bucket = bucket_map.get(bid)
            if bucket is None:
                continue
            name = bucket.name
            color = bucket.color or '#888888'
        rows.append({'name': name, 'color': color, 'amount': amount})

    if not rows:
        return rows

    max_amount = rows[0]['amount']
    for row in rows:
        row['bar_width_pct'] = (
            int(float(row['amount'] / max_amount) * _BUCKET_BAR_MAX_W)
            if max_amount > 0 else 0
        )
    return rows


_DOW_NAMES = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
_DOW_ORDER = [2, 3, 4, 5, 6, 7, 1]  # Mon → Sun


def _dow_pattern(user, year, month):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        )
        .annotate(weekday=ExtractWeekDay('date'))
        .values('weekday')
        .annotate(total=Sum('amount'))
    )
    totals = {row['weekday']: row['total'] or Decimal('0') for row in qs}
    days = [{'label': _DOW_NAMES[d], 'amount': totals.get(d, Decimal('0'))} for d in _DOW_ORDER]
    max_amount = max((d['amount'] for d in days), default=Decimal('0'))
    peak_amount = max_amount
    for day in days:
        day['bar_height_px'] = (
            max(2, int(float(day['amount'] / max_amount) * _DOW_CHART_H))
            if max_amount > 0 else 2
        )
        day['is_peak'] = max_amount > 0 and day['amount'] == peak_amount
    return days


def _income_expense_trend(user, today):
    months = []
    for i in range(_INCOME_EXPENSE_MONTHS - 1, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        income = _month_income(user, year, month)
        expenses = _month_expenses(user, year, month)
        months.append({
            'label': datetime.date(year, month, 1).strftime('%b'),
            'income': income,
            'expenses': expenses,
            'net': income - expenses,
        })
    chart_max = max(
        (max(m['income'], m['expenses']) for m in months),
        default=Decimal('0'),
    )
    for m in months:
        m['income_bar_h'] = (
            max(2, int(float(m['income'] / chart_max) * _INCOME_EXPENSE_CHART_H))
            if chart_max > 0 else 2
        )
        m['expense_bar_h'] = (
            max(2, int(float(m['expenses'] / chart_max) * _INCOME_EXPENSE_CHART_H))
            if chart_max > 0 else 2
        )
        m['net_positive'] = m['net'] >= 0
    return months


def _savings_rate_trend(user, today):
    months = []
    for i in range(11, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        income = _month_income(user, year, month)
        expenses = _month_expenses(user, year, month)
        if income > 0:
            rate = round(float((income - expenses) / income * 100), 1)
        else:
            rate = None
        months.append({
            'label': datetime.date(year, month, 1).strftime('%b'),
            'rate': rate,
        })

    valid_rates = [m['rate'] for m in months if m['rate'] is not None]
    chart_max = max(max(valid_rates), _SAVINGS_RATE_NATIONAL_AVG) if valid_rates else 100.0

    for m in months:
        if m['rate'] is not None:
            chart_y = max(2, int(m['rate'] / chart_max * _SAVINGS_TREND_CHART_H))
            m['dot_bottom_px'] = chart_y + _SAVINGS_TREND_LABEL_H
            m['above_avg'] = m['rate'] >= _SAVINGS_RATE_NATIONAL_AVG
        else:
            m['dot_bottom_px'] = None

    avg_line_px = int(_SAVINGS_RATE_NATIONAL_AVG / chart_max * _SAVINGS_TREND_CHART_H) + _SAVINGS_TREND_LABEL_H
    return months, avg_line_px


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

    # Spending by bucket (current month)
    bucket_breakdown = _bucket_breakdown(request.user, this_year, this_month)

    # Top merchants (current month)
    top_merchants = _top_merchants(request.user, this_year, this_month)

    # Day-of-week spending pattern (current month)
    dow_pattern = _dow_pattern(request.user, this_year, this_month)

    # Income vs expenses — last 6 months
    income_expense_trend = _income_expense_trend(request.user, today)

    # Savings rate trend — last 12 months
    sr_trend_months, sr_avg_line_px = _savings_rate_trend(request.user, today)

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
        'bucket_breakdown': bucket_breakdown,
        'top_merchants': top_merchants,
        'dow_pattern': dow_pattern,
        'income_expense_trend': income_expense_trend,
        'sr_trend_months': sr_trend_months,
        'sr_avg_line_px': sr_avg_line_px,
    })
