from django.urls import path

from . import views

urlpatterns = [
    path('rankings/', views.rankings, name='rankings'),
    path('rankings/review/', views.rankings_review, name='rankings_review'),
]
