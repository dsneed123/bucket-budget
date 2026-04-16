import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.urls import reverse

from buckets.models import Bucket
from transactions.models import Transaction


@login_required
def budget_overview(request, year=None, month=None):
    today = datetime.date.today()

    if year is None or month is None:
        year, month = today.year, today.month

    if not (1 <= month <= 12 and year >= 2000):
        year, month = today.year, today.month

    is_current_month = (year == today.year and month == today.month)

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1

    prev_url = reverse('budget_overview_month', kwargs={'year': prev_year, 'month': prev_month})
    next_url = reverse('budget_overview_month', kwargs={'year': next_year, 'month': next_month})
    current_url = reverse('budget_overview')

    monthly_income = request.user.monthly_income or Decimal('0')

    buckets = Bucket.objects.filter(
        user=request.user, is_active=True, is_uncategorized=False
    ).order_by('sort_order', 'name')

    total_allocated = buckets.aggregate(s=Sum('monthly_allocation'))['s'] or Decimal('0')
    unallocated = monthly_income - total_allocated

    month_expenses = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        date__year=year,
        date__month=month,
    )
    total_spent = month_expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0')

    remaining_budget = monthly_income - total_spent

    bucket_data = []
    for bucket in buckets:
        spent = month_expenses.filter(bucket=bucket).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        remaining = bucket.monthly_allocation - spent
        if bucket.monthly_allocation > 0:
            pct = min(int((spent / bucket.monthly_allocation) * 100), 100)
        else:
            pct = 0
        bucket_data.append({
            'bucket': bucket,
            'spent': spent,
            'remaining': remaining,
            'pct': pct,
            'over': spent > bucket.monthly_allocation,
        })

    bucket_data.sort(key=lambda x: x['pct'], reverse=True)

    total_remaining = total_allocated - total_spent
    if total_allocated > 0:
        total_pct = min(int((total_spent / total_allocated) * 100), 100)
    else:
        total_pct = 0

    selected_date = datetime.date(year, month, 1)

    return render(request, 'budget/budget_overview.html', {
        'current_month': selected_date.strftime('%B %Y'),
        'is_current_month': is_current_month,
        'prev_url': prev_url,
        'next_url': next_url,
        'current_url': current_url,
        'monthly_income': monthly_income,
        'total_allocated': total_allocated,
        'unallocated': unallocated,
        'total_spent': total_spent,
        'remaining_budget': remaining_budget,
        'bucket_data': bucket_data,
        'total_remaining': total_remaining,
        'total_pct': total_pct,
    })
