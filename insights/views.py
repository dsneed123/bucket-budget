import calendar
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Max, Min, Sum
from django.db.models.functions import ExtractWeekDay
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from banking.models import BalanceHistory, BankAccount
from buckets.models import Bucket
from savings.models import SavingsContribution, SavingsGoal, SavingsMilestone
from transactions.models import Transaction

from .models import Recommendation
from .recommendations import refresh_recommendations
from core.utils import make_breadcrumbs


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


def _resolve_date_range(preset, date_from_str, date_to_str, today):
    """Return (date_from, date_to, prev_date_from, prev_date_to, period_label, preset)."""
    if preset == 'last_month':
        first = today.replace(day=1)
        end = first - datetime.timedelta(days=1)
        start = end.replace(day=1)
    elif preset == 'last_3_months':
        end = today
        m = today.month - 3
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start = datetime.date(y, m, 1)
    elif preset == 'last_6_months':
        end = today
        m = today.month - 6
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        start = datetime.date(y, m, 1)
    elif preset == 'this_year':
        start = datetime.date(today.year, 1, 1)
        end = today
    elif preset == 'custom' and date_from_str and date_to_str:
        try:
            start = datetime.date.fromisoformat(date_from_str)
            end = datetime.date.fromisoformat(date_to_str)
            if start > end:
                start, end = end, start
        except ValueError:
            preset = 'this_month'
            start = today.replace(day=1)
            end = today
    else:
        preset = 'this_month'
        start = today.replace(day=1)
        end = today

    delta_days = (end - start).days + 1
    prev_end = start - datetime.timedelta(days=1)
    prev_start = prev_end - datetime.timedelta(days=delta_days - 1)

    if start.year == end.year and start.month == end.month:
        label = start.strftime('%B %Y')
    elif start.year == end.year:
        label = f"{start.strftime('%b')} \u2013 {end.strftime('%b %Y')}"
    else:
        label = f"{start.strftime('%b %Y')} \u2013 {end.strftime('%b %Y')}"

    if prev_start.year == prev_end.year and prev_start.month == prev_end.month:
        prev_label = prev_start.strftime('%B %Y')
    elif prev_start.year == prev_end.year:
        prev_label = f"{prev_start.strftime('%b')} \u2013 {prev_end.strftime('%b %Y')}"
    else:
        prev_label = f"{prev_start.strftime('%b %Y')} \u2013 {prev_end.strftime('%b %Y')}"

    return start, end, prev_start, prev_end, label, prev_label, preset


def _range_expenses(user, date_from, date_to):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=date_from, date__lte=date_to,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _range_income(user, date_from, date_to):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='income',
            date__gte=date_from, date__lte=date_to,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _range_contributions(user, date_from, date_to):
    return (
        SavingsContribution.objects.filter(
            goal__user=user, transaction_type='contribution',
            date__gte=date_from, date__lte=date_to,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _range_quality_score(user, date_from, date_to):
    result = Transaction.objects.filter(
        user=user, transaction_type='expense',
        date__gte=date_from, date__lte=date_to,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))
    if not result['count']:
        return None, 0
    return round(Decimal(str(result['avg'])), 1), result['count']


def _range_top_merchants(user, date_from, date_to):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=date_from, date__lte=date_to,
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


def _range_bucket_breakdown(user, date_from, date_to):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=date_from, date__lte=date_to,
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


def _range_dow_pattern(user, date_from, date_to):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=date_from, date__lte=date_to,
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
        day['bar_height_pct'] = (
            int(float(day['amount'] / max_amount) * 100)
            if max_amount > 0 else 0
        )
        day['is_peak'] = max_amount > 0 and day['amount'] == peak_amount
    return days


def _range_expense_ratio(user, date_from, date_to):
    income = _range_income(user, date_from, date_to)
    if income <= 0:
        return None

    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=date_from, date__lte=date_to,
        )
        .values('bucket_id')
        .annotate(total=Sum('amount'))
    )
    bucket_map = {b.pk: b for b in Bucket.objects.filter(user=user)}

    bucket_spending = {}
    for entry in qs:
        bid = entry['bucket_id']
        amount = entry['total'] or Decimal('0')
        name = 'Uncategorized' if bid is None else (bucket_map[bid].name if bid in bucket_map else None)
        if name is not None:
            bucket_spending[name] = bucket_spending.get(name, Decimal('0')) + amount

    category_spending = {cat['key']: Decimal('0') for cat in _EXPENSE_RATIO_CATEGORIES}
    for bucket_name, amount in bucket_spending.items():
        lower = bucket_name.lower()
        for cat in _EXPENSE_RATIO_CATEGORIES:
            if any(kw in lower for kw in cat['keywords']):
                category_spending[cat['key']] += amount
                break

    rows = []
    for cat in _EXPENSE_RATIO_CATEGORIES:
        spent = category_spending[cat['key']]
        pct = round(float(spent / income * 100), 1)
        min_pct, max_pct = cat['min_pct'], cat['max_pct']
        if pct > max_pct + _RATIO_SIGNIFICANT_OVER_PP:
            status, status_color, status_label = 'high', 'red', 'Significantly over'
        elif pct > max_pct:
            status, status_color, status_label = 'over', 'gold', 'Above recommended'
        elif pct >= min_pct:
            status, status_color, status_label = 'ok', 'green', 'On track'
        else:
            status, status_color, status_label = 'under', 'secondary', 'Below range'
        bar_pct = min(int(pct / _RATIO_BAR_SCALE * 100), 100)
        rec_min_bar = int(min_pct / _RATIO_BAR_SCALE * 100)
        rec_max_bar = int(max_pct / _RATIO_BAR_SCALE * 100)
        rec_band_width = rec_max_bar - rec_min_bar
        rows.append({
            'label': cat['key'],
            'description': cat['description'],
            'spent': spent,
            'pct': pct,
            'min_pct': min_pct,
            'max_pct': max_pct,
            'status': status,
            'status_color': status_color,
            'status_label': status_label,
            'bar_pct': bar_pct,
            'rec_min_bar': rec_min_bar,
            'rec_band_width': rec_band_width,
        })

    contributions = _range_contributions(user, date_from, date_to)
    savings_pct = round(float(contributions / income * 100), 1)
    savings_target = 20
    if savings_pct >= savings_target:
        savings_status, savings_color, savings_status_label = 'ok', 'green', 'On track'
    elif savings_pct >= savings_target * 0.75:
        savings_status, savings_color, savings_status_label = 'under', 'gold', 'Below target'
    else:
        savings_status, savings_color, savings_status_label = 'low', 'red', 'Significantly under'

    savings_bar_pct = min(int(savings_pct / _RATIO_BAR_SCALE * 100), 100)
    savings_rec_bar = int(savings_target / _RATIO_BAR_SCALE * 100)
    savings_row = {
        'label': 'Savings',
        'description': 'Contributions to savings goals',
        'contributed': contributions,
        'pct': savings_pct,
        'target_pct': savings_target,
        'status': savings_status,
        'status_color': savings_color,
        'status_label': savings_status_label,
        'bar_pct': savings_bar_pct,
        'rec_target_bar': savings_rec_bar,
    }

    flagged = sum(1 for r in rows if r['status'] in ('over', 'high'))
    return {
        'income': income,
        'rows': rows,
        'savings_row': savings_row,
        'flagged_count': flagged,
    }


def _has_12_months_data(user, today):
    cutoff = datetime.date(today.year - 1, today.month, 1)
    return Transaction.objects.filter(user=user, date__lt=cutoff).exists()


def _yoy_comparison(user, today):
    this_year, this_month = today.year, today.month
    last_year = this_year - 1

    this_spending = _month_expenses(user, this_year, this_month)
    last_spending = _month_expenses(user, last_year, this_month)

    if last_spending > 0:
        spending_pct = round(float((this_spending - last_spending) / last_spending * 100), 1)
    else:
        spending_pct = None

    if spending_pct is None:
        spending_arrow, spending_arrow_color = None, 'secondary'
    elif spending_pct > 0:
        spending_arrow, spending_arrow_color = 'up', 'red'
    elif spending_pct < 0:
        spending_arrow, spending_arrow_color = 'down', 'green'
    else:
        spending_arrow, spending_arrow_color = 'same', 'secondary'

    this_income = _month_income(user, this_year, this_month)
    this_contrib = _month_contributions(user, this_year, this_month)
    last_income = _month_income(user, last_year, this_month)
    last_contrib = _month_contributions(user, last_year, this_month)
    this_sr = _savings_rate(this_contrib, this_income)
    last_sr = _savings_rate(last_contrib, last_income)

    if this_sr is not None and last_sr is not None:
        sr_delta = round(this_sr - last_sr, 1)
        if sr_delta > 0:
            sr_arrow, sr_arrow_color = 'up', 'green'
        elif sr_delta < 0:
            sr_arrow, sr_arrow_color = 'down', 'red'
        else:
            sr_arrow, sr_arrow_color = 'same', 'secondary'
    else:
        sr_delta, sr_arrow, sr_arrow_color = None, None, 'secondary'

    bucket_map = {b.pk: b for b in Bucket.objects.filter(user=user)}

    this_buckets = {
        row['bucket_id']: row['total'] or Decimal('0')
        for row in Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=this_year, date__month=this_month,
        ).values('bucket_id').annotate(total=Sum('amount'))
    }
    last_buckets = {
        row['bucket_id']: row['total'] or Decimal('0')
        for row in Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=last_year, date__month=this_month,
        ).values('bucket_id').annotate(total=Sum('amount'))
    }

    bucket_rows = []
    for bid in set(this_buckets) | set(last_buckets):
        this_amt = this_buckets.get(bid, Decimal('0'))
        last_amt = last_buckets.get(bid, Decimal('0'))
        if bid is None:
            name, color = 'Uncategorized', '#888888'
        else:
            bucket = bucket_map.get(bid)
            if bucket is None:
                continue
            name, color = bucket.name, bucket.color or '#888888'
        pct = round(float((this_amt - last_amt) / last_amt * 100), 1) if last_amt > 0 else None
        if pct is None:
            arrow, arrow_color = None, 'secondary'
        elif pct > 0:
            arrow, arrow_color = 'up', 'red'
        elif pct < 0:
            arrow, arrow_color = 'down', 'green'
        else:
            arrow, arrow_color = 'same', 'secondary'
        bucket_rows.append({
            'name': name, 'color': color,
            'this_amount': this_amt, 'last_amount': last_amt,
            'pct_change': pct, 'arrow': arrow, 'arrow_color': arrow_color,
        })

    bucket_rows.sort(key=lambda r: r['this_amount'], reverse=True)
    max_amt = max(
        (max(r['this_amount'], r['last_amount']) for r in bucket_rows),
        default=Decimal('0'),
    )
    for row in bucket_rows:
        row['this_bar_pct'] = int(float(row['this_amount'] / max_amt) * 100) if max_amt > 0 else 0
        row['last_bar_pct'] = int(float(row['last_amount'] / max_amt) * 100) if max_amt > 0 else 0

    return {
        'this_spending': this_spending,
        'last_spending': last_spending,
        'spending_pct_change': spending_pct,
        'spending_arrow': spending_arrow,
        'spending_arrow_color': spending_arrow_color,
        'this_savings_rate': this_sr,
        'last_savings_rate': last_sr,
        'sr_delta': sr_delta,
        'sr_arrow': sr_arrow,
        'sr_arrow_color': sr_arrow_color,
        'bucket_rows': bucket_rows,
        'this_month_label': today.strftime('%B %Y'),
        'last_year_month_label': datetime.date(last_year, this_month, 1).strftime('%B %Y'),
    }


_RATIO_BAR_SCALE = 50  # 50% of income = 100% bar width
_RATIO_SIGNIFICANT_OVER_PP = 5  # flag if >5pp above recommended max

_EXPENSE_RATIO_CATEGORIES = [
    {
        'key': 'Housing',
        'description': 'Rent, mortgage, utilities',
        'keywords': ['rent', 'mortgage', 'home', 'housing', 'utilities', 'utility', 'electric', 'electricity', 'internet', 'cable', 'hoa'],
        'min_pct': 25, 'max_pct': 30,
    },
    {
        'key': 'Food',
        'description': 'Groceries, dining, coffee',
        'keywords': ['food', 'groceries', 'grocery', 'dining', 'restaurant', 'coffee', 'eat', 'lunch', 'dinner', 'breakfast', 'takeout', 'meals', 'cafe'],
        'min_pct': 10, 'max_pct': 15,
    },
    {
        'key': 'Transportation',
        'description': 'Car, fuel, transit, rideshare',
        'keywords': ['transport', 'car', 'auto', 'vehicle', 'fuel', 'transit', 'uber', 'lyft', 'parking', 'commute', 'bus', 'train', 'subway', 'toll'],
        'min_pct': 10, 'max_pct': 15,
    },
]


def _expense_ratio_analysis(user, year, month):
    income = _month_income(user, year, month)
    if income <= 0:
        return None

    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        )
        .values('bucket_id')
        .annotate(total=Sum('amount'))
    )
    bucket_map = {b.pk: b for b in Bucket.objects.filter(user=user)}

    bucket_spending = {}
    for entry in qs:
        bid = entry['bucket_id']
        amount = entry['total'] or Decimal('0')
        name = 'Uncategorized' if bid is None else (bucket_map[bid].name if bid in bucket_map else None)
        if name is not None:
            bucket_spending[name] = bucket_spending.get(name, Decimal('0')) + amount

    category_spending = {cat['key']: Decimal('0') for cat in _EXPENSE_RATIO_CATEGORIES}
    for bucket_name, amount in bucket_spending.items():
        lower = bucket_name.lower()
        for cat in _EXPENSE_RATIO_CATEGORIES:
            if any(kw in lower for kw in cat['keywords']):
                category_spending[cat['key']] += amount
                break

    rows = []
    for cat in _EXPENSE_RATIO_CATEGORIES:
        spent = category_spending[cat['key']]
        pct = round(float(spent / income * 100), 1)
        min_pct, max_pct = cat['min_pct'], cat['max_pct']

        if pct > max_pct + _RATIO_SIGNIFICANT_OVER_PP:
            status, status_color, status_label = 'high', 'red', 'Significantly over'
        elif pct > max_pct:
            status, status_color, status_label = 'over', 'gold', 'Above recommended'
        elif pct >= min_pct:
            status, status_color, status_label = 'ok', 'green', 'On track'
        else:
            status, status_color, status_label = 'under', 'secondary', 'Below range'

        bar_pct = min(int(pct / _RATIO_BAR_SCALE * 100), 100)
        rec_min_bar = int(min_pct / _RATIO_BAR_SCALE * 100)
        rec_max_bar = int(max_pct / _RATIO_BAR_SCALE * 100)
        rec_band_width = rec_max_bar - rec_min_bar
        rows.append({
            'label': cat['key'],
            'description': cat['description'],
            'spent': spent,
            'pct': pct,
            'min_pct': min_pct,
            'max_pct': max_pct,
            'status': status,
            'status_color': status_color,
            'status_label': status_label,
            'bar_pct': bar_pct,
            'rec_min_bar': rec_min_bar,
            'rec_band_width': rec_band_width,
        })

    contributions = _month_contributions(user, year, month)
    savings_pct = round(float(contributions / income * 100), 1)
    savings_target = 20
    if savings_pct >= savings_target:
        savings_status, savings_color, savings_status_label = 'ok', 'green', 'On track'
    elif savings_pct >= savings_target * 0.75:
        savings_status, savings_color, savings_status_label = 'under', 'gold', 'Below target'
    else:
        savings_status, savings_color, savings_status_label = 'low', 'red', 'Significantly under'

    savings_bar_pct = min(int(savings_pct / _RATIO_BAR_SCALE * 100), 100)
    savings_rec_bar = int(savings_target / _RATIO_BAR_SCALE * 100)

    savings_row = {
        'label': 'Savings',
        'description': 'Contributions to savings goals',
        'contributed': contributions,
        'pct': savings_pct,
        'target_pct': savings_target,
        'status': savings_status,
        'status_color': savings_color,
        'status_label': savings_status_label,
        'bar_pct': savings_bar_pct,
        'rec_target_bar': savings_rec_bar,
    }

    flagged = sum(1 for r in rows if r['status'] in ('over', 'high'))
    return {
        'income': income,
        'rows': rows,
        'savings_row': savings_row,
        'flagged_count': flagged,
    }


_TREND_CHART_H = 140  # px height for tallest bar
_NW_CHART_H = 140
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
        day['bar_height_pct'] = (
            int(float(day['amount'] / max_amount) * 100)
            if max_amount > 0 else 0
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
            int(float(m['income'] / chart_max) * 100)
            if chart_max > 0 else 0
        )
        m['expense_bar_h'] = (
            int(float(m['expenses'] / chart_max) * 100)
            if chart_max > 0 else 0
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


_HEATMAP_DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']


def _daily_heatmap(user, year, month):
    qs = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        )
        .values('date')
        .annotate(total=Sum('amount'))
    )
    daily_totals = {row['date']: row['total'] or Decimal('0') for row in qs}

    amounts = [v for v in daily_totals.values() if v > 0]
    if amounts:
        max_amount = max(amounts)
        low_threshold = max_amount / Decimal('3')
        high_threshold = max_amount * Decimal('2') / Decimal('3')
    else:
        max_amount = low_threshold = high_threshold = Decimal('0')

    today = datetime.date.today()
    weeks = []
    for week in calendar.monthcalendar(year, month):
        week_days = []
        for day_num in week:
            if day_num == 0:
                week_days.append({'day': 0, 'is_current_month': False})
            else:
                d = datetime.date(year, month, day_num)
                amount = daily_totals.get(d, Decimal('0'))
                is_future = d > today
                if is_future or amount <= 0:
                    color = 'none'
                elif amount <= low_threshold:
                    color = 'green'
                elif amount <= high_threshold:
                    color = 'yellow'
                else:
                    color = 'red'
                week_days.append({
                    'day': day_num,
                    'date_str': d.strftime('%Y-%m-%d'),
                    'amount': amount,
                    'color': color,
                    'is_today': d == today,
                    'is_future': is_future,
                    'is_current_month': True,
                })
        weeks.append(week_days)
    return weeks


def _spending_forecast(user, year, month, today):
    days_in_month = calendar.monthrange(year, month)[1]
    days_elapsed = today.day

    current_spending = _month_expenses(user, year, month)

    if days_elapsed > 0:
        daily_avg = current_spending / Decimal(str(days_elapsed))
        projected = (daily_avg * Decimal(str(days_in_month))).quantize(Decimal('0.01'))
    else:
        daily_avg = Decimal('0')
        projected = Decimal('0')

    total_budget = (
        Bucket.objects.filter(user=user, is_active=True)
        .aggregate(s=Sum('monthly_allocation'))['s'] or Decimal('0')
    )

    days_remaining = days_in_month - days_elapsed

    if total_budget > 0:
        budget_pct = min(int(float(projected / total_budget) * 100), 200)
        current_pct = min(int(float(current_spending / total_budget) * 100), 100)
        over_budget = projected > total_budget
        raw_delta = projected - total_budget
        abs_delta = abs(raw_delta)
        over_budget = raw_delta > 0
    else:
        budget_pct = None
        current_pct = None
        over_budget = None
        abs_delta = None

    return {
        'current_spending': current_spending,
        'projected_amount': projected,
        'daily_avg': round(daily_avg, 2),
        'days_elapsed': days_elapsed,
        'days_in_month': days_in_month,
        'days_remaining': days_remaining,
        'total_budget': total_budget,
        'budget_pct': budget_pct,
        'current_pct': current_pct,
        'over_budget': over_budget,
        'abs_delta': abs_delta,
    }


def _net_worth_trend(user, today):
    accounts = list(BankAccount.objects.filter(user=user, is_active=True))
    goals = list(SavingsGoal.objects.filter(user=user))

    account_ids = [a.pk for a in accounts]
    goal_ids = [g.pk for g in goals]

    all_history = (
        list(BalanceHistory.objects.filter(account_id__in=account_ids)
             .values('account_id', 'change_amount', 'created_at'))
        if account_ids else []
    )
    all_contributions = (
        list(SavingsContribution.objects.filter(goal_id__in=goal_ids)
             .values('goal_id', 'amount', 'date', 'transaction_type'))
        if goal_ids else []
    )

    months = []
    for i in range(11, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1

        end_of_month = datetime.date(year, month, calendar.monthrange(year, month)[1])

        bank_total = Decimal('0')
        for account in accounts:
            if account.created_at.date() > end_of_month:
                continue
            changes_after = sum(
                (h['change_amount'] for h in all_history
                 if h['account_id'] == account.pk
                 and h['created_at'].date() > end_of_month),
                Decimal('0'),
            )
            bank_total += account.balance - changes_after

        savings_total = Decimal('0')
        for goal in goals:
            if goal.created_at.date() > end_of_month:
                continue
            net_after = sum(
                (c['amount'] if c['transaction_type'] == 'contribution' else -c['amount']
                 for c in all_contributions
                 if c['goal_id'] == goal.pk and c['date'] > end_of_month),
                Decimal('0'),
            )
            amount = goal.current_amount - net_after
            savings_total += max(amount, Decimal('0'))

        net_worth = bank_total + savings_total
        months.append({
            'label': datetime.date(year, month, 1).strftime('%b'),
            'net_worth': net_worth,
            'bank_total': bank_total,
            'savings_total': savings_total,
        })

    if len(months) >= 2 and months[-2]['net_worth'] != 0:
        change_pct = round(float(
            (months[-1]['net_worth'] - months[-2]['net_worth'])
            / abs(months[-2]['net_worth']) * 100
        ), 1)
    else:
        change_pct = None

    if change_pct is not None:
        if change_pct > 0:
            change_arrow, change_color = 'up', 'green'
        elif change_pct < 0:
            change_arrow, change_color = 'down', 'red'
        else:
            change_arrow, change_color = 'same', 'secondary'
    else:
        change_arrow, change_color = None, 'secondary'

    all_values = [abs(m['net_worth']) for m in months]
    max_abs = max(all_values, default=Decimal('0'))
    for m in months:
        m['positive'] = m['net_worth'] >= 0
        m['bar_height_pct'] = (
            int(float(abs(m['net_worth']) / max_abs) * 100)
            if max_abs > 0 else 0
        )

    current = months[-1] if months else None
    return months, change_pct, change_arrow, change_color, current


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
        m['bar_height_pct'] = (
            int(float(m['amount'] / trend_max) * 100)
            if trend_max > 0 else 0
        )
    return months, trend_avg


def _financial_health_score(user, year, month, cur_savings_rate, quality_score, forecast):
    """Return 0-100 health score with per-component breakdown."""

    # 1. Savings Rate — 25 pts (target: ≥20%)
    if cur_savings_rate is None:
        sr_pts = 0
        sr_flag = 'No income recorded'
    else:
        sr_pts = min(25, round(float(cur_savings_rate) / 20.0 * 25))
        sr_flag = None

    # 2. Spending Quality — 20 pts (necessity score 1-10 → 0-20)
    if quality_score is None:
        sq_pts = 0
        sq_flag = 'No scored transactions'
    else:
        sq_pts = round(float(quality_score) / 10.0 * 20)
        sq_flag = None

    # 3. Budget Adherence — 20 pts (under budget = full pts; 50%+ over = 0)
    if not forecast['total_budget']:
        ba_pts = 0
        ba_flag = 'No budget set'
    else:
        ratio = float(forecast['current_spending']) / float(forecast['total_budget'])
        if ratio <= 1.0:
            ba_pts = 20
        elif ratio <= 1.5:
            ba_pts = round(20 * (1.5 - ratio) / 0.5)
        else:
            ba_pts = 0
        ba_flag = None

    # 4. Emergency Fund Progress — 15 pts
    ef_goals = list(SavingsGoal.objects.filter(user=user, goal_type='emergency_fund', is_achieved=False))
    if not ef_goals:
        ef_goals = list(SavingsGoal.objects.filter(user=user, is_achieved=False))
    if ef_goals:
        total_target = sum(float(g.target_amount) for g in ef_goals)
        total_current = sum(float(g.current_amount) for g in ef_goals)
        progress = min(1.0, total_current / total_target) if total_target > 0 else 0.0
        ef_pts = round(progress * 15)
        ef_flag = None
    elif SavingsGoal.objects.filter(user=user, is_achieved=True).exists():
        ef_pts = 15
        ef_flag = None
    else:
        ef_pts = 0
        ef_flag = 'No savings goals set'

    # 5. Expense Trend — 10 pts (current vs 3-month prior average)
    prior = []
    for i in range(1, 4):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        prior.append(_month_expenses(user, y, m))
    prior_avg = sum(prior) / Decimal('3')
    current_expenses = _month_expenses(user, year, month)
    if prior_avg <= 0:
        trend_pts = 5
        trend_flag = 'Insufficient history'
    else:
        ratio = float(current_expenses) / float(prior_avg)
        if ratio <= 1.0:
            trend_pts = 10
        elif ratio <= 1.3:
            trend_pts = round(10 * (1.3 - ratio) / 0.3)
        else:
            trend_pts = 0
        trend_flag = None

    # 6. Consistency — 10 pts (months with transactions in past 6 months)
    active = 0
    for i in range(1, 7):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        if Transaction.objects.filter(user=user, date__year=y, date__month=m).exists():
            active += 1
    consistency_pts = round(active / 6 * 10)
    consistency_flag = None if active >= 3 else 'Limited transaction history'

    total = max(0, min(100, sr_pts + sq_pts + ba_pts + ef_pts + trend_pts + consistency_pts))

    if total >= 90:
        grade = 'A'
    elif total >= 80:
        grade = 'B'
    elif total >= 70:
        grade = 'C'
    elif total >= 60:
        grade = 'D'
    else:
        grade = 'F'

    if total >= 80:
        gauge_color = 'var(--accent-green)'
    elif total >= 60:
        gauge_color = 'var(--accent-gold)'
    else:
        gauge_color = 'var(--accent-red)'

    gauge_filled_deg = round(total / 100 * 180, 1)

    components = [
        {'label': 'Savings Rate', 'pts': sr_pts, 'max': 25, 'flag': sr_flag,
         'bar_pct': round(sr_pts / 25 * 100)},
        {'label': 'Spending Quality', 'pts': sq_pts, 'max': 20, 'flag': sq_flag,
         'bar_pct': round(sq_pts / 20 * 100)},
        {'label': 'Budget Adherence', 'pts': ba_pts, 'max': 20, 'flag': ba_flag,
         'bar_pct': round(ba_pts / 20 * 100)},
        {'label': 'Emergency Fund', 'pts': ef_pts, 'max': 15, 'flag': ef_flag,
         'bar_pct': round(ef_pts / 15 * 100)},
        {'label': 'Expense Trend', 'pts': trend_pts, 'max': 10, 'flag': trend_flag,
         'bar_pct': round(trend_pts / 10 * 100)},
        {'label': 'Consistency', 'pts': consistency_pts, 'max': 10, 'flag': consistency_flag,
         'bar_pct': round(consistency_pts / 10 * 100)},
    ]

    return {
        'score': total,
        'grade': grade,
        'gauge_color': gauge_color,
        'gauge_filled_deg': gauge_filled_deg,
        'components': components,
    }


@login_required
def insights(request):
    today = datetime.date.today()

    preset = request.GET.get('preset', 'this_month')
    date_from_str = request.GET.get('date_from', '')
    date_to_str = request.GET.get('date_to', '')

    date_from, date_to, prev_date_from, prev_date_to, period_label, prev_period_label, preset = (
        _resolve_date_range(preset, date_from_str, date_to_str, today)
    )

    # Period spending
    this_spending = _range_expenses(request.user, date_from, date_to)
    last_spending = _range_expenses(request.user, prev_date_from, prev_date_to)
    has_data = Transaction.objects.filter(user=request.user, date__gte=date_from, date__lte=date_to).exists()

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
    cur_income = _range_income(request.user, date_from, date_to)
    cur_contributions = _range_contributions(request.user, date_from, date_to)
    cur_savings_rate = _savings_rate(cur_contributions, cur_income)

    prev_income = _range_income(request.user, prev_date_from, prev_date_to)
    prev_contributions = _range_contributions(request.user, prev_date_from, prev_date_to)
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
    quality_score, quality_count = _range_quality_score(request.user, date_from, date_to)
    last_quality_score, _ = _range_quality_score(request.user, prev_date_from, prev_date_to)
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

    # 12-month spending trend (always anchored to today)
    trend_months, trend_avg = _monthly_trend(request.user, today)

    # Spending by bucket for selected period
    bucket_breakdown = _range_bucket_breakdown(request.user, date_from, date_to)

    # Top merchants for selected period
    top_merchants = _range_top_merchants(request.user, date_from, date_to)

    # Day-of-week spending pattern for selected period
    dow_pattern = _range_dow_pattern(request.user, date_from, date_to)

    # Income vs expenses — last 6 months (always anchored to today)
    income_expense_trend = _income_expense_trend(request.user, today)

    # Savings rate trend — last 12 months (always anchored to today)
    sr_trend_months, sr_avg_line_px = _savings_rate_trend(request.user, today)

    # Daily spending heatmap — only for single-month ranges
    is_single_month = (date_from.year == date_to.year and date_from.month == date_to.month)
    heatmap_weeks = _daily_heatmap(request.user, date_from.year, date_from.month) if is_single_month else None

    # Spending forecast — only for current month
    is_current_month = (preset == 'this_month')
    forecast = _spending_forecast(request.user, today.year, today.month, today) if is_current_month else None

    # Year-over-year comparison (always for current month)
    yoy_data = _yoy_comparison(request.user, today) if _has_12_months_data(request.user, today) else None

    # Expense ratio analysis for selected period
    expense_ratio = _range_expense_ratio(request.user, date_from, date_to)

    # Financial health score — always for current month (uses consistency, emergency funds, etc.)
    cur_sr_for_health = _savings_rate(
        _month_contributions(request.user, today.year, today.month),
        _month_income(request.user, today.year, today.month),
    )
    quality_for_health, _ = _spending_quality_score(request.user, today.year, today.month)
    forecast_for_health = _spending_forecast(request.user, today.year, today.month, today)
    health_score = _financial_health_score(
        request.user, today.year, today.month,
        cur_sr_for_health, quality_for_health, forecast_for_health,
    )

    # Net worth trend — last 12 months (always anchored to today)
    nw_trend_months, nw_change_pct, nw_change_arrow, nw_change_color, nw_current = (
        _net_worth_trend(request.user, today)
    )

    # Personalized recommendations
    refresh_recommendations(request.user)
    _priority_order = {Recommendation.PRIORITY_HIGH: 0, Recommendation.PRIORITY_MEDIUM: 1, Recommendation.PRIORITY_LOW: 2}
    recommendations = sorted(
        Recommendation.objects.filter(user=request.user, is_dismissed=False),
        key=lambda r: _priority_order.get(r.priority, 3),
    )

    return render(request, 'insights/insights.html', {
        'breadcrumbs': make_breadcrumbs(('Dashboard', '/dashboard/'), ('Insights', None)),
        'period_label': period_label,
        'prev_period_label': prev_period_label,
        'preset': preset,
        'date_from': date_from.isoformat(),
        'date_to': date_to.isoformat(),
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
        'heatmap_weeks': heatmap_weeks,
        'heatmap_dow_labels': _HEATMAP_DOW_LABELS,
        'recommendations': recommendations,
        'forecast': forecast,
        'yoy_data': yoy_data,
        'expense_ratio': expense_ratio,
        'health_score': health_score,
        'nw_trend_months': nw_trend_months,
        'nw_change_pct': nw_change_pct,
        'nw_change_arrow': nw_change_arrow,
        'nw_change_color': nw_change_color,
        'nw_current': nw_current,
        'has_data': has_data,
    })


def _resolve_single_period(preset_key, from_key, to_key, params, today):
    """Parse one side of the compare form. Returns (date_from, date_to, label, preset)."""
    preset = params.get(preset_key, 'this_month')
    date_from_str = params.get(from_key, '')
    date_to_str = params.get(to_key, '')
    start, end, _, _, label, _, preset = _resolve_date_range(preset, date_from_str, date_to_str, today)
    return start, end, label, preset


def _compare_periods(user, a_from, a_to, b_from, b_to):
    """Return a comparison dict between period A and period B."""
    a_spending = _range_expenses(user, a_from, a_to)
    b_spending = _range_expenses(user, b_from, b_to)
    a_income = _range_income(user, a_from, a_to)
    b_income = _range_income(user, b_from, b_to)
    a_contributions = _range_contributions(user, a_from, a_to)
    b_contributions = _range_contributions(user, b_from, b_to)
    a_savings_rate = _savings_rate(a_contributions, a_income)
    b_savings_rate = _savings_rate(b_contributions, b_income)
    a_quality, a_quality_count = _range_quality_score(user, a_from, a_to)
    b_quality, b_quality_count = _range_quality_score(user, b_from, b_to)

    def _pct_change(a, b):
        if b > 0:
            return round(float((a - b) / b * 100), 1)
        return None

    def _spending_arrow(pct):
        if pct is None:
            return None, 'secondary'
        if pct > 0:
            return 'up', 'red'
        if pct < 0:
            return 'down', 'green'
        return 'same', 'secondary'

    def _savings_arrow(a_sr, b_sr):
        if a_sr is None or b_sr is None:
            return None, None, 'secondary'
        delta = round(a_sr - b_sr, 1)
        if delta > 0:
            return delta, 'up', 'green'
        if delta < 0:
            return delta, 'down', 'red'
        return delta, 'same', 'secondary'

    def _quality_arrow(a_q, b_q):
        if a_q is None or b_q is None:
            return None, None, 'secondary'
        delta = round(float(a_q - b_q), 1)
        if delta > 0:
            return delta, 'up', 'green'
        if delta < 0:
            return delta, 'down', 'red'
        return delta, 'same', 'secondary'

    spending_pct = _pct_change(a_spending, b_spending)
    spending_arrow, spending_color = _spending_arrow(spending_pct)

    sr_delta, sr_arrow, sr_color = _savings_arrow(a_savings_rate, b_savings_rate)
    q_delta, q_arrow, q_color = _quality_arrow(a_quality, b_quality)

    # Bucket breakdown comparison
    bucket_map = {b.pk: b for b in Bucket.objects.filter(user=user)}

    def _bucket_totals(date_from, date_to):
        return {
            row['bucket_id']: row['total'] or Decimal('0')
            for row in Transaction.objects.filter(
                user=user, transaction_type='expense',
                date__gte=date_from, date__lte=date_to,
            ).values('bucket_id').annotate(total=Sum('amount'))
        }

    a_buckets = _bucket_totals(a_from, a_to)
    b_buckets = _bucket_totals(b_from, b_to)

    bucket_rows = []
    for bid in set(a_buckets) | set(b_buckets):
        a_amt = a_buckets.get(bid, Decimal('0'))
        b_amt = b_buckets.get(bid, Decimal('0'))
        if bid is None:
            name, color = 'Uncategorized', '#888888'
        else:
            bucket = bucket_map.get(bid)
            if bucket is None:
                continue
            name, color = bucket.name, bucket.color or '#888888'
        diff = a_amt - b_amt
        pct = _pct_change(a_amt, b_amt)
        arrow, arrow_color = _spending_arrow(pct)
        bucket_rows.append({
            'name': name, 'color': color,
            'a_amount': a_amt, 'b_amount': b_amt,
            'diff': diff,
            'pct_change': pct,
            'arrow': arrow, 'arrow_color': arrow_color,
        })

    bucket_rows.sort(key=lambda r: r['a_amount'], reverse=True)
    max_amt = max(
        (max(r['a_amount'], r['b_amount']) for r in bucket_rows),
        default=Decimal('0'),
    )
    for row in bucket_rows:
        row['a_bar_pct'] = int(float(row['a_amount'] / max_amt) * 100) if max_amt > 0 else 0
        row['b_bar_pct'] = int(float(row['b_amount'] / max_amt) * 100) if max_amt > 0 else 0

    return {
        'a_spending': a_spending,
        'b_spending': b_spending,
        'spending_diff': a_spending - b_spending,
        'spending_pct': spending_pct,
        'spending_arrow': spending_arrow,
        'spending_color': spending_color,
        'a_income': a_income,
        'b_income': b_income,
        'a_savings_rate': a_savings_rate,
        'b_savings_rate': b_savings_rate,
        'sr_delta': sr_delta,
        'sr_arrow': sr_arrow,
        'sr_color': sr_color,
        'a_quality': a_quality,
        'b_quality': b_quality,
        'a_quality_color': _score_color(float(a_quality) if a_quality is not None else None),
        'b_quality_color': _score_color(float(b_quality) if b_quality is not None else None),
        'q_delta': q_delta,
        'q_arrow': q_arrow,
        'q_color': q_color,
        'bucket_rows': bucket_rows,
    }


@login_required
def compare(request):
    today = datetime.date.today()
    params = request.GET

    a_from, a_to, a_label, a_preset = _resolve_single_period(
        'preset_a', 'date_from_a', 'date_to_a', params, today,
    )
    b_from, b_to, b_label, b_preset = _resolve_single_period(
        'preset_b', 'date_from_b', 'date_to_b', params, today,
    )

    comparison = _compare_periods(request.user, a_from, a_to, b_from, b_to)

    return render(request, 'insights/compare.html', {
        'a_label': a_label,
        'b_label': b_label,
        'a_preset': a_preset,
        'b_preset': b_preset,
        'a_from': a_from.isoformat(),
        'a_to': a_to.isoformat(),
        'b_from': b_from.isoformat(),
        'b_to': b_to.isoformat(),
        'comparison': comparison,
    })


@login_required
def dismiss_recommendation(request, rec_id):
    if request.method == 'POST':
        rec = get_object_or_404(Recommendation, pk=rec_id, user=request.user)
        rec.is_dismissed = True
        rec.save()
        next_url = request.POST.get('next', '')
        if next_url == '/dashboard/':
            return redirect('dashboard')
    return redirect('insights')


@login_required
def annual_report(request, year):
    today = datetime.date.today()
    if year < 2000 or year > today.year:
        raise Http404

    start_date = datetime.date(year, 1, 1)
    end_date = datetime.date(year, 12, 31)

    # Annual totals
    annual_income = _range_income(request.user, start_date, end_date)
    annual_expenses = _range_expenses(request.user, start_date, end_date)
    annual_contributions = _range_contributions(request.user, start_date, end_date)
    net_savings = annual_income - annual_expenses
    avg_monthly_spending = (annual_expenses / Decimal('12')).quantize(Decimal('0.01'))

    if annual_income > 0:
        annual_savings_rate = round(float(annual_contributions / annual_income * 100), 1)
        annual_savings_color = 'green' if annual_savings_rate >= 20 else ('gold' if annual_savings_rate >= 10 else 'red')
    else:
        annual_savings_rate = None
        annual_savings_color = 'secondary'

    net_color = 'green' if net_savings > 0 else ('red' if net_savings < 0 else 'secondary')

    # Monthly breakdown table
    monthly_rows = []
    for month in range(1, 13):
        m_income = _month_income(request.user, year, month)
        m_expenses = _month_expenses(request.user, year, month)
        m_contributions = _month_contributions(request.user, year, month)
        m_net = m_income - m_expenses
        m_sr = _savings_rate(m_contributions, m_income)
        is_future = year == today.year and month > today.month
        monthly_rows.append({
            'month': month,
            'month_label': datetime.date(year, month, 1).strftime('%B'),
            'income': m_income,
            'expenses': m_expenses,
            'net': m_net,
            'savings_rate': m_sr,
            'net_positive': m_net >= 0,
            'is_future': is_future,
            'has_data': m_income > 0 or m_expenses > 0,
        })

    # Best/worst months (exclude future and months with no data)
    active_months = [m for m in monthly_rows if not m['is_future'] and m['has_data']]
    best_month = max(active_months, key=lambda m: m['net']) if active_months else None
    worst_month = min(active_months, key=lambda m: m['net']) if active_months else None
    highest_spend_month = max(active_months, key=lambda m: m['expenses']) if active_months else None
    spend_months = [m for m in active_months if m['expenses'] > 0]
    lowest_spend_month = min(spend_months, key=lambda m: m['expenses']) if spend_months else None

    # Annual spending quality score
    quality_result = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        date__year=year,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))
    annual_quality_score = (
        round(Decimal(str(quality_result['avg'])), 1) if quality_result['count'] else None
    )
    annual_quality_count = quality_result['count']
    annual_quality_color = _score_color(
        float(annual_quality_score) if annual_quality_score is not None else None
    )

    # Annual bucket/category breakdown
    annual_buckets = _range_bucket_breakdown(request.user, start_date, end_date)

    # Top merchants for the year
    annual_merchants = _range_top_merchants(request.user, start_date, end_date)

    # Expense ratio analysis for the year
    expense_ratio = _range_expense_ratio(request.user, start_date, end_date)

    # Goals achieved in this year (reached 100% milestone during the year)
    achieved_goal_ids = SavingsMilestone.objects.filter(
        goal__user=request.user,
        percentage=100,
        reached_at__year=year,
    ).values_list('goal_id', flat=True)
    achieved_goals = list(SavingsGoal.objects.filter(pk__in=achieved_goal_ids))

    # Available years for navigation (based on transaction history)
    date_bounds = Transaction.objects.filter(user=request.user).aggregate(
        min_date=Min('date'), max_date=Max('date'),
    )
    if date_bounds['min_date']:
        first_year = date_bounds['min_date'].year
        last_year = min(date_bounds['max_date'].year, today.year)
        available_years = list(range(last_year, first_year - 1, -1))
    else:
        available_years = [today.year]

    prev_year = year - 1 if year - 1 >= (available_years[-1] if available_years else year) else None
    next_year = year + 1 if year + 1 <= today.year else None

    is_print = request.GET.get('print') == '1'

    return render(request, 'insights/annual.html', {
        'year': year,
        'prev_year': prev_year,
        'next_year': next_year,
        'available_years': available_years,
        'annual_income': annual_income,
        'annual_expenses': annual_expenses,
        'annual_contributions': annual_contributions,
        'net_savings': net_savings,
        'net_color': net_color,
        'avg_monthly_spending': avg_monthly_spending,
        'annual_savings_rate': annual_savings_rate,
        'annual_savings_color': annual_savings_color,
        'monthly_rows': monthly_rows,
        'best_month': best_month,
        'worst_month': worst_month,
        'highest_spend_month': highest_spend_month,
        'lowest_spend_month': lowest_spend_month,
        'annual_quality_score': annual_quality_score,
        'annual_quality_count': annual_quality_count,
        'annual_quality_color': annual_quality_color,
        'annual_buckets': annual_buckets,
        'annual_merchants': annual_merchants,
        'expense_ratio': expense_ratio,
        'achieved_goals': achieved_goals,
        'is_print': is_print,
    })
