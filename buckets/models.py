import datetime
from decimal import Decimal

from django.conf import settings
from django.db import models


class Bucket(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='buckets')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    monthly_allocation = models.DecimalField(max_digits=10, decimal_places=2)
    color = models.CharField(max_length=7, default='#0984e3')
    icon = models.CharField(max_length=10, default='💰')
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_uncategorized = models.BooleanField(default=False)
    rollover = models.BooleanField(default=False)
    alert_threshold = models.IntegerField(default=90)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def spent_this_month(self):
        # Will aggregate expenses for this bucket once the Expense model exists
        return Decimal('0')

    def rollover_amount(self, year=None, month=None):
        if not self.rollover:
            return Decimal('0')

        from django.db.models import Sum
        from transactions.models import Transaction

        today = datetime.date.today()
        if year is None:
            year = today.year
        if month is None:
            month = today.month

        if month == 1:
            prev_year, prev_month = year - 1, 12
        else:
            prev_year, prev_month = year, month - 1

        prev_spent = (
            Transaction.objects.filter(
                user=self.user,
                bucket=self,
                transaction_type='expense',
                date__year=prev_year,
                date__month=prev_month,
            ).aggregate(s=Sum('amount'))['s']
            or Decimal('0')
        )
        return max(self.monthly_allocation - prev_spent, Decimal('0'))

    def remaining_this_month(self):
        return self.monthly_allocation - self.spent_this_month()

    def percentage_used(self):
        if self.monthly_allocation <= 0:
            return 0
        return min(int((self.spent_this_month() / self.monthly_allocation) * 100), 100)
