from django.contrib.auth.views import LogoutView
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register, name='register'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/password/', views.ChangePasswordView.as_view(), name='change_password'),
]
