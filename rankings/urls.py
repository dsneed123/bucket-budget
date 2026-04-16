from django.urls import path

from . import views

urlpatterns = [
    path('rankings/', views.rankings, name='rankings'),
]
