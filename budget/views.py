import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render

from buckets.models import Bucket
from transactions.models import Transaction


@login_required
def budget_overview(request):
    today = datetime.date.today()

    monthly_income = request.user.monthly_income or Decimal('0')

    buckets = Bucket.objects.filter(
        user=request.user, is_active=True, is_uncategorized=False
    ).order_by('sort_order', 'name')

    total_allocated = buckets.aggregate(s=Sum('monthly_allocation'))['s'] or Decimal('0')
    unallocated = monthly_income - total_allocated

    month_expenses = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        date__year=today.year,
        date__month=today.month,
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

    return render(request, 'budget/budget_overview.html', {
        'current_month': today.strftime('%B %Y'),
        'monthly_income': monthly_income,
        'total_allocated': total_allocated,
        'unallocated': unallocated,
        'total_spent': total_spent,
        'remaining_budget': remaining_budget,
        'bucket_data': bucket_data,
    })
