from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth import get_user_model

User = get_user_model()


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
