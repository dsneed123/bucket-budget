from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import redirect, render

from transactions.models import Transaction


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
