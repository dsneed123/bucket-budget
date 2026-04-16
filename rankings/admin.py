from django.contrib import admin

from .models import NecessitySnapshot, ScoreStreak


@admin.register(NecessitySnapshot)
class NecessitySnapshotAdmin(admin.ModelAdmin):
    list_display = ('user', 'period_start', 'period_end', 'avg_score', 'total_spend', 'transaction_count', 'created_at')
    list_filter = ('user',)
    ordering = ('-period_start',)


@admin.register(ScoreStreak)
class ScoreStreakAdmin(admin.ModelAdmin):
    list_display = ('user', 'best_streak')
    ordering = ('-best_streak',)
