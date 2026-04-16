from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import ExtractWeekDay
from django.shortcuts import redirect, render

from transactions.models import Transaction

from .models import ScoreStreak


def _get_regret_stats(user, year, month):
    """Return regret rate overall and per bucket for the given month."""
    base_qs = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
    )
    total = base_qs.count()
    if not total:
        return None, []

    regret_count = base_qs.filter(regret=True).count()
    overall_rate = round(regret_count / total * 100, 1)

    bucket_data = (
        base_qs.filter(bucket__isnull=False)
        .values('bucket__id', 'bucket__name', 'bucket__icon', 'bucket__color')
        .annotate(
            total_count=Count('id'),
            regret_count=Count('id', filter=Q(regret=True)),
        )
        .order_by('-regret_count')
    )

    bucket_rows = []
    for row in bucket_data:
        if row['total_count']:
            rate = round(row['regret_count'] / row['total_count'] * 100, 1)
            bucket_rows.append({
                'name': row['bucket__name'],
                'icon': row['bucket__icon'] or '',
                'color': row['bucket__color'] or '#0984e3',
                'regret_count': row['regret_count'],
                'total_count': row['total_count'],
                'rate': rate,
            })

    return overall_rate, bucket_rows


def _get_score_histogram(user, year, month):
    """Return transaction count per necessity score (1-10) for the given month."""
    qs = (
        Transaction.objects.filter(
            user=user,
            transaction_type='expense',
            date__year=year,
            date__month=month,
            necessity_score__isnull=False,
        )
        .values('necessity_score')
        .annotate(count=Count('id'))
    )
    counts = {row['necessity_score']: row['count'] for row in qs}
    max_count = max(counts.values(), default=0)
    if max_count == 0:
        return []

    bins = []
    for score in range(1, 11):
        count = counts.get(score, 0)
        bar_height = round(count / max_count * 100)
        if score >= 7:
            color = 'green'
        elif score >= 4:
            color = 'gold'
        else:
            color = 'red'
        bins.append({
            'score': score,
            'count': count,
            'bar_height': bar_height,
            'color': color,
        })
    return bins


def _get_necessity_breakdown(user, year, month):
    """Return spending breakdown by necessity category for the given month."""
    base_qs = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
    )

    def _sum(qs):
        return qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    need_amount = _sum(base_qs.filter(necessity_score__gte=7))
    useful_amount = _sum(base_qs.filter(necessity_score__gte=4, necessity_score__lte=6))
    want_amount = _sum(base_qs.filter(necessity_score__gte=1, necessity_score__lte=3))
    unscored_amount = _sum(base_qs.filter(necessity_score__isnull=True))

    grand_total = need_amount + useful_amount + want_amount + unscored_amount
    if grand_total == 0:
        return None

    def _pct(val):
        return round(float(val / grand_total * 100), 1)

    need_pct = _pct(need_amount)
    useful_pct = _pct(useful_amount)
    want_pct = _pct(want_amount)
    unscored_pct = round(100 - need_pct - useful_pct - want_pct, 1)

    # Cumulative stop positions for conic-gradient
    need_end = need_pct
    useful_end = round(need_end + useful_pct, 1)
    want_end = round(useful_end + want_pct, 1)

    return {
        'grand_total': grand_total,
        'need': need_amount,
        'useful': useful_amount,
        'want': want_amount,
        'unscored': unscored_amount,
        'need_pct': need_pct,
        'useful_pct': useful_pct,
        'want_pct': want_pct,
        'unscored_pct': unscored_pct,
        'need_end': need_end,
        'useful_end': useful_end,
        'want_end': want_end,
    }


def _get_spending_quality_score(user, year, month):
    """Return (avg_score, count) for expense transactions in given month with necessity_score set."""
    qs = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
        necessity_score__isnull=False,
    )
    result = qs.aggregate(avg=Avg('necessity_score'), count=Count('id'))
    if result['count'] == 0:
        return None, 0
    return round(Decimal(str(result['avg'])), 1), result['count']


def _get_impulse_purchases(user, year, month):
    """Return (purchases_list, total) for the 10 lowest-scored expenses (1-3) this month."""
    base_qs = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
        necessity_score__gte=1,
        necessity_score__lte=3,
    )
    total = base_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    purchases = list(
        base_qs.order_by('necessity_score', '-amount')
        .values('date', 'description', 'vendor', 'amount', 'necessity_score')[:10]
    )
    return purchases, total


def _get_essential_purchases(user, year, month):
    """Return (purchases_list, total) for the 10 highest-scored expenses (8-10) this month."""
    base_qs = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
        necessity_score__gte=8,
        necessity_score__lte=10,
    )
    total = base_qs.aggregate(total=Sum('amount'))['total'] or Decimal('0')
    purchases = list(
        base_qs.order_by('-necessity_score', '-amount')
        .values('date', 'description', 'vendor', 'amount', 'necessity_score')[:10]
    )
    return purchases, total


def _score_color(score):
    if score is None:
        return 'secondary'
    if score >= 7:
        return 'green'
    if score >= 4:
        return 'gold'
    return 'red'


def _get_vendor_averages(user, year, month):
    """Return vendors sorted by avg necessity score (lowest first) for the given month."""
    vendor_stats = (
        Transaction.objects.filter(
            user=user,
            transaction_type='expense',
            date__year=year,
            date__month=month,
            necessity_score__isnull=False,
        )
        .exclude(vendor='')
        .values('vendor')
        .annotate(avg_score=Avg('necessity_score'), tx_count=Count('id'), total_spent=Sum('amount'))
        .order_by('avg_score')
    )

    rows = []
    for row in vendor_stats:
        score = round(Decimal(str(row['avg_score'])), 1)
        rows.append({
            'vendor': row['vendor'],
            'score': score,
            'score_color': _score_color(score),
            'tx_count': row['tx_count'],
            'total_spent': row['total_spent'],
        })
    return rows


def _get_daily_spending_quality(user):
    """Return day-of-week spending quality stats (Mon–Sun), using all scored expense history."""
    # Django ExtractWeekDay: 1=Sunday, 2=Monday, ..., 7=Saturday
    day_stats = (
        Transaction.objects.filter(
            user=user,
            transaction_type='expense',
            necessity_score__isnull=False,
        )
        .annotate(weekday=ExtractWeekDay('date'))
        .values('weekday')
        .annotate(avg_score=Avg('necessity_score'), tx_count=Count('id'), total_spent=Sum('amount'))
    )

    day_names = {1: 'Sun', 2: 'Mon', 3: 'Tue', 4: 'Wed', 5: 'Thu', 6: 'Fri', 7: 'Sat'}
    day_order = [2, 3, 4, 5, 6, 7, 1]  # Mon first

    rows_by_weekday = {}
    for row in day_stats:
        score = round(Decimal(str(row['avg_score'])), 1)
        if score < 4:
            insight = 'impulse day!'
        elif score < 7:
            insight = 'mixed spending'
        else:
            insight = 'strong day'
        rows_by_weekday[row['weekday']] = {
            'day': day_names[row['weekday']],
            'score': score,
            'score_color': _score_color(score),
            'tx_count': row['tx_count'],
            'total_spent': row['total_spent'],
            'insight': insight,
            'bar_height': round(float(score) / 10 * 100),
        }

    rows = []
    for wd in day_order:
        if wd in rows_by_weekday:
            rows.append(rows_by_weekday[wd])
        else:
            rows.append({
                'day': day_names[wd],
                'score': None,
                'score_color': 'secondary',
                'tx_count': 0,
                'total_spent': Decimal('0'),
                'insight': '',
                'bar_height': 0,
            })

    # Find the worst day (lowest score with data) for the headline insight
    scored = [r for r in rows if r['score'] is not None]
    worst_day = min(scored, key=lambda r: r['score']) if scored else None

    return rows, worst_day


def _compute_score_streak(user, today):
    """Return the current scoring streak (consecutive days where all expenses are scored).

    A day counts toward the streak only if it has at least one expense and every
    expense has a necessity_score.  Days with no expenses are skipped (neither
    counted nor broken).  The streak includes today only if today has no unscored
    expenses.
    """
    lookback_start = today - timedelta(days=365)

    daily_stats = (
        Transaction.objects.filter(
            user=user,
            transaction_type='expense',
            date__gte=lookback_start,
            date__lte=today,
        )
        .values('date')
        .annotate(
            total=Count('id'),
            unscored=Count('id', filter=Q(necessity_score__isnull=True)),
        )
    )

    daily_map = {row['date']: row['unscored'] for row in daily_stats}

    # If today has unscored transactions, today can't contribute to the streak.
    if daily_map.get(today, 0) > 0:
        start_date = today - timedelta(days=1)
    else:
        start_date = today

    streak = 0
    current_date = start_date
    days_checked = 0
    while days_checked < 365:
        unscored = daily_map.get(current_date)
        if unscored is None:
            # No expenses this day — skip without breaking the streak
            current_date -= timedelta(days=1)
            days_checked += 1
            continue
        if unscored > 0:
            break
        streak += 1
        current_date -= timedelta(days=1)
        days_checked += 1

    return streak


def _build_comparison_arrow(current, last, higher_is_better=True):
    """Return (arrow_direction, arrow_color) for month-over-month metric comparison.

    arrow_direction: 'up', 'down', 'same', or None (missing data).
    arrow_color: 'green', 'red', or 'secondary'.
    """
    if current is None or last is None:
        return None, 'secondary'
    if current > last:
        return 'up', 'green' if higher_is_better else 'red'
    if current < last:
        return 'down', 'red' if higher_is_better else 'green'
    return 'same', 'secondary'


def _get_score_trend(user, today):
    """Return last 6 months of avg necessity scores for the trend bar chart, oldest first."""
    months = []
    year, month = today.year, today.month
    for _ in range(6):
        score, _ = _get_spending_quality_score(user, year, month)
        months.append({
            'label': date(year, month, 1).strftime('%b'),
            'score': score,
            'color': _score_color(score),
            'bar_height': round(float(score) / 10 * 100) if score is not None else 0,
            'has_data': score is not None,
        })
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    months.reverse()
    return months


@login_required
def rankings(request):
    today = date.today()
    this_year, this_month = today.year, today.month

    if this_month == 1:
        last_year, last_month = this_year - 1, 12
    else:
        last_year, last_month = this_year, this_month - 1

    breakdown = _get_necessity_breakdown(request.user, this_year, this_month)
    last_breakdown = _get_necessity_breakdown(request.user, last_year, last_month)
    impulse_purchases, impulse_total = _get_impulse_purchases(request.user, this_year, this_month)
    essential_purchases, essential_total = _get_essential_purchases(request.user, this_year, this_month)
    current_score, current_count = _get_spending_quality_score(request.user, this_year, this_month)
    last_score, last_count = _get_spending_quality_score(request.user, last_year, last_month)

    if current_score is not None and last_score is not None:
        if current_score > last_score:
            trend = 'up'
        elif current_score < last_score:
            trend = 'down'
        else:
            trend = 'same'
    else:
        trend = None

    score_trend = _get_score_trend(request.user, today)

    bucket_stats = (
        Transaction.objects.filter(
            user=request.user,
            transaction_type='expense',
            date__year=this_year,
            date__month=this_month,
            bucket__isnull=False,
            necessity_score__isnull=False,
        )
        .values('bucket__id', 'bucket__name', 'bucket__icon', 'bucket__color')
        .annotate(avg_score=Avg('necessity_score'), tx_count=Count('id'), total_spent=Sum('amount'))
        .order_by('avg_score')
    )

    bucket_rows = []
    for row in bucket_stats:
        score = round(Decimal(str(row['avg_score'])), 1)
        bucket_rows.append({
            'name': row['bucket__name'],
            'icon': row['bucket__icon'] or '',
            'color': row['bucket__color'] or '#0984e3',
            'score': score,
            'score_color': _score_color(score),
            'tx_count': row['tx_count'],
            'total_spent': row['total_spent'],
        })

    score_histogram = _get_score_histogram(request.user, this_year, this_month)
    vendor_rows = _get_vendor_averages(request.user, this_year, this_month)
    daily_quality, worst_day = _get_daily_spending_quality(request.user)

    current_streak = _compute_score_streak(request.user, today)
    streak_obj, _ = ScoreStreak.objects.get_or_create(user=request.user)
    if current_streak > streak_obj.best_streak:
        streak_obj.best_streak = current_streak
        streak_obj.save(update_fields=['best_streak'])
    best_streak = streak_obj.best_streak

    unscored_count = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        necessity_score__isnull=True,
    ).count()

    regret_to_review = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        regret__isnull=True,
        date__lte=today - timedelta(days=7),
    ).count()

    regret_rate, regret_bucket_rows = _get_regret_stats(request.user, this_year, this_month)

    # Build month-over-month comparison metrics
    score_arrow, score_arrow_color = _build_comparison_arrow(
        float(current_score) if current_score is not None else None,
        float(last_score) if last_score is not None else None,
        higher_is_better=True,
    )
    count_arrow, count_arrow_color = _build_comparison_arrow(
        current_count, last_count, higher_is_better=True,
    )
    need_arrow, need_arrow_color = _build_comparison_arrow(
        float(breakdown['need']) if breakdown else None,
        float(last_breakdown['need']) if last_breakdown else None,
        higher_is_better=True,
    )
    useful_arrow, _ = _build_comparison_arrow(
        float(breakdown['useful']) if breakdown else None,
        float(last_breakdown['useful']) if last_breakdown else None,
        higher_is_better=True,
    )
    want_arrow, want_arrow_color = _build_comparison_arrow(
        float(breakdown['want']) if breakdown else None,
        float(last_breakdown['want']) if last_breakdown else None,
        higher_is_better=False,
    )

    monthly_comparison = {
        'avg_score': {
            'this': current_score,
            'last': last_score,
            'arrow': score_arrow,
            'arrow_color': score_arrow_color,
        },
        'need': {
            'this': breakdown['need'] if breakdown else None,
            'last': last_breakdown['need'] if last_breakdown else None,
            'arrow': need_arrow,
            'arrow_color': need_arrow_color,
        },
        'useful': {
            'this': breakdown['useful'] if breakdown else None,
            'last': last_breakdown['useful'] if last_breakdown else None,
            'arrow': useful_arrow,
            'arrow_color': 'secondary',
        },
        'want': {
            'this': breakdown['want'] if breakdown else None,
            'last': last_breakdown['want'] if last_breakdown else None,
            'arrow': want_arrow,
            'arrow_color': want_arrow_color,
        },
        'total_scored': {
            'this': current_count,
            'last': last_count,
            'arrow': count_arrow,
            'arrow_color': count_arrow_color,
        },
    }

    return render(request, 'rankings/rankings.html', {
        'current_score': current_score,
        'current_count': current_count,
        'current_color': _score_color(current_score),
        'last_score': last_score,
        'last_count': last_count,
        'last_color': _score_color(last_score),
        'trend': trend,
        'bucket_rows': bucket_rows,
        'breakdown': breakdown,
        'impulse_purchases': impulse_purchases,
        'impulse_total': impulse_total,
        'essential_purchases': essential_purchases,
        'essential_total': essential_total,
        'this_month_label': today.strftime('%B %Y'),
        'last_month_label': date(last_year, last_month, 1).strftime('%B %Y'),
        'score_trend': score_trend,
        'vendor_rows': vendor_rows,
        'daily_quality': daily_quality,
        'worst_day': worst_day,
        'current_streak': current_streak,
        'best_streak': best_streak,
        'unscored_count': unscored_count,
        'regret_rate': regret_rate,
        'regret_bucket_rows': regret_bucket_rows,
        'regret_to_review': regret_to_review,
        'score_histogram': score_histogram,
        'monthly_comparison': monthly_comparison,
        'last_breakdown': last_breakdown,
    })


@login_required
def rankings_review(request):
    if request.method == 'POST':
        tx_id = request.POST.get('transaction_id')
        # Quick-score buttons submit name="score" which overrides the number input
        # (button value is appended last in form data, so get() returns it)
        score_values = request.POST.getlist('score')
        # Use the last non-empty value (button wins over empty input; input wins if no button)
        score_str = None
        for s in reversed(score_values):
            if s.strip():
                score_str = s.strip()
                break

        if tx_id and score_str:
            try:
                score_int = int(score_str)
                if 1 <= score_int <= 10:
                    Transaction.objects.filter(
                        id=tx_id,
                        user=request.user,
                        transaction_type='expense',
                    ).update(necessity_score=score_int)
                    messages.success(request, 'Score saved.')
                else:
                    messages.error(request, 'Score must be between 1 and 10.')
            except (ValueError, TypeError):
                messages.error(request, 'Invalid score value.')
        return redirect('rankings_review')

    unscored = (
        Transaction.objects.filter(
            user=request.user,
            transaction_type='expense',
            necessity_score__isnull=True,
        )
        .select_related('bucket')
        .order_by('-date', '-id')
    )

    return render(request, 'rankings/review.html', {
        'transactions': unscored,
        'unscored_count': unscored.count(),
    })


@login_required
def rankings_review_regret(request):
    today = date.today()
    cutoff = today - timedelta(days=7)

    if request.method == 'POST':
        tx_id = request.POST.get('transaction_id')
        action = request.POST.get('action')
        if tx_id and action in ('regret', 'no_regret'):
            regret_value = action == 'regret'
            Transaction.objects.filter(
                id=tx_id,
                user=request.user,
                transaction_type='expense',
            ).update(regret=regret_value)
            messages.success(request, 'Response saved.')
        return redirect('rankings_review_regret')

    to_review = (
        Transaction.objects.filter(
            user=request.user,
            transaction_type='expense',
            regret__isnull=True,
            date__lte=cutoff,
        )
        .select_related('bucket')
        .order_by('-date', '-id')
    )

    return render(request, 'rankings/review_regret.html', {
        'transactions': to_review,
        'review_count': to_review.count(),
        'cutoff_date': cutoff,
    })
