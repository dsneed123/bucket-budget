from django.contrib import admin

from .models import AutoSaveRule, SavingsContribution, SavingsGoal, SavingsMilestone


@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ('name', 'target_amount', 'current_amount', 'progress', 'priority', 'goal_type', 'is_achieved', 'user')
    list_filter = ('priority', 'goal_type', 'is_achieved', 'is_private')
    search_fields = ('name', 'user__email')
    ordering = ('-created_at',)

    @admin.display(description='Progress')
    def progress(self, obj):
        if obj.target_amount:
            pct = (obj.current_amount / obj.target_amount) * 100
            return f'{pct:.1f}%'
        return '—'


@admin.register(SavingsContribution)
class SavingsContributionAdmin(admin.ModelAdmin):
    list_display = ('goal', 'amount', 'transaction_type', 'date', 'source_account')
    list_filter = ('transaction_type', 'date')
    search_fields = ('goal__name', 'note')
    ordering = ('-date',)
    date_hierarchy = 'date'


@admin.register(SavingsMilestone)
class SavingsMilestoneAdmin(admin.ModelAdmin):
    list_display = ('goal', 'percentage', 'reached_at')
    list_filter = ('percentage',)
    ordering = ('-reached_at',)


@admin.register(AutoSaveRule)
class AutoSaveRuleAdmin(admin.ModelAdmin):
    list_display = ('user', 'goal', 'amount', 'frequency', 'next_run', 'is_active')
    list_filter = ('frequency', 'is_active')
    search_fields = ('user__email', 'goal__name')
    ordering = ('next_run',)
