from django.conf import settings
from django.db import models


class NecessitySnapshot(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='necessity_snapshots',
    )
    period_start = models.DateField()
    period_end = models.DateField()
    avg_score = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    total_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    want_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    useful_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    need_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    unscored_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    transaction_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_start']
        unique_together = ('user', 'period_start', 'period_end')

    def __str__(self):
        return f'NecessitySnapshot({self.user_id}, {self.period_start} – {self.period_end})'
