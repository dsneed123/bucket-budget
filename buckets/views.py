from decimal import Decimal
from datetime import date
from django.utils import timezone

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required

from .models import Bucket


@login_required
def bucket_list(request):
    show_archived = request.GET.get('show_archived') == '1'

    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    bucket_data = []
    total_allocated = Decimal('0')
    total_spent = Decimal('0')

    for bucket in buckets:
        allocated = bucket.monthly_allocation
        spent = Decimal('0')  # Will be calculated from transactions once available
        remaining = allocated - spent
        if allocated > 0:
            pct = int((spent / allocated) * 100)
        else:
            pct = 0

        if pct >= 90:
            bar_class = 'progress-bar-red'
        elif pct >= 75:
            bar_class = 'progress-bar-gold'
        else:
            bar_class = 'progress-bar'

        total_allocated += allocated
        total_spent += spent

        rollover_amount = bucket.rollover_amount() if bucket.rollover else Decimal('0')

        bucket_data.append({
            'bucket': bucket,
            'spent': spent,
            'remaining': remaining,
            'pct': min(pct, 100),
            'bar_class': bar_class,
            'rollover_amount': rollover_amount,
        })

    archived_buckets = []
    if show_archived:
        archived_buckets = list(
            Bucket.objects.filter(user=request.user, is_active=False).order_by('-archived_at', 'name')
        )

    archived_count = Bucket.objects.filter(user=request.user, is_active=False).count()

    monthly_income = request.user.monthly_income
    over_by = total_allocated - monthly_income if monthly_income > 0 and total_allocated > monthly_income else Decimal('0')

    return render(request, 'buckets/bucket_list.html', {
        'bucket_data': bucket_data,
        'total_allocated': total_allocated,
        'total_spent': total_spent,
        'total_remaining': total_allocated - total_spent,
        'show_archived': show_archived,
        'archived_buckets': archived_buckets,
        'archived_count': archived_count,
        'monthly_income': monthly_income,
        'over_by': over_by,
    })


@login_required
def bucket_detail(request, bucket_id):
    bucket = get_object_or_404(Bucket, pk=bucket_id, user=request.user, is_active=True)

    today = date.today()
    allocated = bucket.monthly_allocation
    spent = Decimal('0')  # Will be calculated from transactions once available
    remaining = allocated - spent
    if allocated > 0:
        pct = min(int((spent / allocated) * 100), 100)
    else:
        pct = 0

    if pct >= 90:
        bar_class = 'progress-bar-red'
    elif pct >= 75:
        bar_class = 'progress-bar-gold'
    else:
        bar_class = 'progress-bar'

    # Build last 6 months history (placeholder until Transaction model exists)
    monthly_history = []
    year = today.year
    month = today.month
    for i in range(5, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        label = date(y, m, 1).strftime('%b')
        monthly_history.append({'label': label, 'spent': Decimal('0'), 'allocated': allocated})

    max_spent = max((h['spent'] for h in monthly_history), default=Decimal('0'))
    max_bar = max(max_spent, allocated) or Decimal('1')
    for h in monthly_history:
        h['bar_pct'] = int((h['spent'] / max_bar) * 100)
        h['alloc_pct'] = int((h['allocated'] / max_bar) * 100)

    transactions = []  # Will be populated from Transaction model once available

    return render(request, 'buckets/bucket_detail.html', {
        'bucket': bucket,
        'spent': spent,
        'remaining': remaining,
        'pct': pct,
        'bar_class': bar_class,
        'monthly_history': monthly_history,
        'transactions': transactions,
        'current_month': today.strftime('%B %Y'),
    })


@login_required
def bucket_add(request):
    errors = {}
    form_data = {'color': '#0984e3', 'icon': '💰'}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        icon = request.POST.get('icon', '💰').strip()
        color = request.POST.get('color', '#0984e3').strip()
        monthly_allocation = request.POST.get('monthly_allocation', '').strip()
        description = request.POST.get('description', '').strip()

        form_data = {
            'name': name,
            'icon': icon,
            'color': color,
            'monthly_allocation': monthly_allocation,
            'description': description,
        }

        if not name:
            errors['name'] = 'Bucket name is required.'

        allocation_val = Decimal('0')
        if not monthly_allocation:
            errors['monthly_allocation'] = 'Monthly allocation is required.'
        else:
            try:
                allocation_val = Decimal(monthly_allocation)
                if allocation_val < 0:
                    errors['monthly_allocation'] = 'Allocation must be a positive number.'
            except Exception:
                errors['monthly_allocation'] = 'Please enter a valid number.'

        if not errors:
            Bucket.objects.create(
                user=request.user,
                name=name,
                icon=icon or '💰',
                color=color or '#0984e3',
                monthly_allocation=allocation_val,
                description=description,
            )
            return redirect('bucket_list')

    return render(request, 'buckets/bucket_add.html', {
        'errors': errors,
        'form_data': form_data,
    })


@login_required
def bucket_delete(request, bucket_id):
    bucket = get_object_or_404(Bucket, pk=bucket_id, user=request.user, is_active=True)
    transaction_count = 0  # Will be calculated from transactions once available

    if request.method == 'POST':
        bucket.delete()
        return redirect('bucket_list')

    return render(request, 'buckets/bucket_delete.html', {
        'bucket': bucket,
        'transaction_count': transaction_count,
    })


@login_required
def bucket_archive(request, bucket_id):
    bucket = get_object_or_404(Bucket, pk=bucket_id, user=request.user, is_active=True)
    transaction_count = 0  # Will be calculated from transactions once available

    if request.method == 'POST':
        bucket.is_active = False
        bucket.archived_at = timezone.now()
        bucket.save()
        return redirect('bucket_list')

    return render(request, 'buckets/bucket_archive.html', {
        'bucket': bucket,
        'transaction_count': transaction_count,
    })


@login_required
def bucket_unarchive(request, bucket_id):
    bucket = get_object_or_404(Bucket, pk=bucket_id, user=request.user, is_active=False)

    if request.method == 'POST':
        bucket.is_active = True
        bucket.archived_at = None
        bucket.save()

    return redirect(reverse('bucket_list') + '?show_archived=1')


@login_required
def bucket_reorder(request):
    if request.method == 'POST':
        bucket_id = request.POST.get('bucket_id', '')
        direction = request.POST.get('direction', '')

        buckets = list(
            Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
        )

        idx = next((i for i, b in enumerate(buckets) if str(b.pk) == bucket_id), None)

        if idx is not None:
            swap_idx = None
            if direction == 'up' and idx > 0:
                swap_idx = idx - 1
            elif direction == 'down' and idx < len(buckets) - 1:
                swap_idx = idx + 1

            if swap_idx is not None:
                for i, b in enumerate(buckets):
                    b.sort_order = i
                buckets[idx].sort_order, buckets[swap_idx].sort_order = (
                    buckets[swap_idx].sort_order,
                    buckets[idx].sort_order,
                )
                Bucket.objects.bulk_update(buckets, ['sort_order'])

    return redirect('bucket_list')


@login_required
def bucket_edit(request, bucket_id):
    bucket = get_object_or_404(Bucket, pk=bucket_id, user=request.user, is_active=True)
    errors = {}
    success = False

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        icon = request.POST.get('icon', '💰').strip()
        color = request.POST.get('color', '#0984e3').strip()
        monthly_allocation = request.POST.get('monthly_allocation', '').strip()
        description = request.POST.get('description', '').strip()
        rollover = request.POST.get('rollover') == 'on'

        if not name:
            errors['name'] = 'Bucket name is required.'

        allocation_val = bucket.monthly_allocation
        if not monthly_allocation:
            errors['monthly_allocation'] = 'Monthly allocation is required.'
        else:
            try:
                allocation_val = Decimal(monthly_allocation)
                if allocation_val < 0:
                    errors['monthly_allocation'] = 'Allocation must be a positive number.'
            except Exception:
                errors['monthly_allocation'] = 'Please enter a valid number.'

        if not errors:
            bucket.name = name
            bucket.icon = icon or '💰'
            bucket.color = color or '#0984e3'
            bucket.monthly_allocation = allocation_val
            bucket.description = description
            bucket.rollover = rollover
            bucket.save()
            success = True

    return render(request, 'buckets/bucket_edit.html', {
        'bucket': bucket,
        'errors': errors,
        'success': success,
    })
