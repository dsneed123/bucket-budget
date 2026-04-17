import re
from decimal import Decimal

from django import forms

from .models import BankAccount

ACCOUNT_TYPE_CHOICES = BankAccount.ACCOUNT_TYPE_CHOICES


class BankAccountForm(forms.Form):
    name = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={'required': 'Account name is required.'},
    )
    account_type = forms.ChoiceField(
        choices=[('', '— select —')] + list(ACCOUNT_TYPE_CHOICES),
        error_messages={
            'required': 'Account type is required.',
            'invalid_choice': 'Please select a valid account type.',
        },
    )
    institution = forms.CharField(
        max_length=255,
        strip=True,
        required=False,
    )
    color = forms.CharField(
        max_length=7,
        strip=True,
        required=False,
        initial='#0984e3',
    )

    def clean_account_type(self):
        value = self.cleaned_data.get('account_type', '')
        valid = [c[0] for c in ACCOUNT_TYPE_CHOICES]
        if value not in valid:
            raise forms.ValidationError('Please select a valid account type.')
        return value

    def clean_color(self):
        color = (self.cleaned_data.get('color') or '').strip()
        if not color:
            return '#0984e3'
        if not re.match(r'^#[0-9a-fA-F]{6}$', color):
            raise forms.ValidationError('Please enter a valid hex color (e.g. #0984e3).')
        return color


class AccountUpdateBalanceForm(forms.Form):
    new_balance = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        error_messages={
            'required': 'New balance is required.',
            'invalid': 'Please enter a valid number.',
        },
    )
