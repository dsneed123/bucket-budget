import re
from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator

from .models import AutoSaveRule, SavingsGoal


class SavingsGoalForm(forms.Form):
    VALID_PRIORITIES = ('low', 'medium', 'high', 'critical')
    VALID_GOAL_TYPES = {c[0] for c in SavingsGoal.GOAL_TYPE_CHOICES}

    name = forms.CharField(
        max_length=100,
        strip=True,
        error_messages={'required': 'Goal name is required.'},
    )
    description = forms.CharField(
        max_length=500,
        strip=True,
        required=False,
    )
    target_amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Target amount must be greater than zero.')],
        error_messages={
            'required': 'Target amount is required.',
            'invalid': 'Please enter a valid number.',
        },
    )
    deadline = forms.DateField(
        input_formats=['%Y-%m-%d'],
        required=False,
        error_messages={'invalid': 'Please enter a valid date.'},
    )
    priority = forms.ChoiceField(
        choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')],
        required=False,
    )
    goal_type = forms.CharField(
        max_length=50,
        strip=True,
        required=False,
    )
    color = forms.CharField(
        max_length=7,
        strip=True,
        required=False,
    )
    icon = forms.CharField(
        max_length=10,
        strip=True,
        required=False,
    )
    is_private = forms.BooleanField(required=False)

    def clean_priority(self):
        val = self.cleaned_data.get('priority', 'medium')
        if val not in self.VALID_PRIORITIES:
            return 'medium'
        return val

    def clean_goal_type(self):
        val = self.cleaned_data.get('goal_type', 'general')
        if val not in self.VALID_GOAL_TYPES:
            return 'general'
        return val

    def clean_color(self):
        color = (self.cleaned_data.get('color') or '').strip()
        if not color:
            return '#00d4aa'
        if not re.match(r'^#[0-9a-fA-F]{6}$', color):
            raise forms.ValidationError('Please enter a valid hex color (e.g. #00d4aa).')
        return color

    def clean_icon(self):
        return self.cleaned_data.get('icon') or '🎯'


class ContributionForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Amount must be greater than zero.')],
        error_messages={
            'required': 'Amount is required.',
            'invalid': 'Please enter a valid number.',
        },
    )
    date = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'Date is required.',
            'invalid': 'Please enter a valid date.',
        },
    )
    note = forms.CharField(
        max_length=255,
        strip=True,
        required=False,
    )


class AutoSaveRuleForm(forms.Form):
    VALID_FREQUENCIES = [c[0] for c in AutoSaveRule.FREQUENCY_CHOICES]

    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'), message='Amount must be greater than zero.')],
        error_messages={
            'required': 'Amount is required.',
            'invalid': 'Please enter a valid number.',
        },
    )
    frequency = forms.ChoiceField(
        choices=AutoSaveRule.FREQUENCY_CHOICES,
        error_messages={
            'required': 'Frequency is required.',
            'invalid_choice': 'Please select a valid frequency.',
        },
    )
    next_run = forms.DateField(
        input_formats=['%Y-%m-%d'],
        error_messages={
            'required': 'First run date is required.',
            'invalid': 'Please enter a valid date.',
        },
    )

    def clean_frequency(self):
        val = self.cleaned_data.get('frequency', '')
        if val not in self.VALID_FREQUENCIES:
            raise forms.ValidationError('Please select a valid frequency.')
        return val
