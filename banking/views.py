from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone

from decimal import Decimal, InvalidOperation

from .forms import AccountUpdateBalanceForm, BankAccountForm
from .models import BankAccount

ACCOUNT_TYPE_CHOICES = BankAccount.ACCOUNT_TYPE_CHOICES
VALID_ACCOUNT_TYPES = [c[0] for c in ACCOUNT_TYPE_CHOICES]


def _form_errors(form):
    return {field: errs[0] for field, errs in form.errors.items()}


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
        form_data = request.POST.dict()
        raw_balance = request.POST.get('balance', '0') or '0'
        try:
            initial_balance = Decimal(raw_balance).quantize(Decimal('0.01'))
        except InvalidOperation:
            initial_balance = None

        form = BankAccountForm(request.POST)
        if initial_balance is None:
            errors = {'balance': 'Please enter a valid number.'}
        elif form.is_valid():
            cd = form.cleaned_data
            BankAccount.objects.create(
                user=request.user,
                name=cd['name'],
                account_type=cd['account_type'],
                institution=cd.get('institution') or None,
                balance=initial_balance,
                color=cd['color'],
            )
            return redirect('account_list')
        else:
            errors = _form_errors(form)

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
        form = AccountUpdateBalanceForm(request.POST)
        if form.is_valid():
            new_balance_val = form.cleaned_data['new_balance']
            previous_balance = account.balance
            change_amount = float(new_balance_val) - float(previous_balance)
            account.balance = new_balance_val
            account.save(change_reason='manual_update')
            success = True
        else:
            errors = _form_errors(form)

    return render(request, 'banking/account_update_balance.html', {
        'account': account,
        'errors': errors,
        'success': success,
        'change_amount': change_amount,
    })


@login_required
def account_delete(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user, is_active=True)
    transaction_count = account.transactions.count()

    if request.method == 'POST':
        account.is_active = False
        account.save()
        return redirect('account_list')

    return render(request, 'banking/account_delete.html', {
        'account': account,
        'transaction_count': transaction_count,
    })


@login_required
def account_edit(request, account_id):
    account = get_object_or_404(BankAccount, pk=account_id, user=request.user, is_active=True)
    errors = {}
    success = False

    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            account.name = cd['name']
            account.account_type = cd['account_type']
            account.institution = cd.get('institution') or None
            account.color = cd['color']
            account.save()
            success = True
        else:
            errors = _form_errors(form)

    return render(request, 'banking/account_edit.html', {
        'account': account,
        'errors': errors,
        'success': success,
        'account_type_choices': ACCOUNT_TYPE_CHOICES,
    })
