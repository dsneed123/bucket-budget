import datetime
from decimal import Decimal

from django.db.models import Avg, Count, Sum

from buckets.models import Bucket
from savings.models import SavingsContribution
from transactions.models import Transaction

from .models import Recommendation

_VENDOR_HIGH_SPEND_PCT = Decimal('0.30')  # vendor > 30% of total → flag
_QUALITY_DROP_THRESHOLD = Decimal('1.5')  # score drop of 1.5+ points → flag
_SAVINGS_IMPROVEMENT_THRESHOLD = 2.0      # rate improved 2+ pct points → congrats


def _prev_month(year, month, n=1):
    month -= n
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def _month_expenses(user, year, month):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=year, date__month=month,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _bucket_month_expenses(user, bucket_id, year, month):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            bucket_id=bucket_id, date__year=year, date__month=month,
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


def _quality_score(user, year, month):
    result = Transaction.objects.filter(
        user=user, transaction_type='expense',
        date__year=year, date__month=month,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))
    if not result['count']:
        return None
    return round(Decimal(str(result['avg'])), 1)


def _impulse_count(user, year, month):
    return Transaction.objects.filter(
        user=user, transaction_type='expense',
        date__year=year, date__month=month,
        necessity_score__lte=3,
    ).count()


def _over_budget_buckets(user, today):
    recs = []
    active_buckets = list(
        Bucket.objects.filter(user=user, is_active=True, is_uncategorized=False)
    )
    for bucket in active_buckets:
        if not bucket.monthly_allocation or bucket.monthly_allocation <= 0:
            continue
        over_count = 0
        for i in range(1, 4):
            y, m = _prev_month(today.year, today.month, i)
            spent = _bucket_month_expenses(user, bucket.pk, y, m)
            if spent > bucket.monthly_allocation:
                over_count += 1
        if over_count >= 3:
            recs.append(Recommendation(
                user=user,
                message=(
                    f'Your "{bucket.name}" bucket has exceeded its allocation for '
                    f'3 months in a row. Consider adjusting the allocation or reducing spending.'
                ),
                category=Recommendation.CATEGORY_BUDGET,
                priority=Recommendation.PRIORITY_HIGH,
            ))
    return recs


def _spending_quality_recs(user, today):
    recs = []
    this_y, this_m = today.year, today.month
    prev_y, prev_m = _prev_month(this_y, this_m)

    cur_score = _quality_score(user, this_y, this_m)
    prev_score = _quality_score(user, prev_y, prev_m)

    if cur_score is not None and prev_score is not None:
        if prev_score - cur_score >= _QUALITY_DROP_THRESHOLD:
            impulses = _impulse_count(user, this_y, this_m)
            recs.append(Recommendation(
                user=user,
                message=(
                    f'More impulse purchases this month — your spending quality score dropped '
                    f'from {prev_score}/10 to {cur_score}/10'
                    + (f', with {impulses} low-necessity transaction{"s" if impulses != 1 else ""}.' if impulses else '.')
                ),
                category=Recommendation.CATEGORY_QUALITY,
                priority=Recommendation.PRIORITY_MEDIUM,
            ))
    return recs


def _savings_rate_recs(user, today):
    recs = []
    this_y, this_m = today.year, today.month
    prev_y, prev_m = _prev_month(this_y, this_m)

    cur_income = _month_income(user, this_y, this_m)
    cur_contributions = _month_contributions(user, this_y, this_m)
    cur_rate = _savings_rate(cur_contributions, cur_income)

    prev_income = _month_income(user, prev_y, prev_m)
    prev_contributions = _month_contributions(user, prev_y, prev_m)
    prev_rate = _savings_rate(prev_contributions, prev_income)

    if cur_rate is not None and prev_rate is not None:
        improvement = cur_rate - prev_rate
        if improvement >= _SAVINGS_IMPROVEMENT_THRESHOLD:
            recs.append(Recommendation(
                user=user,
                message=(
                    f'Great job! You saved {cur_rate}% of your income this month, '
                    f'up {round(improvement, 1)}% from last month ({prev_rate}%).'
                ),
                category=Recommendation.CATEGORY_SAVINGS,
                priority=Recommendation.PRIORITY_LOW,
            ))
    return recs


def _vendor_recs(user, today):
    recs = []
    this_y, this_m = today.year, today.month

    total = _month_expenses(user, this_y, this_m)
    if total <= 0:
        return recs

    top = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__year=this_y, date__month=this_m,
        )
        .exclude(vendor='')
        .values('vendor')
        .annotate(total=Sum('amount'))
        .order_by('-total')
        .first()
    )
    if not top:
        return recs

    vendor_total = top['total'] or Decimal('0')
    if vendor_total / total >= _VENDOR_HIGH_SPEND_PCT:
        pct = round(float(vendor_total / total * 100), 1)
        recs.append(Recommendation(
            user=user,
            message=(
                f'You spent {pct}% of your monthly expenses at {top["vendor"]}. '
                f'Consider exploring alternatives to diversify your spending.'
            ),
            category=Recommendation.CATEGORY_VENDOR,
            priority=Recommendation.PRIORITY_MEDIUM,
        ))
    return recs


def refresh_recommendations(user):
    today = datetime.date.today()

    Recommendation.objects.filter(user=user, is_dismissed=False).delete()

    new_recs = []
    new_recs.extend(_over_budget_buckets(user, today))
    new_recs.extend(_spending_quality_recs(user, today))
    new_recs.extend(_savings_rate_recs(user, today))
    new_recs.extend(_vendor_recs(user, today))

    if new_recs:
        Recommendation.objects.bulk_create(new_recs)
