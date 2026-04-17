import re
from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator

from .models import RecurringTransaction, Transaction


TRANSACTION_TYPE_CHOICES = Transaction.TRANSACTION_TYPE_CHOICES
FREQUENCY_CHOICES = RecurringTransaction.FREQUENCY_CHOICES


class TransactionForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Amount must be greater than zero.')],
        error_messages={
            'required': 'Amount is required.',
            'invalid': 'Please enter a valid amount.',
        },
    )
    transaction_type = forms.ChoiceField(
        choices=[('', '— select —')] + list(TRANSACTION_TYPE_CHOICES),
        error_messages={
            'required': 'Transaction type is required.',
            'invalid_choice': 'Please select expense or income.',
        },
    )
    description = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={'required': 'Description is required.'},
    )
    vendor = forms.CharField(
        max_length=100,
        strip=True,
        required=False,
    )
    date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'Date is required.',
            'invalid': 'Please enter a valid date.',
        },
    )
    necessity_score = forms.IntegerField(
        required=False,
        validators=[
            MinValueValidator(1, message='Necessity score must be between 1 and 10.'),
            MaxValueValidator(10, message='Necessity score must be between 1 and 10.'),
        ],
        error_messages={'invalid': 'Please enter a valid necessity score.'},
    )
    tags = forms.CharField(
        max_length=500,
        strip=True,
        required=False,
    )
    notes = forms.CharField(
        max_length=1000,
        strip=True,
        required=False,
    )

    def clean_transaction_type(self):
        value = self.cleaned_data.get('transaction_type', '')
        if value not in ('expense', 'income'):
            raise forms.ValidationError('Please select expense or income.')
        return value


class TransactionTransferForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Amount must be greater than zero.')],
        error_messages={
            'required': 'Amount is required.',
            'invalid': 'Please enter a valid amount.',
        },
    )
    description = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={'required': 'Description is required.'},
    )
    date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'Date is required.',
            'invalid': 'Please enter a valid date.',
        },
    )


class RecurringTransactionForm(forms.Form):
    VALID_TYPES = [c[0] for c in RecurringTransaction.TRANSACTION_TYPE_CHOICES]
    VALID_FREQUENCIES = [c[0] for c in RecurringTransaction.FREQUENCY_CHOICES]

    description = forms.CharField(
        max_length=255,
        strip=True,
        error_messages={'required': 'Description is required.'},
    )
    vendor = forms.CharField(
        max_length=100,
        strip=True,
        required=False,
    )
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Amount must be greater than zero.')],
        error_messages={
            'required': 'Amount is required.',
            'invalid': 'Enter a valid amount.',
        },
    )
    transaction_type = forms.ChoiceField(
        choices=RecurringTransaction.TRANSACTION_TYPE_CHOICES,
        error_messages={
            'required': 'Transaction type is required.',
            'invalid_choice': 'Please select a valid type.',
        },
    )
    frequency = forms.ChoiceField(
        choices=RecurringTransaction.FREQUENCY_CHOICES,
        error_messages={
            'required': 'Frequency is required.',
            'invalid_choice': 'Please select a valid frequency.',
        },
    )
    start_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'Start date is required.',
            'invalid': 'Enter a valid date.',
        },
    )
    next_due = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'Next due date is required.',
            'invalid': 'Enter a valid date.',
        },
    )
    end_date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        required=False,
        error_messages={'invalid': 'Enter a valid date.'},
    )
    necessity_score = forms.IntegerField(
        required=False,
        validators=[
            MinValueValidator(1, message='Necessity score must be between 1 and 10.'),
            MaxValueValidator(10, message='Necessity score must be between 1 and 10.'),
        ],
        error_messages={'invalid': 'Enter a valid necessity score.'},
    )
    is_active = forms.BooleanField(required=False)
    is_subscription = forms.BooleanField(required=False)


class IncomeSourceForm(forms.Form):
    name = forms.CharField(
        max_length=50,
        strip=True,
        error_messages={'required': 'Name is required.'},
    )
    color = forms.CharField(
        max_length=7,
        strip=True,
        required=False,
        initial='#0984e3',
    )

    def clean_color(self):
        color = self.cleaned_data.get('color', '').strip()
        if not color:
            return '#0984e3'
        if not re.match(r'^#[0-9a-fA-F]{6}$', color):
            raise forms.ValidationError('Please select a valid color.')
        return color
