from django.urls import path

from . import views

urlpatterns = [
    path('insights/', views.insights, name='insights'),
    path('insights/report/<int:year>/<int:month>/', views.monthly_report, name='monthly_report'),
]
