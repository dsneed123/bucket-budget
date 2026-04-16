from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required

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
                username=email,
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
            request.user.save()
            success = True

    return render(request, 'accounts/profile.html', {
        'errors': errors,
        'success': success,
        'currency_choices': CURRENCY_CHOICES,
    })
