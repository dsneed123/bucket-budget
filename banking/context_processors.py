import datetime
import math
from decimal import Decimal

from django.db.models import Avg, Count

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

    return {
        'net_worth': net_worth_value,
        'unscored_count': unscored_count,
        'sidebar_quality_score': avg,
        'sidebar_quality_color': color,
        'sidebar_quality_dashoffset': dashoffset,
        'sidebar_quality_circumference': _CIRCUMFERENCE,
    }
