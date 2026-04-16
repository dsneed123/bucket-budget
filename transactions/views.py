import datetime
import json
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket

from .models import Tag, Transaction, VendorMapping

VALID_TRANSACTION_TYPES = [c[0] for c in Transaction.TRANSACTION_TYPE_CHOICES]

TAG_COLOR_PALETTE = [
    '#0984e3', '#00d4aa', '#f9ca24', '#ff4757',
    '#a29bfe', '#fd79a8', '#55efc4', '#fdcb6e',
    '#e17055', '#74b9ff',
]


def _resolve_tags(user, raw_names):
    """Parse comma-separated tag names and get-or-create Tag objects for the user."""
    tags = []
    existing_count = Tag.objects.filter(user=user).count()
    for i, raw in enumerate(raw_names.split(',')):
        name = raw.strip()
        if not name:
            continue
        color = TAG_COLOR_PALETTE[(existing_count + i) % len(TAG_COLOR_PALETTE)]
        tag, created = Tag.objects.get_or_create(
            user=user,
            name__iexact=name,
            defaults={'name': name, 'color': color},
        )
        tags.append(tag)
    return tags


@login_required
def vendor_autocomplete(request):
    """Return JSON list of vendor names and their mapped bucket IDs for the current user."""
    mappings = VendorMapping.objects.filter(user=request.user).select_related('bucket').order_by('-last_used')
    data = [
        {'vendor': m.vendor_name, 'bucket_id': m.bucket_id}
        for m in mappings
    ]
    return JsonResponse({'vendors': data})


@login_required
def transaction_list(request):
    qs = Transaction.objects.filter(user=request.user).select_related('account', 'bucket').prefetch_related('tags')

    # Extract filter params
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    bucket_id = request.GET.get('bucket', '').strip()
    txn_type = request.GET.get('type', '').strip()
    account_id = request.GET.get('account', '').strip()
    search = request.GET.get('search', '').strip()
    tag_id = request.GET.get('tag', '').strip()

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
    if tag_id:
        try:
            Tag.objects.get(pk=tag_id, user=request.user)
            qs = qs.filter(tags__id=tag_id).distinct()
        except Tag.DoesNotExist:
            tag_id = ''

    active_filter_count = sum(bool(f) for f in [date_from, date_to, bucket_id, txn_type, account_id, search, tag_id])

    # Compute running balance for all filtered transactions
    # Process oldest-to-newest so balance accumulates in chronological order
    all_txns = list(qs.order_by('date', 'created_at'))

    if account_id:
        try:
            acct_obj = BankAccount.objects.get(pk=account_id, user=request.user)
            income_sum = qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
            expense_sum = qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')
            running = acct_obj.balance - (income_sum - expense_sum)
        except BankAccount.DoesNotExist:
            running = Decimal('0')
    else:
        running = Decimal('0')

    for txn in all_txns:
        if txn.transaction_type == 'income':
            running += txn.amount
        else:
            running -= txn.amount
        txn.running_balance = running

    # Restore newest-first ordering for display
    all_txns.sort(key=lambda t: (t.date, t.created_at), reverse=True)

    paginator = Paginator(all_txns, 25)
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
    if tag_id:
        filter_params['tag'] = tag_id
    filter_qs = urlencode(filter_params)

    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    tags = Tag.objects.filter(user=request.user).order_by('name')

    return render(request, 'transactions/transaction_list.html', {
        'page_obj': page_obj,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': net,
        'current_month': today.strftime('%B %Y'),
        'buckets': buckets,
        'accounts': accounts,
        'tags': tags,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'bucket': bucket_id,
            'type': txn_type,
            'account': account_id,
            'search': search,
            'tag': tag_id,
        },
        'active_filter_count': active_filter_count,
        'filter_qs': filter_qs,
        'balance_is_absolute': bool(account_id),
    })


@login_required
def transaction_add(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    user_tags = Tag.objects.filter(user=request.user).order_by('name')
    vendor_mappings = list(
        VendorMapping.objects.filter(user=request.user)
        .values('vendor_name', 'bucket_id')
        .order_by('-last_used')
    )

    errors = {}
    form_data = {
        'transaction_type': 'expense',
        'date': datetime.date.today().isoformat(),
        'tags': '',
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
        tags_raw = request.POST.get('tags', '').strip()

        form_data = {
            'amount': amount,
            'transaction_type': transaction_type,
            'description': description,
            'vendor': vendor,
            'bucket': bucket_id,
            'account': account_id,
            'date': date_str,
            'necessity_score': necessity_score_str,
            'tags': tags_raw,
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
            force_save = request.POST.get('force_save', '') == '1'
            duplicate_warning = None

            if not force_save and vendor:
                window_start = date_val - datetime.timedelta(days=7)
                window_end = date_val + datetime.timedelta(days=7)
                duplicate_warning = Transaction.objects.filter(
                    user=request.user,
                    amount=amount_val,
                    vendor__iexact=vendor,
                    date__gte=window_start,
                    date__lte=window_end,
                ).first()

            if duplicate_warning:
                return render(request, 'transactions/transaction_add.html', {
                    'errors': errors,
                    'form_data': form_data,
                    'accounts': accounts,
                    'buckets': buckets,
                    'user_tags': user_tags,
                    'vendor_mappings_json': json.dumps(vendor_mappings),
                    'duplicate_warning': duplicate_warning,
                })

            receipt = request.FILES.get('receipt') or None
            txn = Transaction.objects.create(
                user=request.user,
                account=account,
                bucket=bucket,
                amount=amount_val,
                transaction_type=transaction_type,
                description=description,
                vendor=vendor,
                date=date_val,
                necessity_score=necessity_score_val,
                receipt=receipt,
            )
            if tags_raw:
                txn.tags.set(_resolve_tags(request.user, tags_raw))

            if vendor:
                existing = VendorMapping.objects.filter(user=request.user, vendor_name__iexact=vendor).first()
                if existing:
                    existing.bucket = bucket
                    existing.save()
                else:
                    VendorMapping.objects.create(user=request.user, vendor_name=vendor, bucket=bucket)

            next_url = request.POST.get('next', '').strip()
            if next_url == '/dashboard/':
                return redirect('dashboard')
            return redirect('transaction_list')

    return render(request, 'transactions/transaction_add.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
        'user_tags': user_tags,
        'vendor_mappings_json': json.dumps(vendor_mappings),
    })


@login_required
def transaction_edit(request, transaction_id):
    transaction = get_object_or_404(Transaction, pk=transaction_id, user=request.user)

    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    user_tags = Tag.objects.filter(user=request.user).order_by('name')

    errors = {}

    if request.method == 'POST':
        amount = request.POST.get('amount', '').strip()
        transaction_type = request.POST.get('transaction_type', '').strip()
        description = request.POST.get('description', '').strip()
        vendor = request.POST.get('vendor', '').strip()
        bucket_id = request.POST.get('bucket', '').strip()
        account_id = request.POST.get('account', '').strip()
        date_str = request.POST.get('date', '').strip()
        necessity_score_str = request.POST.get('necessity_score', '').strip()
        tags_raw = request.POST.get('tags', '').strip()
        notes = request.POST.get('notes', '')

        form_data = {
            'amount': amount,
            'transaction_type': transaction_type,
            'description': description,
            'vendor': vendor,
            'bucket': bucket_id,
            'account': account_id,
            'date': date_str,
            'necessity_score': necessity_score_str,
            'tags': tags_raw,
            'notes': notes,
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
            # Update transaction fields — the post_save signal handles balance.
            transaction.account = account
            transaction.bucket = bucket
            transaction.amount = amount_val
            transaction.transaction_type = transaction_type
            transaction.description = description
            transaction.vendor = vendor
            transaction.date = date_val
            transaction.necessity_score = necessity_score_val
            transaction.notes = notes
            if request.FILES.get('receipt'):
                transaction.receipt = request.FILES['receipt']
            elif request.POST.get('clear_receipt') == '1':
                transaction.receipt = None
            transaction.save()
            transaction.tags.set(_resolve_tags(request.user, tags_raw) if tags_raw else [])

            return redirect('transaction_list')
    else:
        existing_tags = ', '.join(transaction.tags.values_list('name', flat=True))
        form_data = {
            'amount': str(transaction.amount),
            'transaction_type': transaction.transaction_type,
            'description': transaction.description,
            'vendor': transaction.vendor,
            'bucket': str(transaction.bucket_id) if transaction.bucket_id else '',
            'account': str(transaction.account_id),
            'date': transaction.date.isoformat(),
            'necessity_score': str(transaction.necessity_score) if transaction.necessity_score is not None else '',
            'tags': existing_tags,
            'notes': transaction.notes,
        }

    return render(request, 'transactions/transaction_edit.html', {
        'transaction': transaction,
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
        'user_tags': user_tags,
    })


@login_required
def transaction_add_split(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    errors = {}
    # Default two empty split rows
    default_splits = [{'amount': '', 'bucket': ''}, {'amount': '', 'bucket': ''}]
    form_data = {
        'transaction_type': 'expense',
        'date': datetime.date.today().isoformat(),
        'splits': default_splits,
    }

    if request.method == 'POST':
        transaction_type = request.POST.get('transaction_type', '').strip()
        description = request.POST.get('description', '').strip()
        vendor = request.POST.get('vendor', '').strip()
        account_id = request.POST.get('account', '').strip()
        date_str = request.POST.get('date', '').strip()

        # Collect split rows from POST (arrays: split_amount[], split_bucket[])
        split_amounts = request.POST.getlist('split_amount')
        split_buckets = request.POST.getlist('split_bucket')
        splits_raw = [
            {'amount': a.strip(), 'bucket': b.strip()}
            for a, b in zip(split_amounts, split_buckets)
        ]

        form_data = {
            'transaction_type': transaction_type,
            'description': description,
            'vendor': vendor,
            'account': account_id,
            'date': date_str,
            'splits': splits_raw if splits_raw else default_splits,
        }

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

        # Validate date
        date_val = None
        if not date_str:
            errors['date'] = 'Date is required.'
        else:
            try:
                date_val = datetime.date.fromisoformat(date_str)
            except ValueError:
                errors['date'] = 'Please enter a valid date.'

        # Validate splits
        split_errors = {}
        validated_splits = []
        non_empty = [(i, s) for i, s in enumerate(splits_raw) if s['amount'] or s['bucket']]

        if len(non_empty) < 2:
            errors['splits'] = 'At least two splits are required.'
        else:
            for i, split in non_empty:
                row_errors = {}
                amount_val = None
                if not split['amount']:
                    row_errors['amount'] = 'Required.'
                else:
                    try:
                        amount_val = Decimal(split['amount'])
                        if amount_val <= 0:
                            row_errors['amount'] = 'Must be greater than zero.'
                    except InvalidOperation:
                        row_errors['amount'] = 'Enter a valid amount.'

                bucket = None
                if split['bucket']:
                    try:
                        bucket = buckets.get(pk=split['bucket'])
                    except Bucket.DoesNotExist:
                        row_errors['bucket'] = 'Invalid bucket.'

                if row_errors:
                    split_errors[i] = row_errors
                else:
                    validated_splits.append({'amount': amount_val, 'bucket': bucket, 'index': i})

            if split_errors:
                errors['split_rows'] = split_errors

        if not errors:
            group_id = uuid.uuid4()
            for split in validated_splits:
                Transaction.objects.create(
                    user=request.user,
                    account=account,
                    bucket=split['bucket'],
                    amount=split['amount'],
                    transaction_type=transaction_type,
                    description=description,
                    vendor=vendor,
                    date=date_val,
                    split_group=group_id,
                )
            return redirect('transaction_list')

    return render(request, 'transactions/transaction_add_split.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
    })


@login_required
def transaction_transfer(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')

    errors = {}
    form_data = {
        'date': datetime.date.today().isoformat(),
    }

    if request.method == 'POST':
        from_account_id = request.POST.get('from_account', '').strip()
        to_account_id = request.POST.get('to_account', '').strip()
        amount = request.POST.get('amount', '').strip()
        description = request.POST.get('description', '').strip()
        date_str = request.POST.get('date', '').strip()

        form_data = {
            'from_account': from_account_id,
            'to_account': to_account_id,
            'amount': amount,
            'description': description,
            'date': date_str,
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

        # Validate from_account
        from_account = None
        if not from_account_id:
            errors['from_account'] = 'Source account is required.'
        else:
            try:
                from_account = accounts.get(pk=from_account_id)
            except BankAccount.DoesNotExist:
                errors['from_account'] = 'Please select a valid account.'

        # Validate to_account
        to_account = None
        if not to_account_id:
            errors['to_account'] = 'Destination account is required.'
        else:
            try:
                to_account = accounts.get(pk=to_account_id)
            except BankAccount.DoesNotExist:
                errors['to_account'] = 'Please select a valid account.'

        # Ensure accounts differ
        if from_account and to_account and from_account_id == to_account_id:
            errors['to_account'] = 'Destination account must differ from source account.'

        # Validate description
        if not description:
            errors['description'] = 'Description is required.'

        # Validate date
        date_val = None
        if not date_str:
            errors['date'] = 'Date is required.'
        else:
            try:
                date_val = datetime.date.fromisoformat(date_str)
            except ValueError:
                errors['date'] = 'Please enter a valid date.'

        if not errors:
            transfer_id = uuid.uuid4()
            Transaction.objects.create(
                user=request.user,
                account=from_account,
                amount=amount_val,
                transaction_type='expense',
                description=description,
                date=date_val,
                transfer_id=transfer_id,
            )
            Transaction.objects.create(
                user=request.user,
                account=to_account,
                amount=amount_val,
                transaction_type='income',
                description=description,
                date=date_val,
                transfer_id=transfer_id,
            )
            return redirect('transaction_list')

    return render(request, 'transactions/transaction_transfer.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
    })


@login_required
def transaction_detail(request, transaction_id):
    transaction = get_object_or_404(
        Transaction.objects.select_related('account', 'bucket').prefetch_related('tags'),
        pk=transaction_id,
        user=request.user,
    )

    split_transactions = None
    if transaction.split_group:
        split_transactions = (
            Transaction.objects.filter(user=request.user, split_group=transaction.split_group)
            .select_related('account', 'bucket')
            .order_by('pk')
        )

    linked_transfer = None
    if transaction.transfer_id:
        linked_transfer = (
            Transaction.objects.filter(user=request.user, transfer_id=transaction.transfer_id)
            .exclude(pk=transaction.pk)
            .select_related('account')
            .first()
        )

    necessity_label = None
    if transaction.necessity_score is not None:
        if transaction.necessity_score <= 3:
            necessity_label = 'Want'
        elif transaction.necessity_score <= 6:
            necessity_label = 'Useful'
        else:
            necessity_label = 'Need'

    return render(request, 'transactions/transaction_detail.html', {
        'transaction': transaction,
        'split_transactions': split_transactions,
        'linked_transfer': linked_transfer,
        'necessity_label': necessity_label,
    })


@login_required
def transaction_delete(request, transaction_id):
    transaction = get_object_or_404(Transaction, pk=transaction_id, user=request.user)

    if request.method == 'POST':
        transaction.delete()  # post_delete signal handles balance reversal.
        return redirect('transaction_list')

    return render(request, 'transactions/transaction_delete.html', {
        'transaction': transaction,
    })


@login_required
def transaction_bulk_action(request):
    if request.method != 'POST':
        return redirect('transaction_list')

    action = request.POST.get('bulk_action', '').strip()
    ids_raw = request.POST.getlist('transaction_ids')

    ids = [int(i) for i in ids_raw if i.strip().isdigit()]

    if not ids or action not in ('categorize', 'delete', 'tag', 'score'):
        return redirect('transaction_list')

    # Only operate on this user's transactions
    transactions = Transaction.objects.filter(user=request.user, pk__in=ids)

    if action == 'delete':
        # Call .delete() per transaction so post_delete signal fires (balance updates)
        for txn in list(transactions):
            txn.delete()

    elif action == 'categorize':
        bucket_id = request.POST.get('bulk_bucket', '').strip()
        if bucket_id == '__none__':
            transactions.update(bucket=None)
        elif bucket_id:
            try:
                bucket = Bucket.objects.get(pk=bucket_id, user=request.user)
                transactions.update(bucket=bucket)
            except Bucket.DoesNotExist:
                pass

    elif action == 'tag':
        tags_raw = request.POST.get('bulk_tags', '').strip()
        if tags_raw:
            tags = _resolve_tags(request.user, tags_raw)
            for txn in transactions:
                txn.tags.add(*tags)

    elif action == 'score':
        score_str = request.POST.get('bulk_score', '').strip()
        if score_str:
            try:
                score = int(score_str)
                if 1 <= score <= 10:
                    transactions.update(necessity_score=score)
            except ValueError:
                pass

    # Preserve active filters in the redirect
    filter_keys = ['date_from', 'date_to', 'bucket', 'type', 'account', 'search', 'tag', 'page']
    filter_params = {k: request.POST.get(k, '') for k in filter_keys if request.POST.get(k, '')}
    redirect_url = reverse('transaction_list')
    if filter_params:
        redirect_url += '?' + urlencode(filter_params)
    return redirect(redirect_url)
