import re
from decimal import Decimal

from django import forms
from django.core.validators import MinValueValidator, MaxValueValidator


class BucketForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        strip=True,
        error_messages={'required': 'Bucket name is required.'},
    )
    icon = forms.CharField(
        max_length=10,
        strip=True,
        required=False,
    )
    color = forms.CharField(
        max_length=7,
        strip=True,
        required=False,
    )
    monthly_allocation = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0'), message='Allocation must be a positive number.')],
        error_messages={
            'required': 'Monthly allocation is required.',
            'invalid': 'Please enter a valid number.',
        },
    )
    description = forms.CharField(
        max_length=500,
        strip=True,
        required=False,
    )
    alert_threshold = forms.IntegerField(
        required=False,
        validators=[
            MinValueValidator(1, message='Alert threshold must be between 1 and 100.'),
            MaxValueValidator(100, message='Alert threshold must be between 1 and 100.'),
        ],
        error_messages={'invalid': 'Please enter a valid percentage.'},
    )
    rollover = forms.BooleanField(required=False)

    def clean_icon(self):
        return self.cleaned_data.get('icon') or '💰'

    def clean_color(self):
        color = (self.cleaned_data.get('color') or '').strip()
        if not color:
            return '#0984e3'
        if not re.match(r'^#[0-9a-fA-F]{6}$', color):
            raise forms.ValidationError('Please enter a valid hex color (e.g. #0984e3).')
        return color

    def clean_alert_threshold(self):
        val = self.cleaned_data.get('alert_threshold')
        if val is None:
            return 90
        return val
