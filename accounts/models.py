from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        extra_fields.setdefault('username', email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractUser):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    currency = models.CharField(max_length=3, default='USD')
    monthly_income = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    zero_based_budgeting = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name']

    objects = CustomUserManager()


class UserPreferences(models.Model):
    START_OF_WEEK_CHOICES = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='preferences')
    email_weekly_digest = models.BooleanField(default=True)
    email_budget_alerts = models.BooleanField(default=True)
    email_goal_achieved = models.BooleanField(default=True)
    default_account = models.ForeignKey(
        'banking.BankAccount',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    start_of_week = models.CharField(max_length=10, choices=START_OF_WEEK_CHOICES, default='monday')
    fiscal_month_start = models.IntegerField(default=1)

    def __str__(self):
        return f'Preferences for {self.user}'
