import csv
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Sum
from django.http import StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from accounts.utils import get_current_fiscal_month, get_fiscal_month_range, get_user_fiscal_start
from buckets.models import Bucket
from budget.models import BudgetSummary, MonthlyBudgetAllocation
from transactions.models import Transaction


@login_required
def budget_overview(request, year=None, month=None):
    today = datetime.date.today()
    fiscal_start = get_user_fiscal_start(request.user)

    if year is None or month is None:
        year, month = get_current_fiscal_month(today, fiscal_start)

    if not (1 <= month <= 12 and year >= 2000):
        year, month = get_current_fiscal_month(today, fiscal_start)

    fstart, fend = get_fiscal_month_range(year, month, fiscal_start)
    is_current_month = fstart <= today <= fend

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
        date__gte=fstart,
        date__lte=fend,
    )
    total_spent = month_expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0')

    remaining_budget = monthly_income - total_spent

    _bucket_spending = {
        row['bucket_id']: row['s']
        for row in month_expenses.values('bucket_id').annotate(s=Sum('amount'))
    }
    bucket_data = []
    for bucket in buckets:
        spent = _bucket_spending.get(bucket.pk) or Decimal('0')
        rollover = bucket.rollover_amount(year, month) if bucket.rollover else Decimal('0')
        effective_allocation = bucket.monthly_allocation + rollover
        remaining = effective_allocation - spent
        if effective_allocation > 0:
            pct = min(int((spent / effective_allocation) * 100), 100)
        else:
            pct = 0
        bar_max = max(effective_allocation, spent, Decimal('1'))
        bucket_data.append({
            'bucket': bucket,
            'spent': spent,
            'rollover_amount': rollover,
            'effective_allocation': effective_allocation,
            'remaining': remaining,
            'pct': pct,
            'over': spent > effective_allocation,
            'bar_max': bar_max,
        })

    bucket_data.sort(key=lambda x: x['pct'], reverse=True)

    zero_based = request.user.zero_based_budgeting
    every_dollar_assigned = zero_based and monthly_income > 0 and unallocated == Decimal('0')

    alerts = []
    if monthly_income > 0 and total_allocated > monthly_income:
        alerts.append({
            'level': 'error',
            'message': f'Total allocations ({total_allocated:,.2f}) exceed your monthly income. Reduce bucket allocations to balance your budget.',
        })
    if zero_based and monthly_income > 0 and unallocated != Decimal('0'):
        if unallocated > 0:
            alerts.append({
                'level': 'warning',
                'message': f'Zero-based budgeting: {unallocated:,.2f} unallocated. Assign every dollar to a bucket to complete your budget.',
            })
        else:
            alerts.append({
                'level': 'warning',
                'message': f'Zero-based budgeting: allocations exceed income by {abs(unallocated):,.2f}. Reduce bucket allocations to reach zero.',
            })
    for item in bucket_data:
        threshold = item['bucket'].alert_threshold
        if item['pct'] >= threshold and item['bucket'].monthly_allocation > 0:
            alerts.append({
                'level': 'warning',
                'message': f'{item["bucket"].icon} {item["bucket"].name} has used {item["pct"]}% of its allocation.',
            })
    if monthly_income > 0 and total_spent > monthly_income * Decimal('0.8'):
        spend_pct = int((total_spent / monthly_income) * 100)
        alerts.append({
            'level': 'warning',
            'message': f'Overall spending is at {spend_pct}% of your monthly income.',
        })
    for item in bucket_data:
        if item['bucket'].monthly_allocation == 0 and item['spent'] > 0:
            alerts.append({
                'level': 'warning',
                'message': f'{item["bucket"].icon} {item["bucket"].name} has no allocation but has ${item["spent"]:,.2f} in spending.',
            })

    total_remaining = total_allocated - total_spent
    if total_allocated > 0:
        total_pct = min(int((total_spent / total_allocated) * 100), 100)
    else:
        total_pct = 0

    days_in_month = (fend - fstart).days + 1
    if is_current_month:
        days_elapsed = (today - fstart).days + 1
        days_left = (fend - today).days + 1
    else:
        days_elapsed = days_in_month
        days_left = 0

    actual_daily_avg = (total_spent / Decimal(days_elapsed)).quantize(Decimal('0.01')) if days_elapsed > 0 else Decimal('0')

    if is_current_month and days_left > 0 and remaining_budget > 0:
        ideal_daily_spend = (remaining_budget / Decimal(days_left)).quantize(Decimal('0.01'))
    else:
        ideal_daily_spend = Decimal('0')

    selected_date = datetime.date(year, month, 1)

    prev_month_has_snapshot = MonthlyBudgetAllocation.objects.filter(
        user=request.user, year=prev_year, month=prev_month
    ).exists()

    summary = BudgetSummary.objects.filter(user=request.user, year=year, month=month).first()
    notes = summary.notes if summary else ''

    return render(request, 'budget/budget_overview.html', {
        'current_month': selected_date.strftime('%B %Y'),
        'year': year,
        'month': month,
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
        'days_in_month': days_in_month,
        'days_elapsed': days_elapsed,
        'days_left': days_left,
        'actual_daily_avg': actual_daily_avg,
        'ideal_daily_spend': ideal_daily_spend,
        'alloc_saved': request.GET.get('saved') == '1',
        'alloc_copied': request.GET.get('copied') == '1',
        'alerts': alerts,
        'zero_based': zero_based,
        'every_dollar_assigned': every_dollar_assigned,
        'prev_month_has_snapshot': prev_month_has_snapshot,
        'notes': notes,
        'notes_saved': request.GET.get('notes_saved') == '1',
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

        today = datetime.date.today()
        try:
            snap_year = int(request.POST.get('year', today.year))
            snap_month = int(request.POST.get('month', today.month))
            if not (1 <= snap_month <= 12 and snap_year >= 2000):
                snap_year, snap_month = today.year, today.month
        except (ValueError, TypeError):
            snap_year, snap_month = today.year, today.month

        for bucket in buckets:
            if bucket.pk in allocations:
                MonthlyBudgetAllocation.objects.update_or_create(
                    user=request.user,
                    bucket=bucket,
                    year=snap_year,
                    month=snap_month,
                    defaults={'amount': allocations[bucket.pk]},
                )

    return redirect(reverse('budget_overview') + '?saved=1')


@login_required
def copy_last_month_allocations(request):
    if request.method != 'POST':
        return redirect('budget_overview')

    today = datetime.date.today()
    try:
        year = int(request.POST.get('year', today.year))
        month = int(request.POST.get('month', today.month))
        if not (1 <= month <= 12 and year >= 2000):
            year, month = today.year, today.month
    except (ValueError, TypeError):
        year, month = today.year, today.month

    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1

    snapshots = MonthlyBudgetAllocation.objects.filter(
        user=request.user, year=prev_year, month=prev_month
    ).select_related('bucket')

    buckets_to_update = []
    for snap in snapshots:
        if snap.bucket.is_active and not snap.bucket.is_uncategorized:
            snap.bucket.monthly_allocation = snap.amount
            buckets_to_update.append(snap.bucket)

    if buckets_to_update:
        Bucket.objects.bulk_update(buckets_to_update, ['monthly_allocation'])

        for snap in snapshots:
            if snap.bucket in buckets_to_update:
                MonthlyBudgetAllocation.objects.update_or_create(
                    user=request.user,
                    bucket=snap.bucket,
                    year=year,
                    month=month,
                    defaults={'amount': snap.amount},
                )

    if year == today.year and month == today.month:
        redirect_url = reverse('budget_overview') + '?copied=1'
    else:
        redirect_url = reverse('budget_overview_month', kwargs={'year': year, 'month': month}) + '?copied=1'
    return redirect(redirect_url)


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


@login_required
def budget_history_export_csv(request):
    summaries = BudgetSummary.objects.filter(user=request.user).order_by('-year', '-month')

    def _csv_rows(queryset):
        class _EchoBuf:
            def write(self, val):
                return val

        writer = csv.writer(_EchoBuf())
        yield writer.writerow(['month', 'year', 'income', 'allocated', 'spent', 'saved', 'surplus_deficit', 'necessity_avg'])
        for s in queryset.iterator():
            yield writer.writerow([
                s.month,
                s.year,
                str(s.income),
                str(s.total_allocated),
                str(s.total_spent),
                str(s.total_saved),
                str(s.surplus_deficit),
                str(s.necessity_avg) if s.necessity_avg is not None else '',
            ])

    response = StreamingHttpResponse(_csv_rows(summaries), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="budget_history.csv"'
    return response


@login_required
def save_notes(request):
    if request.method != 'POST':
        return redirect('budget_overview')

    today = datetime.date.today()
    try:
        year = int(request.POST.get('year', today.year))
        month = int(request.POST.get('month', today.month))
        if not (1 <= month <= 12 and year >= 2000):
            year, month = today.year, today.month
    except (ValueError, TypeError):
        year, month = today.year, today.month

    notes = request.POST.get('notes', '')

    monthly_income = request.user.monthly_income or Decimal('0')
    total_allocated = (
        Bucket.objects.filter(user=request.user, is_active=True, is_uncategorized=False)
        .aggregate(s=Sum('monthly_allocation'))['s'] or Decimal('0')
    )
    _fiscal_start = get_user_fiscal_start(request.user)
    _fstart, _fend = get_fiscal_month_range(year, month, _fiscal_start)
    month_expenses = Transaction.objects.filter(
        user=request.user,
        transaction_type='expense',
        date__gte=_fstart,
        date__lte=_fend,
    )
    total_spent = month_expenses.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    necessity_avg = month_expenses.aggregate(a=Avg('necessity_score'))['a']
    total_saved = monthly_income - total_spent
    surplus_deficit = total_saved

    BudgetSummary.objects.update_or_create(
        user=request.user,
        year=year,
        month=month,
        defaults={
            'notes': notes,
            'income': monthly_income,
            'total_allocated': total_allocated,
            'total_spent': total_spent,
            'total_saved': total_saved,
            'surplus_deficit': surplus_deficit,
            'necessity_avg': necessity_avg,
        },
    )

    if year == today.year and month == today.month:
        redirect_url = reverse('budget_overview') + '?notes_saved=1'
    else:
        redirect_url = reverse('budget_overview_month', kwargs={'year': year, 'month': month}) + '?notes_saved=1'
    return redirect(redirect_url)
