from django.conf import settings
from django.db import models


class BudgetSummary(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='budget_summaries',
    )
    month = models.IntegerField()
    year = models.IntegerField()
    income = models.DecimalField(max_digits=12, decimal_places=2)
    total_allocated = models.DecimalField(max_digits=12, decimal_places=2)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2)
    total_saved = models.DecimalField(max_digits=12, decimal_places=2)
    necessity_avg = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    surplus_deficit = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-year', '-month']
        unique_together = ('user', 'month', 'year')

    def __str__(self):
        return f'BudgetSummary({self.user_id}, {self.year}-{self.month:02d})'
