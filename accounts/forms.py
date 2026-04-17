import re
from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from .currencies import CURRENCY_CHOICES


class LoginForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Please enter a valid email address.',
        },
    )
    password = forms.CharField(
        error_messages={'required': 'Password is required.'},
    )


class RegisterForm(forms.Form):
    email = forms.EmailField(
        max_length=254,
        error_messages={
            'required': 'Email is required.',
            'invalid': 'Please enter a valid email address.',
        },
    )
    first_name = forms.CharField(
        max_length=150,
        strip=True,
        error_messages={'required': 'First name is required.'},
    )
    password = forms.CharField(
        error_messages={'required': 'Password is required.'},
    )
    password_confirm = forms.CharField(
        error_messages={'required': 'Please confirm your password.'},
    )

    def clean_password(self):
        password = self.cleaned_data.get('password', '')
        if len(password) < 8:
            raise forms.ValidationError('Password must be at least 8 characters.')
        return password

    def clean_password_confirm(self):
        password = self.cleaned_data.get('password', '')
        password_confirm = self.cleaned_data.get('password_confirm', '')
        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match.')
        return password_confirm


class ProfileForm(forms.Form):
    VALID_CURRENCIES = [c[0] for c in CURRENCY_CHOICES]

    first_name = forms.CharField(
        max_length=150,
        strip=True,
        error_messages={'required': 'First name is required.'},
    )
    last_name = forms.CharField(
        max_length=150,
        strip=True,
        required=False,
    )
    currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        error_messages={
            'required': 'Currency is required.',
            'invalid_choice': 'Please select a valid currency.',
        },
    )
    monthly_income = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        validators=[MinValueValidator(Decimal('0'), message='Monthly income cannot be negative.')],
        error_messages={'invalid': 'Please enter a valid number.'},
    )
    zero_based_budgeting = forms.BooleanField(required=False)
