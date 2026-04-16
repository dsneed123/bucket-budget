from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from .models import BankAccount

ACCOUNT_TYPE_CHOICES = BankAccount.ACCOUNT_TYPE_CHOICES
VALID_ACCOUNT_TYPES = [c[0] for c in ACCOUNT_TYPE_CHOICES]


@login_required
def account_detail(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user, is_active=True)

    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=29)

    # History entries within the 30-day window, ascending for chart building
    window_history = list(
        account.balance_history.filter(created_at__date__gte=thirty_days_ago).order_by('created_at')
    )

    # Determine the balance at the start of the window
    before_window = account.balance_history.filter(
        created_at__date__lt=thirty_days_ago
    ).order_by('-created_at').first()

    if before_window:
        starting_balance = float(before_window.new_balance)
    elif window_history:
        starting_balance = float(window_history[0].previous_balance)
    else:
        starting_balance = float(account.balance)

    # Build per-day closing balances (last change wins each day)
    daily_close = {}
    for entry in window_history:
        daily_close[entry.created_at.date()] = float(entry.new_balance)

    # Fill forward across all 30 days
    chart_data = []
    last_known = starting_balance
    for i in range(30):
        day = thirty_days_ago + timedelta(days=i)
        if day in daily_close:
            last_known = daily_close[day]
        chart_data.append({'date': day, 'balance': last_known})

    # Compute bar heights as percentages
    balances = [d['balance'] for d in chart_data]
    min_bal = min(balances)
    max_bal = max(balances)
    bal_range = max_bal - min_bal
    for item in chart_data:
        if bal_range > 0:
            item['height_pct'] = max(4, round((item['balance'] - min_bal) / bal_range * 100))
        else:
            item['height_pct'] = 50

    recent_changes = list(account.balance_history.all()[:20])

    return render(request, 'banking/account_detail.html', {
        'account': account,
        'chart_data': chart_data,
        'recent_changes': recent_changes,
        'min_bal': min_bal,
        'max_bal': max_bal,
    })


@login_required
def account_list(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    total_balance = sum(a.balance for a in accounts)
    return render(request, 'banking/account_list.html', {
        'accounts': accounts,
        'total_balance': total_balance,
    })


@login_required
def account_add(request):
    errors = {}
    form_data = {'color': '#0984e3'}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        account_type = request.POST.get('account_type', '').strip()
        institution = request.POST.get('institution', '').strip()
        balance = request.POST.get('balance', '').strip()
        color = request.POST.get('color', '#0984e3').strip()

        form_data = {
            'name': name,
            'account_type': account_type,
            'institution': institution,
            'balance': balance,
            'color': color,
        }

        if not name:
            errors['name'] = 'Account name is required.'

        if not account_type:
            errors['account_type'] = 'Account type is required.'
        elif account_type not in VALID_ACCOUNT_TYPES:
            errors['account_type'] = 'Please select a valid account type.'

        balance_val = 0
        if balance:
            try:
                balance_val = float(balance)
            except ValueError:
                errors['balance'] = 'Please enter a valid number.'

        if not errors:
            BankAccount.objects.create(
                user=request.user,
                name=name,
                account_type=account_type,
                institution=institution or None,
                balance=balance_val,
                color=color,
            )
            return redirect('account_list')

    return render(request, 'banking/account_add.html', {
        'errors': errors,
        'form_data': form_data,
        'account_type_choices': ACCOUNT_TYPE_CHOICES,
    })


@login_required
def account_update_balance(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user, is_active=True)
    errors = {}
    success = False
    change_amount = None

    if request.method == 'POST':
        new_balance = request.POST.get('new_balance', '').strip()

        if not new_balance:
            errors['new_balance'] = 'New balance is required.'
        else:
            try:
                new_balance_val = float(new_balance)
            except ValueError:
                errors['new_balance'] = 'Please enter a valid number.'

        if not errors:
            previous_balance = account.balance
            change_amount = round(new_balance_val - float(previous_balance), 2)
            account.balance = new_balance_val
            account.save(change_reason='manual_update')
            success = True

    return render(request, 'banking/account_update_balance.html', {
        'account': account,
        'errors': errors,
        'success': success,
        'change_amount': change_amount,
    })


@login_required
def account_edit(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user, is_active=True)
    errors = {}
    success = False

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        account_type = request.POST.get('account_type', '').strip()
        institution = request.POST.get('institution', '').strip()
        balance = request.POST.get('balance', '').strip()
        color = request.POST.get('color', '#0984e3').strip()

        if not name:
            errors['name'] = 'Account name is required.'

        if not account_type:
            errors['account_type'] = 'Account type is required.'
        elif account_type not in VALID_ACCOUNT_TYPES:
            errors['account_type'] = 'Please select a valid account type.'

        balance_val = account.balance
        if balance:
            try:
                balance_val = float(balance)
            except ValueError:
                errors['balance'] = 'Please enter a valid number.'

        if not errors:
            account.name = name
            account.account_type = account_type
            account.institution = institution or None
            account.balance = balance_val
            account.color = color
            account.save()
            success = True

    return render(request, 'banking/account_edit.html', {
        'account': account,
        'errors': errors,
        'success': success,
        'account_type_choices': ACCOUNT_TYPE_CHOICES,
    })
