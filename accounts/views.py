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

        valid_weeks = [c[0] for c in UserPreferences.START_OF_WEEK_CHOICES]
        if start_of_week not in valid_weeks:
            errors['start_of_week'] = 'Please select a valid day.'

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
            prefs.save()
            return redirect('/settings/?saved=1#preferences')

    bank_accounts = BankAccount.objects.filter(user=request.user, is_active=True)

    return render(request, 'accounts/settings.html', {
        'prefs': prefs,
        'errors': errors,
        'week_choices': UserPreferences.START_OF_WEEK_CHOICES,
        'bank_accounts': bank_accounts,
    })


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
