from django.contrib import admin

from .models import SavingsContribution, SavingsGoal

admin.site.register(SavingsGoal)
admin.site.register(SavingsContribution)
