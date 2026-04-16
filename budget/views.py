import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse

from buckets.models import Bucket
from budget.models import BudgetSummary
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
        bar_max = max(bucket.monthly_allocation, spent, Decimal('1'))
        bucket_data.append({
            'bucket': bucket,
            'spent': spent,
            'remaining': remaining,
            'pct': pct,
            'over': spent > bucket.monthly_allocation,
            'bar_max': bar_max,
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
        'alloc_saved': request.GET.get('saved') == '1',
    })


@login_required
def save_allocations(request):
    if request.method != 'POST':
        return redirect('budget_overview')

    buckets = list(
        Bucket.objects.filter(user=request.user, is_active=True, is_uncategorized=False)
    )

    allocations = {}
    has_errors = False

    for bucket in buckets:
        raw = request.POST.get(f'allocation_{bucket.pk}', '').strip()
        if raw == '':
            raw = '0'
        try:
            val = Decimal(raw)
            if val < 0:
                has_errors = True
            else:
                allocations[bucket.pk] = val
        except Exception:
            has_errors = True

    if not has_errors:
        for bucket in buckets:
            if bucket.pk in allocations:
                bucket.monthly_allocation = allocations[bucket.pk]
        Bucket.objects.bulk_update(buckets, ['monthly_allocation'])

    return redirect(reverse('budget_overview') + '?saved=1')


@login_required
def budget_history(request):
    summaries = list(BudgetSummary.objects.filter(user=request.user))

    def _trend(current, previous):
        if current is None or previous is None:
            return None
        if current > previous:
            return 'up'
        if current < previous:
            return 'down'
        return 'flat'

    history = []
    for i, summary in enumerate(summaries):
        prev = summaries[i + 1] if i + 1 < len(summaries) else None
        history.append({
            'summary': summary,
            'detail_url': reverse(
                'budget_overview_month',
                kwargs={'year': summary.year, 'month': summary.month},
            ),
            'trends': {
                'income': _trend(summary.income, prev.income) if prev else None,
                'spent': _trend(summary.total_spent, prev.total_spent) if prev else None,
                'saved': _trend(summary.total_saved, prev.total_saved) if prev else None,
                'surplus': _trend(summary.surplus_deficit, prev.surplus_deficit) if prev else None,
                'necessity': _trend(summary.necessity_avg, prev.necessity_avg) if prev else None,
            },
        })

    return render(request, 'budget/budget_history.html', {
        'history': history,
    })
