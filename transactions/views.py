import csv
import datetime
import hashlib
import io
import json
import uuid
from decimal import Decimal, InvalidOperation
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Max, Q, Sum
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from banking.models import BankAccount
from buckets.models import Bucket

from .models import CsvColumnMapping, IncomeSource, RecurringTransaction, Tag, Transaction, VendorMapping

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
        qs = qs.filter(
            Q(description__icontains=search) | Q(vendor__icontains=search) | Q(notes__icontains=search)
        )
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

    try:
        page_size = int(request.GET.get('page_size', 25))
    except (ValueError, TypeError):
        page_size = 25
    if page_size not in (25, 50, 100):
        page_size = 25

    paginator = Paginator(all_txns, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    today = datetime.date.today()

    # Parse selected summary month/year from GET params (default to current month)
    try:
        summary_year = int(request.GET.get('summary_year', today.year))
        summary_month = int(request.GET.get('summary_month', today.month))
        if not (1 <= summary_month <= 12 and summary_year >= 2000):
            summary_year, summary_month = today.year, today.month
    except (ValueError, TypeError):
        summary_year, summary_month = today.year, today.month

    selected_month_date = datetime.date(summary_year, summary_month, 1)

    # Stats reflect the selected month across all user transactions (unaffected by filters)
    month_qs = Transaction.objects.filter(
        user=request.user, date__year=summary_year, date__month=summary_month
    )
    total_income = month_qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = month_qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    net = total_income - total_expenses

    # Additional summary stats for selected month
    non_transfer_qs = month_qs.exclude(transaction_type='transfer')
    txn_count = non_transfer_qs.count()
    total_all = non_transfer_qs.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    avg_txn_amount = (total_all / txn_count).quantize(Decimal('0.01')) if txn_count > 0 else Decimal('0')
    largest_expense = month_qs.filter(transaction_type='expense').aggregate(m=Max('amount'))['m'] or Decimal('0')

    # Build prev/next month links
    if summary_month == 1:
        prev_year, prev_month = summary_year - 1, 12
    else:
        prev_year, prev_month = summary_year, summary_month - 1
    if summary_month == 12:
        next_year, next_month = summary_year + 1, 1
    else:
        next_year, next_month = summary_year, summary_month + 1

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
    if page_size != 25:
        filter_params['page_size'] = page_size
    # Preserve summary month selection in pagination and filter links
    if summary_year != today.year or summary_month != today.month:
        filter_params['summary_year'] = summary_year
        filter_params['summary_month'] = summary_month
    filter_qs = urlencode(filter_params)
    filter_qs_no_search = urlencode({k: v for k, v in filter_params.items() if k != 'search'})

    # Build prev/next month query strings (preserve current filters, strip summary month params)
    base_month_params = {k: v for k, v in filter_params.items() if k not in ('summary_year', 'summary_month', 'page')}

    prev_month_params = dict(base_month_params)
    prev_month_params['summary_year'] = prev_year
    prev_month_params['summary_month'] = prev_month
    prev_month_qs = urlencode(prev_month_params)

    next_month_params = dict(base_month_params)
    next_month_params['summary_year'] = next_year
    next_month_params['summary_month'] = next_month
    next_month_qs = urlencode(next_month_params)

    # Query string for "Today" link — same filters but no summary month override
    today_qs = urlencode(base_month_params)

    # Build a condensed page range for the template: always show first/last,
    # current ±2, with None as ellipsis sentinel.
    num_pages = paginator.num_pages
    current_page = page_obj.number
    page_range = []
    if num_pages <= 7:
        page_range = list(range(1, num_pages + 1))
    else:
        pages_set = sorted({1, 2, current_page - 2, current_page - 1, current_page,
                            current_page + 1, current_page + 2, num_pages - 1, num_pages})
        pages_set = [p for p in pages_set if 1 <= p <= num_pages]
        prev = None
        for p in pages_set:
            if prev is not None and p - prev > 1:
                page_range.append(None)  # ellipsis
            page_range.append(p)
            prev = p

    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    tags = Tag.objects.filter(user=request.user).order_by('name')

    # Income by source for selected month
    income_by_source = []
    if total_income > 0:
        source_rows = (
            month_qs.filter(transaction_type='income')
            .values('income_source__id', 'income_source__name', 'income_source__color')
            .annotate(total=Sum('amount'))
            .order_by('-total')
        )
        for row in source_rows:
            income_by_source.append({
                'id': row['income_source__id'],
                'name': row['income_source__name'] or 'Uncategorized',
                'color': row['income_source__color'] or '#74b9ff',
                'total': row['total'],
                'pct': round(row['total'] / total_income * 100),
            })

    return render(request, 'transactions/transaction_list.html', {
        'page_obj': page_obj,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': net,
        'txn_count': txn_count,
        'avg_txn_amount': avg_txn_amount,
        'largest_expense': largest_expense,
        'current_month': selected_month_date.strftime('%B %Y'),
        'is_current_month': (summary_year == today.year and summary_month == today.month),
        'prev_month_qs': prev_month_qs,
        'next_month_qs': next_month_qs,
        'today_qs': today_qs,
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
        'filter_qs_no_search': filter_qs_no_search,
        'balance_is_absolute': bool(account_id),
        'income_by_source': income_by_source,
        'page_size': page_size,
        'page_range': page_range,
    })


@login_required
def transaction_export_csv(request):
    """Stream filtered transactions as a CSV download."""
    qs = Transaction.objects.filter(user=request.user).select_related('account', 'bucket').prefetch_related('tags').order_by('-date', '-created_at')

    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()
    bucket_id = request.GET.get('bucket', '').strip()
    txn_type = request.GET.get('type', '').strip()
    account_id = request.GET.get('account', '').strip()
    search = request.GET.get('search', '').strip()
    tag_id = request.GET.get('tag', '').strip()

    if date_from:
        try:
            qs = qs.filter(date__gte=datetime.date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            qs = qs.filter(date__lte=datetime.date.fromisoformat(date_to))
        except ValueError:
            pass
    if bucket_id:
        qs = qs.filter(bucket_id=bucket_id)
    if txn_type in ('expense', 'income'):
        qs = qs.filter(transaction_type=txn_type)
    if account_id:
        qs = qs.filter(account_id=account_id)
    if search:
        qs = qs.filter(
            Q(description__icontains=search) | Q(vendor__icontains=search) | Q(notes__icontains=search)
        )
    if tag_id:
        try:
            Tag.objects.get(pk=tag_id, user=request.user)
            qs = qs.filter(tags__id=tag_id).distinct()
        except Tag.DoesNotExist:
            pass

    def _csv_rows(queryset):
        class _EchoBuf:
            def write(self, val):
                return val

        writer = csv.writer(_EchoBuf())
        yield writer.writerow(['date', 'description', 'vendor', 'amount', 'type', 'bucket', 'account', 'necessity_score', 'tags'])
        for txn in queryset.iterator():
            tag_names = ', '.join(t.name for t in txn.tags.all())
            yield writer.writerow([
                txn.date.isoformat(),
                txn.description,
                txn.vendor,
                str(txn.amount),
                txn.transaction_type,
                txn.bucket.name if txn.bucket else '',
                txn.account.name if txn.account else '',
                txn.necessity_score if txn.necessity_score is not None else '',
                tag_names,
            ])

    response = StreamingHttpResponse(_csv_rows(qs), content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="transactions.csv"'
    return response


@login_required
def transaction_add(request):
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    user_tags = Tag.objects.filter(user=request.user).order_by('name')
    income_sources = IncomeSource.objects.filter(user=request.user, is_active=True).order_by('name')
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
        income_source_id = request.POST.get('income_source', '').strip()

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
            'income_source': income_source_id,
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

        # Validate income_source (optional, income only)
        income_source = None
        if income_source_id and transaction_type == 'income':
            try:
                income_source = income_sources.get(pk=income_source_id)
            except IncomeSource.DoesNotExist:
                errors['income_source'] = 'Please select a valid income source.'

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
                    'income_sources': income_sources,
                    'vendor_mappings_json': json.dumps(vendor_mappings),
                    'duplicate_warning': duplicate_warning,
                })

            receipt = request.FILES.get('receipt') or None
            txn = Transaction.objects.create(
                user=request.user,
                account=account,
                bucket=bucket,
                income_source=income_source,
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
        'income_sources': income_sources,
        'vendor_mappings_json': json.dumps(vendor_mappings),
    })


@login_required
def transaction_edit(request, transaction_id):
    transaction = get_object_or_404(Transaction, pk=transaction_id, user=request.user)

    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    user_tags = Tag.objects.filter(user=request.user).order_by('name')
    income_sources = IncomeSource.objects.filter(user=request.user, is_active=True).order_by('name')

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
        income_source_id = request.POST.get('income_source', '').strip()

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
            'income_source': income_source_id,
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

        # Validate income_source (optional, income only)
        income_source = None
        if income_source_id and transaction_type == 'income':
            try:
                income_source = income_sources.get(pk=income_source_id)
            except IncomeSource.DoesNotExist:
                errors['income_source'] = 'Please select a valid income source.'

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
            transaction.income_source = income_source
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
            'income_source': str(transaction.income_source_id) if transaction.income_source_id else '',
        }

    return render(request, 'transactions/transaction_edit.html', {
        'transaction': transaction,
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
        'user_tags': user_tags,
        'income_sources': income_sources,
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


# ── CSV column-mapping helpers ────────────────────────────────────────────────

# Maps normalised CSV header names to transaction fields
_CSV_AUTO_DETECT = {
    'date': 'date',
    'transaction date': 'date',
    'trans date': 'date',
    'trans. date': 'date',
    'posting date': 'date',
    'value date': 'date',
    'amount': 'amount',
    'transaction amount': 'amount',
    'description': 'description',
    'desc': 'description',
    'memo': 'description',
    'narration': 'description',
    'details': 'description',
    'transaction description': 'description',
    'particulars': 'description',
    'category': 'category',
    'bucket': 'category',
    'type': 'type',
    'transaction type': 'type',
    'trans type': 'type',
    'vendor': 'vendor',
    'merchant': 'vendor',
    'payee': 'vendor',
}

CSV_FIELD_CHOICES = [
    ('', '— ignore —'),
    ('date', 'Date'),
    ('amount', 'Amount'),
    ('description', 'Description / Memo'),
    ('category', 'Category / Bucket'),
    ('type', 'Transaction Type'),
    ('vendor', 'Vendor / Merchant'),
]

_CSV_REQUIRED_FIELDS = {'date', 'amount', 'description'}


def _csv_source_key(headers):
    """SHA-1 of sorted normalised headers — fingerprints a CSV format."""
    normalized = sorted(h.strip().lower() for h in headers)
    return hashlib.sha1(','.join(normalized).encode()).hexdigest()


def _auto_detect_csv_mapping(headers):
    """Return {header: field} auto-detection for recognised column names."""
    return {h: _CSV_AUTO_DETECT[h.lower()] for h in headers if h.lower() in _CSV_AUTO_DETECT}


def _parse_csv_rows(raw_rows, user_mapping, bucket_map, vendor_map=None):
    """Apply user_mapping to raw_rows and return (preview_rows, importable_rows).

    vendor_map: optional dict of {vendor_name.lower(): Bucket} built from VendorMapping.
    When provided, rows without a category-column match are auto-categorized by vendor name.
    """
    date_col = next((h for h, f in user_mapping.items() if f == 'date'), None)
    amount_col = next((h for h, f in user_mapping.items() if f == 'amount'), None)
    desc_col = next((h for h, f in user_mapping.items() if f == 'description'), None)
    cat_col = next((h for h, f in user_mapping.items() if f == 'category'), None)
    type_col = next((h for h, f in user_mapping.items() if f == 'type'), None)
    vendor_col = next((h for h, f in user_mapping.items() if f == 'vendor'), None)

    preview_rows = []
    importable_rows = []

    for row_num, raw_row in enumerate(raw_rows, start=2):
        date_raw = raw_row.get(date_col, '') if date_col else ''
        amount_raw = raw_row.get(amount_col, '') if amount_col else ''
        description_raw = raw_row.get(desc_col, '') if desc_col else ''
        category_raw = raw_row.get(cat_col, '') if cat_col else ''
        vendor_raw = raw_row.get(vendor_col, '') if vendor_col else ''

        parse_errors = []

        # Validate date
        date_val = None
        if not date_raw:
            parse_errors.append('missing date')
        else:
            for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y', '%m-%d-%Y'):
                try:
                    date_val = datetime.datetime.strptime(date_raw, fmt).date()
                    break
                except ValueError:
                    pass
            if date_val is None:
                parse_errors.append(f'unrecognised date "{date_raw}"')

        # Validate description
        if not description_raw:
            parse_errors.append('missing description')

        # Validate amount
        amount_val = None
        if not amount_raw:
            parse_errors.append('missing amount')
        else:
            try:
                amount_val = Decimal(amount_raw.replace(',', ''))
            except InvalidOperation:
                parse_errors.append(f'invalid amount "{amount_raw}"')

        # Derive transaction type
        txn_type = None
        if type_col:
            raw_type = raw_row.get(type_col, '').lower()
            if raw_type in ('expense', 'debit', 'dr'):
                txn_type = 'expense'
            elif raw_type in ('income', 'credit', 'cr'):
                txn_type = 'income'

        if txn_type is None and amount_val is not None:
            txn_type = 'income' if amount_val > 0 else 'expense'

        if amount_val is not None:
            amount_val = abs(amount_val)

        # Match category to bucket — first by category column, then by vendor mapping
        matched_bucket = None
        match_source = ''
        if category_raw:
            matched_bucket = bucket_map.get(category_raw.lower())
            if matched_bucket:
                match_source = 'category'

        if matched_bucket is None and vendor_map:
            lookup = vendor_raw or description_raw
            if lookup:
                matched_bucket = vendor_map.get(lookup.lower())
                if matched_bucket:
                    match_source = 'vendor'

        status = 'error' if parse_errors else 'ok'

        preview_row = {
            'row_num': row_num,
            'date': date_val.isoformat() if date_val else date_raw,
            'description': description_raw,
            'vendor': vendor_raw,
            'amount': str(amount_val) if amount_val is not None else amount_raw,
            'transaction_type': txn_type or '',
            'category': category_raw,
            'bucket_name': matched_bucket.name if matched_bucket else '',
            'bucket_id': matched_bucket.pk if matched_bucket else None,
            'match_source': match_source,
            'status': status,
            'error': '; '.join(parse_errors),
        }
        preview_rows.append(preview_row)
        if status == 'ok':
            importable_rows.append(preview_row)

    return preview_rows, importable_rows


@login_required
def transaction_import_csv(request):
    """CSV import: upload → column mapping → preview → confirm → done."""
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')
    bucket_map = {b.name.lower(): b for b in buckets}

    if request.method == 'POST':
        step = request.POST.get('step', 'upload')

        # ── Step 1: parse file headers, show column-mapping form ─────────────
        if step == 'upload':
            errors = {}
            account = None
            account_id = request.POST.get('account', '').strip()

            csv_file = request.FILES.get('csv_file')
            if not csv_file:
                errors['csv_file'] = 'Please select a CSV file.'
            elif not (csv_file.name.lower().endswith('.csv') or csv_file.content_type in ('text/csv', 'application/csv')):
                errors['csv_file'] = 'File must be a CSV (.csv).'

            if not account_id:
                errors['account'] = 'Account is required.'
            else:
                try:
                    account = accounts.get(pk=account_id)
                except BankAccount.DoesNotExist:
                    errors['account'] = 'Please select a valid account.'

            if errors:
                return render(request, 'transactions/transaction_import.html', {
                    'accounts': accounts,
                    'errors': errors,
                    'form_data': {'account': account_id},
                })

            # Decode file (handle optional UTF-8 BOM)
            raw_bytes = csv_file.read()
            try:
                decoded = raw_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                decoded = raw_bytes.decode('latin-1')

            reader = csv.DictReader(io.StringIO(decoded))

            if reader.fieldnames is None:
                return render(request, 'transactions/transaction_import.html', {
                    'accounts': accounts,
                    'errors': {'csv_file': 'CSV file appears to be empty or has no header row.'},
                    'form_data': {'account': account_id},
                })

            # Normalise headers to lowercase, stripped
            headers = [h.strip().lower() for h in reader.fieldnames]

            # Read all raw rows (use normalised keys)
            raw_rows = []
            for raw_row in reader:
                raw_rows.append({k.strip().lower(): (v.strip() if v else '') for k, v in raw_row.items() if k})

            if not raw_rows:
                return render(request, 'transactions/transaction_import.html', {
                    'accounts': accounts,
                    'errors': {'csv_file': 'CSV file contains no data rows.'},
                    'form_data': {'account': account_id},
                })

            source_key = _csv_source_key(headers)

            # Load saved mapping or auto-detect
            saved_mapping_found = False
            try:
                saved = CsvColumnMapping.objects.get(user=request.user, source_key=source_key)
                column_mapping = saved.mapping
                saved_mapping_found = True
            except CsvColumnMapping.DoesNotExist:
                column_mapping = _auto_detect_csv_mapping(headers)

            # Build per-column info: name, sample values, suggested field
            sample_rows = raw_rows[:3]
            columns = [
                {
                    'name': h,
                    'samples': [r.get(h, '') for r in sample_rows],
                    'field': column_mapping.get(h, ''),
                }
                for h in headers
            ]

            return render(request, 'transactions/transaction_import.html', {
                'accounts': accounts,
                'step': 'mapping',
                'account': account,
                'account_id': account_id,
                'columns': columns,
                'saved_mapping_found': saved_mapping_found,
                'raw_rows_json': json.dumps(raw_rows),
                'source_key': source_key,
                'field_choices': CSV_FIELD_CHOICES,
            })

        # ── Step 2: apply mapping, show preview ──────────────────────────────
        elif step == 'mapping':
            account_id = request.POST.get('account_id', '').strip()
            raw_rows_json = request.POST.get('raw_rows_json', '[]')
            source_key = request.POST.get('source_key', '')
            remember = request.POST.get('remember_mapping') == '1'

            try:
                account = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                return redirect('transaction_import_csv')

            try:
                raw_rows = json.loads(raw_rows_json)
            except (json.JSONDecodeError, ValueError):
                return redirect('transaction_import_csv')

            if not raw_rows:
                return redirect('transaction_import_csv')

            headers = list(raw_rows[0].keys()) if raw_rows else []

            # Build mapping from POST: map_{header} → field
            user_mapping = {}
            for header in headers:
                field = request.POST.get(f'map_{header}', '').strip()
                if field:
                    user_mapping[header] = field

            # Validate required fields are covered
            mapped_fields = set(user_mapping.values())
            missing_required = _CSV_REQUIRED_FIELDS - mapped_fields
            if missing_required:
                sample_rows = raw_rows[:3]
                columns = [
                    {
                        'name': h,
                        'samples': [r.get(h, '') for r in sample_rows],
                        'field': user_mapping.get(h, ''),
                    }
                    for h in headers
                ]
                return render(request, 'transactions/transaction_import.html', {
                    'accounts': accounts,
                    'step': 'mapping',
                    'account': account,
                    'account_id': account_id,
                    'columns': columns,
                    'saved_mapping_found': False,
                    'raw_rows_json': raw_rows_json,
                    'source_key': source_key,
                    'field_choices': CSV_FIELD_CHOICES,
                    'mapping_errors': f'Please map the following required fields: {", ".join(sorted(missing_required))}.',
                })

            # Persist mapping if requested
            if remember and source_key:
                CsvColumnMapping.objects.update_or_create(
                    user=request.user,
                    source_key=source_key,
                    defaults={'mapping': user_mapping},
                )

            vendor_map = {
                vm.vendor_name.lower(): vm.bucket
                for vm in VendorMapping.objects.filter(
                    user=request.user,
                ).select_related('bucket')
                if vm.bucket_id
            }

            preview_rows, importable_rows = _parse_csv_rows(raw_rows, user_mapping, bucket_map, vendor_map)
            ok_count = sum(1 for r in preview_rows if r['status'] == 'ok')
            error_count = sum(1 for r in preview_rows if r['status'] == 'error')

            return render(request, 'transactions/transaction_import.html', {
                'accounts': accounts,
                'step': 'preview',
                'preview_rows': preview_rows,
                'ok_count': ok_count,
                'error_count': error_count,
                'account': account,
                'buckets': buckets,
                'rows_json': json.dumps(importable_rows),
            })

        # ── Step 3: user confirmed — import the valid rows ───────────────────
        elif step == 'confirm':
            account_id = request.POST.get('account_id', '').strip()
            rows_json = request.POST.get('rows_json', '[]')

            try:
                account = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                return redirect('transaction_import_csv')

            try:
                rows_data = json.loads(rows_json)
            except (json.JSONDecodeError, ValueError):
                return redirect('transaction_import_csv')

            imported = 0
            skipped = 0

            for row in rows_data:
                if row.get('status') != 'ok':
                    skipped += 1
                    continue

                # Prefer bucket override from the per-row dropdown in the preview form
                override_key = f'bucket_{row["row_num"]}'
                bucket = None
                if override_key in request.POST:
                    override_val = request.POST[override_key].strip()
                    if override_val:
                        try:
                            bucket = buckets.get(pk=int(override_val))
                        except (ValueError, Bucket.DoesNotExist):
                            bucket = None
                else:
                    # Fall back to auto-matched bucket stored in rows_json
                    if row.get('bucket_id'):
                        try:
                            bucket = buckets.get(pk=row['bucket_id'])
                        except Bucket.DoesNotExist:
                            pass

                try:
                    Transaction.objects.create(
                        user=request.user,
                        account=account,
                        bucket=bucket,
                        amount=Decimal(row['amount']),
                        transaction_type=row['transaction_type'],
                        description=row['description'],
                        vendor=row.get('vendor', ''),
                        date=datetime.date.fromisoformat(row['date']),
                    )
                    imported += 1

                    # Learn vendor→bucket mapping for future imports
                    vendor_name = row.get('vendor', '').strip()
                    if vendor_name and bucket:
                        existing = VendorMapping.objects.filter(
                            user=request.user, vendor_name__iexact=vendor_name,
                        ).first()
                        if existing:
                            existing.bucket = bucket
                            existing.save()
                        else:
                            VendorMapping.objects.create(
                                user=request.user, vendor_name=vendor_name[:100], bucket=bucket,
                            )
                except Exception:
                    skipped += 1

            return render(request, 'transactions/transaction_import.html', {
                'accounts': accounts,
                'step': 'done',
                'imported': imported,
                'skipped': skipped,
            })

    # GET — show upload form
    return render(request, 'transactions/transaction_import.html', {
        'accounts': accounts,
    })


# ── Income Source CRUD ────────────────────────────────────────────────────────

INCOME_SOURCE_COLORS = [
    '#0984e3', '#00d4aa', '#f9ca24', '#ff4757',
    '#a29bfe', '#fd79a8', '#55efc4', '#fdcb6e',
    '#e17055', '#74b9ff',
]


@login_required
def income_source_list(request):
    sources = IncomeSource.objects.filter(user=request.user).order_by('name')
    return render(request, 'transactions/income_source_list.html', {'sources': sources})


@login_required
def income_source_add(request):
    errors = {}
    form_data = {'name': '', 'color': '#0984e3', 'is_active': True}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#0984e3').strip()
        is_active = request.POST.get('is_active', '') == '1'

        form_data = {'name': name, 'color': color, 'is_active': is_active}

        if not name:
            errors['name'] = 'Name is required.'
        elif IncomeSource.objects.filter(user=request.user, name__iexact=name).exists():
            errors['name'] = 'An income source with this name already exists.'

        if not color or len(color) != 7 or not color.startswith('#'):
            errors['color'] = 'Please select a valid color.'

        if not errors:
            IncomeSource.objects.create(
                user=request.user,
                name=name,
                color=color,
                is_active=is_active,
            )
            return redirect('income_source_list')

    return render(request, 'transactions/income_source_add.html', {
        'errors': errors,
        'form_data': form_data,
        'color_palette': INCOME_SOURCE_COLORS,
    })


@login_required
def income_source_edit(request, source_id):
    source = get_object_or_404(IncomeSource, pk=source_id, user=request.user)
    errors = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        color = request.POST.get('color', '#0984e3').strip()
        is_active = request.POST.get('is_active', '') == '1'

        form_data = {'name': name, 'color': color, 'is_active': is_active}

        if not name:
            errors['name'] = 'Name is required.'
        elif IncomeSource.objects.filter(user=request.user, name__iexact=name).exclude(pk=source_id).exists():
            errors['name'] = 'An income source with this name already exists.'

        if not color or len(color) != 7 or not color.startswith('#'):
            errors['color'] = 'Please select a valid color.'

        if not errors:
            source.name = name
            source.color = color
            source.is_active = is_active
            source.save()
            return redirect('income_source_list')
    else:
        form_data = {
            'name': source.name,
            'color': source.color,
            'is_active': source.is_active,
        }

    return render(request, 'transactions/income_source_edit.html', {
        'source': source,
        'errors': errors,
        'form_data': form_data,
        'color_palette': INCOME_SOURCE_COLORS,
    })


@login_required
def income_source_delete(request, source_id):
    source = get_object_or_404(IncomeSource, pk=source_id, user=request.user)

    if request.method == 'POST':
        source.delete()
        return redirect('income_source_list')

    txn_count = source.transactions.count()
    return render(request, 'transactions/income_source_delete.html', {
        'source': source,
        'txn_count': txn_count,
    })


_MONTHLY_MULTIPLIERS = {
    'daily': Decimal('30'),
    'weekly': Decimal('4.333'),
    'biweekly': Decimal('2.167'),
    'monthly': Decimal('1'),
    'yearly': Decimal('0.0833'),
}


def _monthly_cost(recurring):
    return recurring.amount * _MONTHLY_MULTIPLIERS.get(recurring.frequency, Decimal('1'))


@login_required
def recurring_list(request):
    qs = RecurringTransaction.objects.filter(user=request.user).select_related('account', 'bucket')

    filter_bucket = request.GET.get('bucket', '').strip()
    filter_frequency = request.GET.get('frequency', '').strip()
    filter_type = request.GET.get('type', '').strip()
    filter_status = request.GET.get('status', '').strip()

    if filter_bucket:
        qs = qs.filter(bucket_id=filter_bucket)
    if filter_frequency:
        qs = qs.filter(frequency=filter_frequency)
    if filter_type:
        qs = qs.filter(transaction_type=filter_type)
    if filter_status == 'active':
        qs = qs.filter(is_active=True)
    elif filter_status == 'inactive':
        qs = qs.filter(is_active=False)

    recurring = list(qs)
    total_monthly = sum(_monthly_cost(r) for r in recurring if r.is_active)

    buckets = Bucket.objects.filter(user=request.user).order_by('name')

    return render(request, 'transactions/recurring_list.html', {
        'recurring': recurring,
        'total_monthly': total_monthly,
        'buckets': buckets,
        'filter_bucket': filter_bucket,
        'filter_frequency': filter_frequency,
        'filter_type': filter_type,
        'filter_status': filter_status,
        'frequency_choices': RecurringTransaction.FREQUENCY_CHOICES,
        'type_choices': RecurringTransaction.TRANSACTION_TYPE_CHOICES,
    })


@login_required
def recurring_add(request):
    errors = {}
    accounts = BankAccount.objects.filter(user=request.user).order_by('name')
    buckets = Bucket.objects.filter(user=request.user).order_by('name')

    today = datetime.date.today().isoformat()
    form_data = {
        'transaction_type': 'expense',
        'frequency': 'monthly',
        'start_date': today,
        'is_active': True,
    }

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        vendor = request.POST.get('vendor', '').strip()
        amount_str = request.POST.get('amount', '').strip()
        transaction_type = request.POST.get('transaction_type', '').strip()
        frequency = request.POST.get('frequency', '').strip()
        start_date_str = request.POST.get('start_date', '').strip()
        end_date_str = request.POST.get('end_date', '').strip()
        account_id = request.POST.get('account', '').strip()
        bucket_id = request.POST.get('bucket', '').strip()
        is_active = request.POST.get('is_active', '') == '1'

        form_data = {
            'description': description, 'vendor': vendor, 'amount': amount_str,
            'transaction_type': transaction_type, 'frequency': frequency,
            'start_date': start_date_str,
            'end_date': end_date_str, 'account': account_id, 'bucket': bucket_id,
            'is_active': is_active,
        }

        if not description:
            errors['description'] = 'Description is required.'

        amount = None
        if not amount_str:
            errors['amount'] = 'Amount is required.'
        else:
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    errors['amount'] = 'Amount must be greater than zero.'
            except InvalidOperation:
                errors['amount'] = 'Enter a valid amount.'

        if not transaction_type or transaction_type not in [c[0] for c in RecurringTransaction.TRANSACTION_TYPE_CHOICES]:
            errors['transaction_type'] = 'Please select a valid type.'

        if not frequency or frequency not in [c[0] for c in RecurringTransaction.FREQUENCY_CHOICES]:
            errors['frequency'] = 'Please select a valid frequency.'

        account = None
        if not account_id:
            errors['account'] = 'Account is required.'
        else:
            try:
                account = accounts.get(pk=account_id)
            except BankAccount.DoesNotExist:
                errors['account'] = 'Please select a valid account.'

        start_date = None
        if not start_date_str:
            errors['start_date'] = 'Start date is required.'
        else:
            try:
                start_date = datetime.date.fromisoformat(start_date_str)
            except ValueError:
                errors['start_date'] = 'Enter a valid date.'

        end_date = None
        if end_date_str:
            try:
                end_date = datetime.date.fromisoformat(end_date_str)
            except ValueError:
                errors['end_date'] = 'Enter a valid date.'

        bucket = None
        if bucket_id:
            try:
                bucket = buckets.get(pk=bucket_id)
            except Bucket.DoesNotExist:
                errors['bucket'] = 'Please select a valid bucket.'

        if not errors:
            RecurringTransaction.objects.create(
                user=request.user,
                account=account,
                bucket=bucket,
                amount=amount,
                transaction_type=transaction_type,
                description=description,
                vendor=vendor,
                frequency=frequency,
                start_date=start_date,
                next_due=start_date,
                end_date=end_date,
                is_active=is_active,
            )
            return redirect('recurring_list')

    return render(request, 'transactions/recurring_add.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
        'frequency_choices': RecurringTransaction.FREQUENCY_CHOICES,
        'type_choices': RecurringTransaction.TRANSACTION_TYPE_CHOICES,
    })


@login_required
def recurring_toggle(request, recurring_id):
    rt = get_object_or_404(RecurringTransaction, pk=recurring_id, user=request.user)
    if request.method == 'POST':
        rt.is_active = not rt.is_active
        rt.save(update_fields=['is_active'])
    return redirect('recurring_list')


@login_required
def recurring_delete(request, recurring_id):
    rt = get_object_or_404(RecurringTransaction, pk=recurring_id, user=request.user)
    if request.method == 'POST':
        rt.delete()
        return redirect('recurring_list')
    return render(request, 'transactions/recurring_delete.html', {'rt': rt})
