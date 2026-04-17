import csv
import io
import zipfile

import pytz

from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate, update_session_auth_hash, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib import messages
from django.urls import reverse_lazy

from banking.models import BankAccount
from buckets.models import Bucket
from .forms import LoginForm, ProfileForm, RegisterForm
from .models import UserPreferences
from .currencies import CURRENCY_CHOICES


def _form_errors(form):
    """Convert Django form errors to the flat dict used by templates."""
    return {field: errs[0] for field, errs in form.errors.items()}

TIMEZONE_CHOICES = [(tz, tz) for tz in pytz.common_timezones]

User = get_user_model()


def _post_login_redirect(request, user):
    prefs, _ = UserPreferences.objects.get_or_create(user=user)
    if not prefs.onboarding_complete and not user.bank_accounts.exists():
        return redirect('/onboarding/step1/')
    return redirect('/dashboard/')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('/dashboard/')

    errors = {}
    form_data = {}

    if request.method == 'POST':
        form = LoginForm(request.POST)
        form_data = {'email': request.POST.get('email', '')}
        if form.is_valid():
            email = form.cleaned_data['email']
            password = form.cleaned_data['password']
            user = authenticate(request, username=email, password=password)
            if user is not None:
                login(request, user)
                return _post_login_redirect(request, user)
            else:
                errors['__all__'] = 'Invalid email or password.'
        else:
            errors = _form_errors(form)

    return render(request, 'accounts/login.html', {
        'errors': errors,
        'form_data': form_data,
    })


def register(request):
    errors = {}
    form_data = {}

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        form_data = {
            'email': request.POST.get('email', ''),
            'first_name': request.POST.get('first_name', ''),
        }
        if form.is_valid():
            email = form.cleaned_data['email']
            first_name = form.cleaned_data['first_name']
            password = form.cleaned_data['password']
            if User.objects.filter(email=email).exists():
                errors['email'] = 'An account with this email already exists.'
            else:
                user = User.objects.create_user(
                    email=email,
                    first_name=first_name,
                    password=password,
                )
                login(request, user)
                return redirect('/onboarding/step1/')
        else:
            errors = _form_errors(form)

    return render(request, 'accounts/register.html', {
        'errors': errors,
        'form_data': form_data,
    })


@login_required
def profile(request):
    errors = {}
    success = False

    if request.method == 'POST':
        form = ProfileForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            request.user.first_name = cd['first_name']
            request.user.last_name = cd.get('last_name', '')
            request.user.currency = cd['currency']
            request.user.monthly_income = cd.get('monthly_income') or 0
            request.user.zero_based_budgeting = cd.get('zero_based_budgeting', False)
            request.user.save()
            success = True
        else:
            errors = _form_errors(form)

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
        default_bucket_id = request.POST.get('default_bucket', '')
        default_transaction_type = request.POST.get('default_transaction_type', 'expense')
        timezone = request.POST.get('timezone', 'UTC')

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

        default_bucket = None
        if default_bucket_id:
            try:
                default_bucket = Bucket.objects.get(pk=default_bucket_id, user=request.user)
            except Bucket.DoesNotExist:
                errors['default_bucket'] = 'Invalid bucket selected.'

        valid_types = [c[0] for c in UserPreferences.TRANSACTION_TYPE_CHOICES]
        if default_transaction_type not in valid_types:
            default_transaction_type = 'expense'

        valid_timezones = pytz.common_timezones
        if timezone not in valid_timezones:
            timezone = 'UTC'

        if not errors:
            prefs.email_weekly_digest = email_weekly_digest
            prefs.email_budget_alerts = email_budget_alerts
            prefs.email_goal_achieved = email_goal_achieved
            prefs.start_of_week = start_of_week
            prefs.fiscal_month_start = fiscal_month_start_val
            prefs.default_account = default_account
            prefs.theme = theme
            prefs.default_bucket = default_bucket
            prefs.default_transaction_type = default_transaction_type
            prefs.timezone = timezone
            prefs.save()
            return redirect('/settings/?saved=1#preferences')

    bank_accounts = BankAccount.objects.filter(user=request.user, is_active=True)
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    return render(request, 'accounts/settings.html', {
        'prefs': prefs,
        'errors': errors,
        'week_choices': UserPreferences.START_OF_WEEK_CHOICES,
        'theme_choices': UserPreferences.THEME_CHOICES,
        'transaction_type_choices': UserPreferences.TRANSACTION_TYPE_CHOICES,
        'timezone_choices': TIMEZONE_CHOICES,
        'bank_accounts': bank_accounts,
        'buckets': buckets,
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


@login_required
def save_widget_preferences(request):
    if request.method != 'POST':
        return redirect('/dashboard/')

    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    widget_keys = list(UserPreferences.WIDGET_DEFAULTS.keys())
    visibility = {key: request.POST.get(key) == 'on' for key in widget_keys}
    prefs.widget_visibility = visibility
    prefs.save()
    return redirect('/dashboard/')


@login_required
def save_no_spend_goal(request):
    if request.method != 'POST':
        return redirect('/dashboard/')

    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    try:
        goal = int(request.POST.get('no_spend_goal', 0))
        prefs.no_spend_goal = max(0, goal)
        prefs.save()
    except (ValueError, TypeError):
        pass
    return redirect('/dashboard/')


# ---------------------------------------------------------------------------
# Onboarding wizard
# ---------------------------------------------------------------------------

_ONBOARDING_STEPS = 4


def _onboarding_guard(request):
    """Return the prefs object, or a redirect response if onboarding is already done."""
    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    if prefs.onboarding_complete:
        return redirect('/dashboard/'), None
    return None, prefs


@login_required
def onboarding_step1(request):
    redirect_resp, prefs = _onboarding_guard(request)
    if redirect_resp:
        return redirect_resp

    errors = {}

    if request.method == 'POST':
        monthly_income = request.POST.get('monthly_income', '').strip()
        income_val = None

        if monthly_income:
            try:
                income_val = float(monthly_income)
                if income_val < 0:
                    errors['monthly_income'] = 'Income cannot be negative.'
            except ValueError:
                errors['monthly_income'] = 'Please enter a valid number.'

        if not errors:
            if income_val is not None:
                request.user.monthly_income = income_val
                request.user.save()
            return redirect('/onboarding/step2/')

    return render(request, 'accounts/onboarding_step1.html', {
        'errors': errors,
        'step': 1,
        'total_steps': _ONBOARDING_STEPS,
    })


@login_required
def onboarding_step2(request):
    redirect_resp, prefs = _onboarding_guard(request)
    if redirect_resp:
        return redirect_resp

    errors = {}
    form_data = {}

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        account_type = request.POST.get('account_type', '').strip()
        balance_str = request.POST.get('balance', '').strip()
        institution = request.POST.get('institution', '').strip()

        form_data = {
            'name': name,
            'account_type': account_type,
            'balance': balance_str,
            'institution': institution,
        }

        if not name:
            errors['name'] = 'Account name is required.'

        valid_types = [c[0] for c in BankAccount.ACCOUNT_TYPE_CHOICES]
        if account_type not in valid_types:
            errors['account_type'] = 'Please select an account type.'

        balance_val = 0
        if balance_str:
            try:
                balance_val = float(balance_str)
            except ValueError:
                errors['balance'] = 'Please enter a valid amount.'

        if not errors:
            BankAccount.objects.create(
                user=request.user,
                name=name,
                account_type=account_type,
                balance=balance_val,
                institution=institution or None,
            )
            return redirect('/onboarding/step3/')

    return render(request, 'accounts/onboarding_step2.html', {
        'errors': errors,
        'form_data': form_data,
        'account_type_choices': BankAccount.ACCOUNT_TYPE_CHOICES,
        'step': 2,
        'total_steps': _ONBOARDING_STEPS,
    })


@login_required
def onboarding_step3(request):
    redirect_resp, prefs = _onboarding_guard(request)
    if redirect_resp:
        return redirect_resp

    from buckets.models import Bucket

    buckets = list(
        Bucket.objects.filter(
            user=request.user,
            is_active=True,
            is_uncategorized=False,
        ).order_by('sort_order', 'name')
    )

    errors = {}

    if request.method == 'POST':
        for bucket in buckets:
            alloc_str = request.POST.get(f'allocation_{bucket.pk}', '').strip()
            if alloc_str:
                try:
                    alloc = float(alloc_str)
                    if alloc < 0:
                        errors[f'allocation_{bucket.pk}'] = 'Cannot be negative.'
                    else:
                        bucket.monthly_allocation = alloc
                        bucket.save()
                except ValueError:
                    errors[f'allocation_{bucket.pk}'] = 'Invalid amount.'

        if not errors:
            return redirect('/onboarding/step4/')

    return render(request, 'accounts/onboarding_step3.html', {
        'buckets': buckets,
        'errors': errors,
        'step': 3,
        'total_steps': _ONBOARDING_STEPS,
    })


@login_required
def onboarding_step4(request):
    import datetime as dt

    redirect_resp, prefs = _onboarding_guard(request)
    if redirect_resp:
        return redirect_resp

    from transactions.models import Transaction
    from buckets.models import Bucket

    accounts = BankAccount.objects.filter(user=request.user, is_active=True)
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    errors = {}
    form_data = {}
    today = dt.date.today().isoformat()

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        amount_str = request.POST.get('amount', '').strip()
        transaction_type = request.POST.get('transaction_type', 'expense').strip()
        date_str = request.POST.get('date', '').strip()
        account_id = request.POST.get('account', '').strip()
        bucket_id = request.POST.get('bucket', '').strip()

        form_data = {
            'description': description,
            'amount': amount_str,
            'transaction_type': transaction_type,
            'date': date_str,
            'account': account_id,
            'bucket': bucket_id,
        }

        if not description:
            errors['description'] = 'Description is required.'

        amount_val = None
        if not amount_str:
            errors['amount'] = 'Amount is required.'
        else:
            try:
                amount_val = float(amount_str)
                if amount_val <= 0:
                    errors['amount'] = 'Amount must be greater than zero.'
            except ValueError:
                errors['amount'] = 'Please enter a valid amount.'

        valid_types = [c[0] for c in Transaction.TRANSACTION_TYPE_CHOICES]
        if transaction_type not in valid_types:
            errors['transaction_type'] = 'Please select a transaction type.'

        date_val = None
        if not date_str:
            errors['date'] = 'Date is required.'
        else:
            try:
                date_val = dt.date.fromisoformat(date_str)
            except ValueError:
                errors['date'] = 'Please enter a valid date.'

        account_obj = None
        if not account_id:
            errors['account'] = 'Please select an account.'
        else:
            try:
                account_obj = BankAccount.objects.get(pk=account_id, user=request.user)
            except BankAccount.DoesNotExist:
                errors['account'] = 'Invalid account selected.'

        bucket_obj = None
        if bucket_id:
            try:
                bucket_obj = Bucket.objects.get(pk=bucket_id, user=request.user)
            except Bucket.DoesNotExist:
                errors['bucket'] = 'Invalid bucket selected.'

        if not errors:
            Transaction.objects.create(
                user=request.user,
                account=account_obj,
                bucket=bucket_obj,
                amount=amount_val,
                transaction_type=transaction_type,
                description=description,
                date=date_val,
            )
            prefs.onboarding_complete = True
            prefs.save()
            return redirect('/dashboard/')

    return render(request, 'accounts/onboarding_step4.html', {
        'errors': errors,
        'form_data': form_data,
        'accounts': accounts,
        'buckets': buckets,
        'today': today,
        'transaction_type_choices': Transaction.TRANSACTION_TYPE_CHOICES,
        'step': 4,
        'total_steps': _ONBOARDING_STEPS,
    })


@login_required
def onboarding_skip(request):
    if request.method == 'POST':
        prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
        prefs.onboarding_complete = True
        prefs.save()
    return redirect('/dashboard/')
