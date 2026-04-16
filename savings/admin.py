from django.contrib import admin

from .models import AutoSaveRule, SavingsContribution, SavingsGoal

admin.site.register(SavingsGoal)
admin.site.register(SavingsContribution)
admin.site.register(AutoSaveRule)
