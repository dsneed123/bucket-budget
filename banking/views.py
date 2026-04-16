from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required

from .models import BankAccount

ACCOUNT_TYPE_CHOICES = BankAccount.ACCOUNT_TYPE_CHOICES
VALID_ACCOUNT_TYPES = [c[0] for c in ACCOUNT_TYPE_CHOICES]


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
