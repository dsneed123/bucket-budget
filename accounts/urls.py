from django.contrib.auth.views import (
    LogoutView,
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.urls import path, reverse_lazy
from . import views

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('register/', views.register, name='register'),
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),
    path('profile/', views.profile, name='profile'),
    path('profile/password/', views.ChangePasswordView.as_view(), name='change_password'),
    path('profile/delete/', views.delete_account, name='delete_account'),
    path('settings/', views.settings, name='settings'),
    path('settings/export/', views.export_all_data, name='export_all_data'),
    path('settings/import/', views.import_csv, name='import_csv'),
    path('settings/import/template/<str:data_type>/', views.download_import_template, name='download_import_template'),
    path('settings/widget-preferences/', views.save_widget_preferences, name='save_widget_preferences'),
    path('settings/no-spend-goal/', views.save_no_spend_goal, name='save_no_spend_goal'),
    path('password-reset/', PasswordResetView.as_view(
        template_name='accounts/password_reset_form.html',
        email_template_name='accounts/password_reset_email.html',
        success_url=reverse_lazy('password_reset_done'),
    ), name='password_reset'),
    path('password-reset/done/', PasswordResetDoneView.as_view(
        template_name='accounts/password_reset_done.html',
    ), name='password_reset_done'),
    path('password-reset/<uidb64>/<token>/', PasswordResetConfirmView.as_view(
        template_name='accounts/password_reset_confirm.html',
        success_url=reverse_lazy('password_reset_complete'),
    ), name='password_reset_confirm'),
    path('password-reset/complete/', PasswordResetCompleteView.as_view(
        template_name='accounts/password_reset_complete.html',
    ), name='password_reset_complete'),
]
