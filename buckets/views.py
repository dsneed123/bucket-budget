from decimal import Decimal
from datetime import date
from django.utils import timezone

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth.decorators import login_required

from .models import Bucket


BUCKET_TEMPLATES = [
    {
        'slug': 'college-student',
        'name': 'College Student',
        'description': 'Essential buckets for managing college expenses.',
        'icon': '🎓',
        'color': '#6c5ce7',
        'buckets': [
            {'name': 'Tuition', 'icon': '🎓', 'color': '#6c5ce7', 'description': 'Semester tuition and fees'},
            {'name': 'Textbooks', 'icon': '📚', 'color': '#0984e3', 'description': 'Books and course materials'},
            {'name': 'Food', 'icon': '🍕', 'color': '#e17055', 'description': 'Meals and dining'},
            {'name': 'Rent', 'icon': '🏠', 'color': '#00b894', 'description': 'Housing and rent'},
            {'name': 'Entertainment', 'icon': '🎉', 'color': '#fdcb6e', 'description': 'Fun and social activities'},
        ],
    },
    {
        'slug': 'young-professional',
        'name': 'Young Professional',
        'description': 'Balanced buckets for early-career budgeting.',
        'icon': '💼',
        'color': '#0984e3',
        'buckets': [
            {'name': 'Rent', 'icon': '🏠', 'color': '#00b894', 'description': 'Monthly rent payment'},
            {'name': 'Utilities', 'icon': '💡', 'color': '#fdcb6e', 'description': 'Electric, water, internet'},
            {'name': 'Groceries', 'icon': '🛒', 'color': '#e17055', 'description': 'Weekly grocery shopping'},
            {'name': 'Transportation', 'icon': '🚗', 'color': '#0984e3', 'description': 'Gas, transit, or car payment'},
            {'name': 'Savings', 'icon': '💰', 'color': '#00cec9', 'description': 'Monthly savings goal'},
            {'name': 'Fun', 'icon': '🎊', 'color': '#a29bfe', 'description': 'Entertainment and leisure'},
        ],
    },
    {
        'slug': 'family',
        'name': 'Family',
        'description': 'Comprehensive buckets for household financial planning.',
        'icon': '👨‍👩‍👧',
        'color': '#00b894',
        'buckets': [
            {'name': 'Mortgage', 'icon': '🏡', 'color': '#00b894', 'description': 'Monthly mortgage payment'},
            {'name': 'Groceries', 'icon': '🛒', 'color': '#e17055', 'description': 'Family grocery budget'},
            {'name': 'Kids', 'icon': '👧', 'color': '#fdcb6e', 'description': 'Children\'s expenses and activities'},
            {'name': 'Utilities', 'icon': '💡', 'color': '#636e72', 'description': 'Electric, water, gas, internet'},
            {'name': 'Insurance', 'icon': '🛡️', 'color': '#0984e3', 'description': 'Health, auto, and home insurance'},
            {'name': 'Savings', 'icon': '💰', 'color': '#00cec9', 'description': 'Family savings and investments'},
            {'name': 'Emergency', 'icon': '🚨', 'color': '#d63031', 'description': 'Emergency fund contributions'},
        ],
    },
]


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
            'alert': pct >= bucket.alert_threshold,
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
        'alert': pct >= bucket.alert_threshold,
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
        alert_threshold_raw = request.POST.get('alert_threshold', '90').strip()

        form_data = {
            'name': name,
            'icon': icon,
            'color': color,
            'monthly_allocation': monthly_allocation,
            'description': description,
            'alert_threshold': alert_threshold_raw,
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

        alert_threshold_val = 90
        try:
            alert_threshold_val = int(alert_threshold_raw)
            if not 1 <= alert_threshold_val <= 100:
                alert_threshold_val = 90
        except (ValueError, TypeError):
            alert_threshold_val = 90

        if not errors:
            Bucket.objects.create(
                user=request.user,
                name=name,
                icon=icon or '💰',
                color=color or '#0984e3',
                monthly_allocation=allocation_val,
                description=description,
                alert_threshold=alert_threshold_val,
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
def quick_allocate(request):
    buckets = list(
        Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    )
    monthly_income = request.user.monthly_income
    errors = {}
    success = False

    if request.method == 'POST':
        allocations = {}
        has_errors = False
        for bucket in buckets:
            raw = request.POST.get(f'allocation_{bucket.pk}', '').strip()
            if raw == '':
                raw = '0'
            try:
                val = Decimal(raw)
                if val < 0:
                    errors[bucket.pk] = 'Must be 0 or more.'
                    has_errors = True
                else:
                    allocations[bucket.pk] = val
            except Exception:
                errors[bucket.pk] = 'Enter a valid number.'
                has_errors = True

        if not has_errors:
            for bucket in buckets:
                bucket.monthly_allocation = allocations[bucket.pk]
            Bucket.objects.bulk_update(buckets, ['monthly_allocation'])
            success = True
            return redirect('bucket_list')

    bucket_rows = [
        {'bucket': b, 'error': errors.get(b.pk)}
        for b in buckets
    ]

    return render(request, 'buckets/quick_allocate.html', {
        'bucket_rows': bucket_rows,
        'monthly_income': monthly_income,
    })


@login_required
def bucket_templates(request):
    if request.method == 'POST':
        slug = request.POST.get('template_slug', '').strip()
        template = next((t for t in BUCKET_TEMPLATES if t['slug'] == slug), None)
        if template:
            for bucket_def in template['buckets']:
                Bucket.objects.create(
                    user=request.user,
                    name=bucket_def['name'],
                    icon=bucket_def['icon'],
                    color=bucket_def['color'],
                    description=bucket_def.get('description', ''),
                    monthly_allocation=Decimal('0'),
                )
        return redirect('bucket_list')

    return render(request, 'buckets/bucket_templates.html', {
        'templates': BUCKET_TEMPLATES,
    })


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
        alert_threshold_raw = request.POST.get('alert_threshold', str(bucket.alert_threshold)).strip()

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

        alert_threshold_val = bucket.alert_threshold
        try:
            alert_threshold_val = int(alert_threshold_raw)
            if not 1 <= alert_threshold_val <= 100:
                alert_threshold_val = bucket.alert_threshold
        except (ValueError, TypeError):
            alert_threshold_val = bucket.alert_threshold

        if not errors:
            bucket.name = name
            bucket.icon = icon or '💰'
            bucket.color = color or '#0984e3'
            bucket.monthly_allocation = allocation_val
            bucket.description = description
            bucket.rollover = rollover
            bucket.alert_threshold = alert_threshold_val
            bucket.save()
            success = True

    return render(request, 'buckets/bucket_edit.html', {
        'bucket': bucket,
        'errors': errors,
        'success': success,
    })
