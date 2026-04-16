from django.urls import path

from . import views

app_name = 'savings'

urlpatterns = [
    path('savings/', views.savings_list, name='savings_list'),
]
