from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Count

from .models import CustomUser, UserPreferences, UserStreak


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'date_joined', 'transaction_count', 'is_staff')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'currency')
    search_fields = ('email', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'currency', 'monthly_income', 'zero_based_budgeting')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'first_name', 'password1', 'password2'),
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_transaction_count=Count('transactions'))

    @admin.display(description='Transactions', ordering='_transaction_count')
    def transaction_count(self, obj):
        return obj._transaction_count


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ('user', 'theme', 'timezone', 'start_of_week', 'onboarding_complete')
    list_filter = ('theme', 'start_of_week', 'onboarding_complete')
    search_fields = ('user__email', 'user__first_name')


@admin.register(UserStreak)
class UserStreakAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_streak', 'longest_streak', 'last_active_date')
    list_filter = ('last_active_date',)
    search_fields = ('user__email',)
    ordering = ('-current_streak',)
