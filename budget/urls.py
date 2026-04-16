from django.urls import path

from . import views

urlpatterns = [
    path('budget/', views.budget_overview, name='budget_overview'),
    path('budget/history/', views.budget_history, name='budget_history'),
    path('budget/save-allocations/', views.save_allocations, name='budget_save_allocations'),
    path('budget/copy-last-month/', views.copy_last_month_allocations, name='budget_copy_last_month'),
    path('budget/<int:year>/<int:month>/', views.budget_overview, name='budget_overview_month'),
]
