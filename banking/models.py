from django.conf import settings
from django.db import models


class BankAccount(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('checking', 'Checking'),
        ('savings', 'Savings'),
        ('credit', 'Credit'),
        ('cash', 'Cash'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bank_accounts')
    name = models.CharField(max_length=255)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    institution = models.CharField(max_length=255, blank=True, null=True)
    color = models.CharField(max_length=7, default='#0984e3')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, change_reason='manual_update', reference_id=None, **kwargs):
        if self.pk:
            previous = BankAccount.objects.filter(pk=self.pk).values_list('balance', flat=True).first()
            if previous is not None and previous != self.balance:
                super().save(*args, **kwargs)
                BalanceHistory.objects.create(
                    account=self,
                    previous_balance=previous,
                    new_balance=self.balance,
                    change_amount=self.balance - previous,
                    change_reason=change_reason,
                    reference_id=reference_id,
                )
                return
        super().save(*args, **kwargs)


class BalanceHistory(models.Model):
    CHANGE_REASON_CHOICES = [
        ('transaction', 'Transaction'),
        ('manual_update', 'Manual Update'),
        ('transfer', 'Transfer'),
        ('savings_contribution', 'Savings Contribution'),
        ('recurring', 'Recurring'),
        ('import', 'Import'),
    ]

    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name='balance_history')
    previous_balance = models.DecimalField(max_digits=12, decimal_places=2)
    new_balance = models.DecimalField(max_digits=12, decimal_places=2)
    change_amount = models.DecimalField(max_digits=12, decimal_places=2)
    change_reason = models.CharField(max_length=25, choices=CHANGE_REASON_CHOICES)
    reference_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
