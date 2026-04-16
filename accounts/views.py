import csv
import io
import zipfile

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, update_session_auth_hash, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib import messages
from django.urls import reverse_lazy

from banking.models import BankAccount
from .models import UserPreferences

User = get_user_model()


def login_view(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')

    errors = {}
    form_data = {}

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')

        form_data = {'email': email}

        if not email:
            errors['email'] = 'Email is required.'

        if not password:
            errors['password'] = 'Password is required.'

        if not errors:
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                return redirect('/dashboard/')
            else:
                errors['__all__'] = 'Invalid email or password.'

    return render(request, 'accounts/login.html', {
        'errors': errors,
        'form_data': form_data,
    })


def register(request):
    errors = {}
    form_data = {}

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        form_data = {'email': email, 'first_name': first_name}

        if not email:
            errors['email'] = 'Email is required.'
        elif User.objects.filter(email=email).exists():
            errors['email'] = 'An account with this email already exists.'

        if not first_name:
            errors['first_name'] = 'First name is required.'

        if not password:
            errors['password'] = 'Password is required.'
        elif len(password) < 8:
            errors['password'] = 'Password must be at least 8 characters.'

        if not password_confirm:
            errors['password_confirm'] = 'Please confirm your password.'
        elif password and password != password_confirm:
            errors['password_confirm'] = 'Passwords do not match.'

        if not errors:
            user = User.objects.create_user(
                email=email,
                first_name=first_name,
                password=password,
            )
            login(request, user)
            return redirect('/dashboard/')

    return render(request, 'accounts/register.html', {
        'errors': errors,
        'form_data': form_data,
    })


CURRENCY_CHOICES = [
    ('USD', 'USD — US Dollar'),
    ('EUR', 'EUR — Euro'),
    ('GBP', 'GBP — British Pound'),
    ('CAD', 'CAD — Canadian Dollar'),
    ('AUD', 'AUD — Australian Dollar'),
    ('JPY', 'JPY — Japanese Yen'),
]


@login_required
def profile(request):
    errors = {}
    success = False

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        currency = request.POST.get('currency', '').strip()
        monthly_income = request.POST.get('monthly_income', '').strip()
        zero_based_budgeting = request.POST.get('zero_based_budgeting') == 'on'

        if not first_name:
            errors['first_name'] = 'First name is required.'

        valid_currencies = [c[0] for c in CURRENCY_CHOICES]
        if currency not in valid_currencies:
            errors['currency'] = 'Please select a valid currency.'

        if monthly_income:
            try:
                monthly_income_val = float(monthly_income)
                if monthly_income_val < 0:
                    errors['monthly_income'] = 'Monthly income cannot be negative.'
            except ValueError:
                errors['monthly_income'] = 'Please enter a valid number.'
        else:
            monthly_income_val = 0

        if not errors:
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.currency = currency
            request.user.monthly_income = monthly_income_val
            request.user.zero_based_budgeting = zero_based_budgeting
            request.user.save()
            success = True

    return render(request, 'accounts/profile.html', {
        'errors': errors,
        'success': success,
        'currency_choices': CURRENCY_CHOICES,
    })


@login_required
def settings(request):
    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    errors = {}

    if request.method == 'POST':
        email_weekly_digest = request.POST.get('email_weekly_digest') == 'on'
        email_budget_alerts = request.POST.get('email_budget_alerts') == 'on'
        email_goal_achieved = request.POST.get('email_goal_achieved') == 'on'
        start_of_week = request.POST.get('start_of_week', 'monday')
        fiscal_month_start = request.POST.get('fiscal_month_start', '1')
        default_account_id = request.POST.get('default_account', '')
        theme = request.POST.get('theme', 'dark')

        valid_weeks = [c[0] for c in UserPreferences.START_OF_WEEK_CHOICES]
        if start_of_week not in valid_weeks:
            errors['start_of_week'] = 'Please select a valid day.'

        valid_themes = [c[0] for c in UserPreferences.THEME_CHOICES]
        if theme not in valid_themes:
            theme = 'dark'

        try:
            fiscal_month_start_val = int(fiscal_month_start)
            if not (1 <= fiscal_month_start_val <= 28):
                errors['fiscal_month_start'] = 'Day must be between 1 and 28.'
        except (ValueError, TypeError):
            errors['fiscal_month_start'] = 'Please enter a valid day number.'
            fiscal_month_start_val = 1

        default_account = None
        if default_account_id:
            try:
                default_account = BankAccount.objects.get(pk=default_account_id, user=request.user)
            except BankAccount.DoesNotExist:
                errors['default_account'] = 'Invalid account selected.'

        if not errors:
            prefs.email_weekly_digest = email_weekly_digest
            prefs.email_budget_alerts = email_budget_alerts
            prefs.email_goal_achieved = email_goal_achieved
            prefs.start_of_week = start_of_week
            prefs.fiscal_month_start = fiscal_month_start_val
            prefs.default_account = default_account
            prefs.theme = theme
            prefs.save()
            return redirect('/settings/?saved=1#preferences')

    bank_accounts = BankAccount.objects.filter(user=request.user, is_active=True)

    return render(request, 'accounts/settings.html', {
        'prefs': prefs,
        'errors': errors,
        'week_choices': UserPreferences.START_OF_WEEK_CHOICES,
        'theme_choices': UserPreferences.THEME_CHOICES,
        'bank_accounts': bank_accounts,
    })


_IMPORT_TEMPLATES = {
    'transactions': {
        'filename': 'transactions_template.csv',
        'headers': ['date', 'description', 'vendor', 'amount', 'type', 'bucket', 'account', 'necessity_score', 'tags'],
        'example': ['2024-01-15', 'Grocery shopping', 'Whole Foods', '85.50', 'expense', 'Groceries', 'Checking', '3', 'food, weekly'],
    },
    'buckets': {
        'filename': 'buckets_template.csv',
        'headers': ['name', 'description', 'monthly_allocation', 'color', 'icon', 'sort_order', 'is_active', 'rollover', 'alert_threshold'],
        'example': ['Groceries', 'Food and household items', '500.00', '#0984e3', '🛒', '1', 'True', 'False', '90'],
    },
    'savings_goals': {
        'filename': 'savings_goals_template.csv',
        'headers': ['name', 'description', 'target_amount', 'current_amount', 'deadline', 'priority', 'goal_type', 'color', 'icon'],
        'example': ['Emergency Fund', '3 months of expenses', '10000.00', '2500.00', '2024-12-31', 'high', 'emergency_fund', '#00d4aa', '🎯'],
    },
    'bank_accounts': {
        'filename': 'bank_accounts_template.csv',
        'headers': ['name', 'account_type', 'balance', 'institution', 'color'],
        'example': ['Main Checking', 'checking', '5000.00', 'Chase Bank', '#0984e3'],
    },
}


@login_required
def download_import_template(request, data_type):
    if data_type not in _IMPORT_TEMPLATES:
        return HttpResponse('Not found', status=404)
    tmpl = _IMPORT_TEMPLATES[data_type]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(tmpl['headers'])
    w.writerow(tmpl['example'])
    response = HttpResponse(out.getvalue(), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{tmpl["filename"]}"'
    return response


def _parse_bool(val):
    return str(val).strip().lower() in ('true', '1', 'yes')


def _import_buckets(user, rows):
    from buckets.models import Bucket
    imported = 0
    for i, row in enumerate(rows, start=2):
        name = (row.get('name') or '').strip()
        if not name:
            continue
        try:
            monthly_allocation = row.get('monthly_allocation', '0').strip() or '0'
            monthly_allocation = float(monthly_allocation)
        except (ValueError, AttributeError):
            continue
        defaults = {
            'monthly_allocation': monthly_allocation,
            'description': (row.get('description') or '').strip(),
            'color': (row.get('color') or '#0984e3').strip() or '#0984e3',
            'icon': (row.get('icon') or '💰').strip() or '💰',
            'rollover': _parse_bool(row.get('rollover', 'False')),
            'is_active': _parse_bool(row.get('is_active', 'True')),
        }
        try:
            defaults['sort_order'] = int((row.get('sort_order') or '0').strip())
        except (ValueError, AttributeError):
            defaults['sort_order'] = 0
        try:
            defaults['alert_threshold'] = int((row.get('alert_threshold') or '90').strip())
        except (ValueError, AttributeError):
            defaults['alert_threshold'] = 90
        Bucket.objects.update_or_create(user=user, name=name, defaults=defaults)
        imported += 1
    return imported


def _import_bank_accounts(user, rows):
    valid_types = {'checking', 'savings', 'credit', 'cash'}
    imported = 0
    for row in rows:
        name = (row.get('name') or '').strip()
        account_type = (row.get('account_type') or '').strip().lower()
        if not name or account_type not in valid_types:
            continue
        try:
            balance = float((row.get('balance') or '0').strip())
        except (ValueError, AttributeError):
            balance = 0.0
        defaults = {
            'account_type': account_type,
            'balance': balance,
            'institution': (row.get('institution') or '').strip() or None,
            'color': (row.get('color') or '#0984e3').strip() or '#0984e3',
            'is_active': True,
        }
        BankAccount.objects.update_or_create(user=user, name=name, defaults=defaults)
        imported += 1
    return imported


def _import_savings_goals(user, rows):
    import datetime
    from savings.models import SavingsGoal
    valid_priorities = {'low', 'medium', 'high', 'critical'}
    valid_goal_types = {'general', 'emergency_fund', 'vacation', 'purchase', 'debt_payoff', 'investment', 'education', 'other'}
    imported = 0
    for row in rows:
        name = (row.get('name') or '').strip()
        if not name:
            continue
        try:
            target_amount = float((row.get('target_amount') or '0').strip())
        except (ValueError, AttributeError):
            continue
        try:
            current_amount = float((row.get('current_amount') or '0').strip())
        except (ValueError, AttributeError):
            current_amount = 0.0
        priority = (row.get('priority') or 'medium').strip().lower()
        if priority not in valid_priorities:
            priority = 'medium'
        goal_type = (row.get('goal_type') or 'general').strip().lower()
        if goal_type not in valid_goal_types:
            goal_type = 'general'
        deadline = None
        raw_deadline = (row.get('deadline') or '').strip()
        if raw_deadline:
            try:
                deadline = datetime.date.fromisoformat(raw_deadline)
            except ValueError:
                pass
        defaults = {
            'target_amount': target_amount,
            'current_amount': current_amount,
            'description': (row.get('description') or '').strip(),
            'priority': priority,
            'goal_type': goal_type,
            'deadline': deadline,
            'color': (row.get('color') or '#00d4aa').strip() or '#00d4aa',
            'icon': (row.get('icon') or '🎯').strip() or '🎯',
        }
        SavingsGoal.objects.update_or_create(user=user, name=name, defaults=defaults)
        imported += 1
    return imported


@login_required
def import_csv(request):
    if request.method != 'POST':
        return redirect('/settings/#data')

    data_type = request.POST.get('data_type', '')
    csv_file = request.FILES.get('csv_file')

    if not csv_file:
        return redirect('/settings/?import_error=no_file&data_type=' + data_type + '#data')

    try:
        raw = csv_file.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')
        reader = csv.DictReader(io.StringIO(text))
        rows = [{k.strip().lower(): v for k, v in row.items()} for row in reader]
    except Exception:
        return redirect('/settings/?import_error=invalid_file&data_type=' + data_type + '#data')

    if data_type == 'buckets':
        imported = _import_buckets(request.user, rows)
    elif data_type == 'bank_accounts':
        imported = _import_bank_accounts(request.user, rows)
    elif data_type == 'savings_goals':
        imported = _import_savings_goals(request.user, rows)
    else:
        return redirect('/settings/?import_error=unknown_type#data')

    return redirect(f'/settings/?imported={imported}&data_type={data_type}#data')


@login_required
def export_all_data(request):
    from transactions.models import Transaction, RecurringTransaction
    from buckets.models import Bucket
    from savings.models import SavingsGoal
    from budget.models import BudgetSummary

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:

        # transactions.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['date', 'description', 'vendor', 'amount', 'type', 'bucket', 'account', 'necessity_score', 'tags'])
        for t in Transaction.objects.filter(user=request.user).select_related('bucket', 'account').prefetch_related('tags').order_by('-date'):
            w.writerow([
                t.date, t.description, t.vendor or '', t.amount,
                t.transaction_type,
                t.bucket.name if t.bucket else '',
                t.account.name if t.account else '',
                t.necessity_score or '',
                ', '.join(tag.name for tag in t.tags.all()),
            ])
        zf.writestr('transactions.csv', out.getvalue())

        # buckets.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['name', 'description', 'monthly_allocation', 'color', 'icon', 'sort_order', 'is_active', 'is_uncategorized', 'rollover', 'alert_threshold'])
        for b in Bucket.objects.filter(user=request.user).order_by('sort_order', 'name'):
            w.writerow([
                b.name, b.description or '', b.monthly_allocation, b.color, b.icon,
                b.sort_order, b.is_active, b.is_uncategorized, b.rollover, b.alert_threshold,
            ])
        zf.writestr('buckets.csv', out.getvalue())

        # savings_goals.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['name', 'description', 'target_amount', 'current_amount', 'deadline', 'priority', 'goal_type', 'color', 'icon', 'is_achieved'])
        for g in SavingsGoal.objects.filter(user=request.user).order_by('name'):
            w.writerow([
                g.name, g.description or '', g.target_amount, g.current_amount,
                g.deadline or '', g.priority, g.goal_type, g.color, g.icon, g.is_achieved,
            ])
        zf.writestr('savings_goals.csv', out.getvalue())

        # budget_summaries.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['year', 'month', 'income', 'total_allocated', 'total_spent', 'total_saved', 'surplus_deficit', 'necessity_avg', 'notes'])
        for s in BudgetSummary.objects.filter(user=request.user).order_by('-year', '-month'):
            w.writerow([
                s.year, s.month, s.income, s.total_allocated, s.total_spent,
                s.total_saved, s.surplus_deficit, s.necessity_avg or '', s.notes or '',
            ])
        zf.writestr('budget_summaries.csv', out.getvalue())

        # recurring.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['description', 'vendor', 'amount', 'type', 'bucket', 'account', 'frequency', 'start_date', 'next_due', 'end_date', 'is_active', 'is_subscription', 'necessity_score'])
        for r in RecurringTransaction.objects.filter(user=request.user).select_related('bucket', 'account').order_by('description'):
            w.writerow([
                r.description, r.vendor or '', r.amount, r.transaction_type,
                r.bucket.name if r.bucket else '',
                r.account.name if r.account else '',
                r.frequency, r.start_date, r.next_due, r.end_date or '',
                r.is_active, r.is_subscription, r.necessity_score or '',
            ])
        zf.writestr('recurring.csv', out.getvalue())

        # bank_accounts.csv
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(['name', 'account_type', 'balance', 'institution', 'color', 'is_active'])
        for a in BankAccount.objects.filter(user=request.user).order_by('name'):
            w.writerow([a.name, a.account_type, a.balance, a.institution or '', a.color, a.is_active])
        zf.writestr('bank_accounts.csv', out.getvalue())

    buf.seek(0)
    response = HttpResponse(buf.read(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="bucket-budget-export.zip"'
    return response


@login_required
def delete_account(request):
    errors = {}

    if request.method == 'POST':
        confirmation = request.POST.get('confirmation', '').strip()

        if confirmation != 'DELETE':
            errors['confirmation'] = 'Please type DELETE to confirm.'

        if not errors:
            user = request.user
            logout(request)
            user.delete()
            return redirect('/')

    return render(request, 'accounts/delete_account.html', {
        'errors': errors,
    })


class ChangePasswordView(PasswordChangeView):
    template_name = 'accounts/change_password.html'
    success_url = reverse_lazy('profile')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Password changed successfully.')
        return response
