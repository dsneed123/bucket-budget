import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

TAG_COLORS = [
    '#0984e3', '#00d4aa', '#f9ca24', '#ff4757',
    '#a29bfe', '#fd79a8', '#55efc4', '#fdcb6e',
    '#e17055', '#74b9ff',
]


class Tag(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tags')
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default='#0984e3')

    class Meta:
        unique_together = ('user', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name


class VendorMapping(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vendor_mappings')
    vendor_name = models.CharField(max_length=100)
    bucket = models.ForeignKey('buckets.Bucket', on_delete=models.SET_NULL, null=True, blank=True, related_name='vendor_mappings')
    last_used = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'vendor_name')
        ordering = ['-last_used']

    def __str__(self):
        return self.vendor_name


class IncomeSource(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='income_sources')
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7, default='#0984e3')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'name')
        ordering = ['name']

    def __str__(self):
        return self.name


class Transaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('expense', 'Expense'),
        ('income', 'Income'),
        ('transfer', 'Transfer'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='transactions')
    account = models.ForeignKey('banking.BankAccount', on_delete=models.CASCADE, related_name='transactions')
    bucket = models.ForeignKey('buckets.Bucket', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES)
    description = models.CharField(max_length=255)
    vendor = models.CharField(max_length=100, blank=True)
    date = models.DateField()
    necessity_score = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
    )
    notes = models.TextField(blank=True)
    receipt = models.ImageField(upload_to='receipts/', null=True, blank=True)
    is_recurring = models.BooleanField(default=False)
    split_group = models.UUIDField(null=True, blank=True, db_index=True)
    transfer_id = models.UUIDField(null=True, blank=True, db_index=True)
    income_source = models.ForeignKey('IncomeSource', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    tags = models.ManyToManyField('Tag', blank=True, related_name='transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f'{self.transaction_type} - {self.description} ({self.amount})'
