from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.shortcuts import render

from transactions.models import Transaction


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


def _score_color(score):
    if score is None:
        return 'secondary'
    if score >= 7:
        return 'green'
    if score >= 4:
        return 'gold'
    return 'red'


@login_required
def rankings(request):
    today = date.today()
    this_year, this_month = today.year, today.month

    if this_month == 1:
        last_year, last_month = this_year - 1, 12
    else:
        last_year, last_month = this_year, this_month - 1

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
        .order_by('-avg_score')
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
        'this_month_label': today.strftime('%B %Y'),
        'last_month_label': date(last_year, last_month, 1).strftime('%B %Y'),
    })
