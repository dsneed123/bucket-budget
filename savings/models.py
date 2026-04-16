from django.conf import settings
from django.db import models


class SavingsGoal(models.Model):
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='savings_goals')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    target_amount = models.DecimalField(max_digits=10, decimal_places=2)
    current_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    deadline = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=8, choices=PRIORITY_CHOICES, default='medium')
    color = models.CharField(max_length=7, default='#00d4aa')
    icon = models.CharField(max_length=10, default='🎯')
    is_achieved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name} ({self.user})'


class SavingsContribution(models.Model):
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='contributions')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    source_account = models.ForeignKey('banking.BankAccount', on_delete=models.CASCADE, related_name='savings_contributions')
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.goal.name} +{self.amount} on {self.date}'


class SavingsMilestone(models.Model):
    MILESTONE_CHOICES = [
        (25, '25%'),
        (50, '50%'),
        (75, '75%'),
        (100, '100%'),
    ]

    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='milestones')
    percentage = models.IntegerField(choices=MILESTONE_CHOICES)
    reached_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('goal', 'percentage')
        ordering = ['percentage']

    def __str__(self):
        return f'{self.goal.name} — {self.percentage}% milestone'


class AutoSaveRule(models.Model):
    FREQUENCY_CHOICES = [
        ('weekly', 'Weekly'),
        ('biweekly', 'Biweekly'),
        ('monthly', 'Monthly'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='auto_save_rules')
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='auto_save_rules')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    frequency = models.CharField(max_length=8, choices=FREQUENCY_CHOICES)
    source_account = models.ForeignKey('banking.BankAccount', on_delete=models.CASCADE, related_name='auto_save_rules')
    is_active = models.BooleanField(default=True)
    next_run = models.DateField()

    def __str__(self):
        return f'{self.user} — ${self.amount} to {self.goal.name} ({self.frequency})'
