import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render

from banking.models import BankAccount
from buckets.models import Bucket
from transactions.models import Transaction


def index(request):
    return render(request, 'core/index.html')


def health(request):
    return HttpResponse("ok", status=200)


@login_required
def dashboard(request):
    today = datetime.date.today()
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    month_qs = Transaction.objects.filter(
        user=request.user, date__year=today.year, date__month=today.month
    )
    total_income = month_qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = month_qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    net = total_income - total_expenses

    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related('account', 'bucket')
        .order_by('-date', '-created_at')[:5]
    )

    quick_add_errors = request.session.pop('quick_add_errors', {})
    quick_add_form_data = request.session.pop('quick_add_form_data', {
        'transaction_type': 'expense',
        'date': today.isoformat(),
    })

    return render(request, 'core/dashboard.html', {
        'accounts': accounts,
        'buckets': buckets,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': net,
        'current_month': today.strftime('%B %Y'),
        'recent_transactions': recent_transactions,
        'quick_add_errors': quick_add_errors,
        'quick_add_form_data': quick_add_form_data,
    })
