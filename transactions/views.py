import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import render, redirect

from banking.models import BankAccount
from buckets.models import Bucket

from .models import Transaction

VALID_TRANSACTION_TYPES = [c[0] for c in Transaction.TRANSACTION_TYPE_CHOICES]


@login_required
def transaction_list(request):
    qs = Transaction.objects.filter(user=request.user).select_related('account', 'bucket')

    # Extract filter params
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    bucket_id = request.GET.get('bucket', '').strip()
    txn_type = request.GET.get('type', '').strip()
    account_id = request.GET.get('account', '').strip()
    search = request.GET.get('search', '').strip()

    # Apply filters
    if date_from:
        try:
            qs = qs.filter(date__gte=datetime.date.fromisoformat(date_from))
        except ValueError:
            date_from = ''
    if date_to:
        try:
            qs = qs.filter(date__lte=datetime.date.fromisoformat(date_to))
        except ValueError:
            date_to = ''
    if bucket_id:
        qs = qs.filter(bucket_id=bucket_id)
    if txn_type in ('expense', 'income'):
        qs = qs.filter(transaction_type=txn_type)
    else:
        txn_type = ''
    if account_id:
        qs = qs.filter(account_id=account_id)
    if search:
        qs = qs.filter(Q(description__icontains=search) | Q(vendor__icontains=search))

    active_filter_count = sum(bool(f) for f in [date_from, date_to, bucket_id, txn_type, account_id, search])

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    today = datetime.date.today()
    # Stats always reflect current month across all user transactions (unaffected by filters)
    month_qs = Transaction.objects.filter(
        user=request.user, date__year=today.year, date__month=today.month
    )
    total_income = month_qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = month_qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    net = total_income - total_expenses

    # Build query string for pagination links (preserves active filters)
    filter_params = {}
    if date_from:
        filter_params['date_from'] = date_from
    if date_to:
        filter_params['date_to'] = date_to
    if bucket_id:
        filter_params['bucket'] = bucket_id
    if txn_type:
        filter_params['type'] = txn_type
    if account_id:
        filter_params['account'] = account_id
    if search:
        filter_params['search'] = search
    filter_qs = urlencode(filter_params)

    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')

    return render(request, 'transactions/transaction_list.html', {
        'page_obj': page_obj,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': net,
        'current_month': today.strftime('%B %Y'),
        'buckets': buckets,
        'accounts': accounts,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'bucket': bucket_id,
            'type': txn_type,
            'account': account_id,
            'search': search,
        },
        'active_filter_count': active_filter_count,
        'filter_qs': filter_qs,
    })


@login_required
def transaction_add(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    errors = {}
    form_data = {
        'transaction_type': 'expense',
        'date': datetime.date.today().isoformat(),
    }

    if request.method == 'POST':
        amount = request.POST.get('amount', '').strip()
        transaction_type = request.POST.get('transaction_type', '').strip()
        description = request.POST.get('description', '').strip()
        vendor = request.POST.get('vendor', '').strip()
        bucket_id = request.POST.get('bucket', '').strip()
        account_id = request.POST.get('account', '').strip()
        date_str = request.POST.get('date', '').strip()
        necessity_score_str = request.POST.get('necessity_score', '').strip()

        form_data = {
            'amount': amount,
            'transaction_type': transaction_type,
            'description': description,
            'vendor': vendor,
            'bucket': bucket_id,
            'account': account_id,
            'date': date_str,
            'necessity_score': necessity_score_str,
        }

        # Validate amount
        amount_val = None
        if not amount:
            errors['amount'] = 'Amount is required.'
        else:
            try:
                amount_val = Decimal(amount)
                if amount_val <= 0:
                    errors['amount'] = 'Amount must be greater than zero.'
            except InvalidOperation:
                errors['amount'] = 'Please enter a valid amount.'

        # Validate transaction_type
        if not transaction_type:
            errors['transaction_type'] = 'Transaction type is required.'
        elif transaction_type not in ('expense', 'income'):
            errors['transaction_type'] = 'Please select expense or income.'

        # Validate description
        if not description:
            errors['description'] = 'Description is required.'

        # Validate account
        account = None
        if not account_id:
            errors['account'] = 'Account is required.'
        else:
            try:
                account = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                errors['account'] = 'Please select a valid account.'

        # Validate bucket (optional)
        bucket = None
        if bucket_id:
            try:
                bucket = buckets.get(pk=bucket_id)
            except Bucket.DoesNotExist:
                errors['bucket'] = 'Please select a valid bucket.'

        # Validate date
        date_val = None
        if not date_str:
            errors['date'] = 'Date is required.'
        else:
            try:
                date_val = datetime.date.fromisoformat(date_str)
            except ValueError:
                errors['date'] = 'Please enter a valid date.'

        # Validate necessity_score (optional, expenses only)
        necessity_score_val = None
        if necessity_score_str and transaction_type == 'expense':
            try:
                necessity_score_val = int(necessity_score_str)
                if not (1 <= necessity_score_val <= 10):
                    errors['necessity_score'] = 'Necessity score must be between 1 and 10.'
            except ValueError:
                errors['necessity_score'] = 'Please enter a valid necessity score.'

        if not errors:
            Transaction.objects.create(
                user=request.user,
                account=account,
                bucket=bucket,
                amount=amount_val,
                transaction_type=transaction_type,
                description=description,
                vendor=vendor,
                date=date_val,
                necessity_score=necessity_score_val,
            )

            # Update account balance
            if transaction_type == 'expense':
                account.balance = account.balance - amount_val
            else:  # income
                account.balance = account.balance + amount_val
            account.save(change_reason='transaction')

            return redirect('transaction_list')

    return render(request, 'transactions/transaction_add.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
    })
