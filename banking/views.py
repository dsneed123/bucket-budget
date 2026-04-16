from django.shortcuts import render
from django.contrib.auth.decorators import login_required

from .models import BankAccount


@login_required
def account_list(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    total_balance = sum(a.balance for a in accounts)
    return render(request, 'banking/account_list.html', {
        'accounts': accounts,
        'total_balance': total_balance,
    })
