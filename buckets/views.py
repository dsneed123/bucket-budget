from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from .models import Bucket


@login_required
def bucket_list(request):
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

        bucket_data.append({
            'bucket': bucket,
            'spent': spent,
            'remaining': remaining,
            'pct': min(pct, 100),
            'bar_class': bar_class,
        })

    return render(request, 'buckets/bucket_list.html', {
        'bucket_data': bucket_data,
        'total_allocated': total_allocated,
        'total_spent': total_spent,
        'total_remaining': total_allocated - total_spent,
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
            bucket.save()
            success = True

    return render(request, 'buckets/bucket_edit.html', {
        'bucket': bucket,
        'errors': errors,
        'success': success,
    })
