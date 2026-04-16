from django.urls import path

from . import views

urlpatterns = [
    path('budget/', views.budget_overview, name='budget_overview'),
    path('budget/<int:year>/<int:month>/', views.budget_overview, name='budget_overview_month'),
]
