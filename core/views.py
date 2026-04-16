import calendar
import datetime
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Case, IntegerField, Sum, Value, When
from django.http import HttpResponse
from django.shortcuts import render

from banking.models import BankAccount
from buckets.models import Bucket
from savings.models import SavingsGoal
from transactions.models import RecurringTransaction, Transaction


def index(request):
    return render(request, 'core/index.html')


def health(request):
    return HttpResponse("ok", status=200)


@login_required
def dashboard(request):
    today = datetime.date.today()
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    month_qs = Transaction.objects.filter(
        user=request.user, date__year=today.year, date__month=today.month
    )
    total_income = month_qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = month_qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    net = total_income - total_expenses

    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related('account', 'bucket')
        .order_by('-date', '-created_at')[:5]
    )

    quick_add_errors = request.session.pop('quick_add_errors', {})
    quick_add_form_data = request.session.pop('quick_add_form_data', {
        'transaction_type': 'expense',
        'date': today.isoformat(),
    })

    all_goals = SavingsGoal.objects.filter(user=request.user)
    total_saved = all_goals.aggregate(s=Sum('current_amount'))['s'] or Decimal('0')

    top_goals_qs = (
        SavingsGoal.objects.filter(user=request.user, is_achieved=False)
        .annotate(priority_order=Case(
            When(priority='critical', then=Value(4)),
            When(priority='high', then=Value(3)),
            When(priority='medium', then=Value(2)),
            When(priority='low', then=Value(1)),
            default=Value(0),
            output_field=IntegerField(),
        ))
        .order_by('-priority_order', 'deadline', 'name')[:3]
    )

    savings_widget_data = []
    for goal in top_goals_qs:
        pct = min(int((goal.current_amount / goal.target_amount) * 100), 100) if goal.target_amount > 0 else 0
        savings_widget_data.append({'goal': goal, 'pct': pct})

    # Budget snapshot widget
    budget_buckets = Bucket.objects.filter(
        user=request.user, is_active=True, is_uncategorized=False
    )
    total_allocated = budget_buckets.aggregate(s=Sum('monthly_allocation'))['s'] or Decimal('0')
    if total_allocated > 0:
        budget_pct = min(int((total_expenses / total_allocated) * 100), 100)
    else:
        budget_pct = 0

    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    days_left = days_in_month - today.day + 1
    actual_daily_avg = (total_expenses / Decimal(days_elapsed)).quantize(Decimal('0.01')) if days_elapsed > 0 else Decimal('0')
    monthly_income = request.user.monthly_income or Decimal('0')
    remaining_budget = monthly_income - total_expenses
    ideal_daily_spend = (remaining_budget / Decimal(days_left)).quantize(Decimal('0.01')) if days_left > 0 and remaining_budget > 0 else Decimal('0')

    month_expenses_qs = Transaction.objects.filter(
        user=request.user, transaction_type='expense',
        date__year=today.year, date__month=today.month,
    )
    top_bucket_data = []
    for bucket in budget_buckets:
        spent = month_expenses_qs.filter(bucket=bucket).aggregate(s=Sum('amount'))['s'] or Decimal('0')
        effective_alloc = bucket.monthly_allocation
        pct = min(int((spent / effective_alloc) * 100), 100) if effective_alloc > 0 else 0
        top_bucket_data.append({'bucket': bucket, 'spent': spent, 'pct': pct, 'over': spent > effective_alloc})
    top_bucket_data.sort(key=lambda x: x['pct'], reverse=True)
    top_buckets = top_bucket_data[:3]

    upcoming_end = today + datetime.timedelta(days=7)
    upcoming_recurring = (
        RecurringTransaction.objects.filter(
            user=request.user,
            is_active=True,
            next_due__gte=today,
            next_due__lte=upcoming_end,
        )
        .select_related('bucket')
        .order_by('next_due')
    )

    return render(request, 'core/dashboard.html', {
        'accounts': accounts,
        'buckets': buckets,
        'total_income': total_income,
        'total_expenses': total_expenses,
        'net': net,
        'current_month': today.strftime('%B %Y'),
        'recent_transactions': recent_transactions,
        'quick_add_errors': quick_add_errors,
        'quick_add_form_data': quick_add_form_data,
        'savings_widget_data': savings_widget_data,
        'total_saved': total_saved,
        'total_allocated': total_allocated,
        'budget_pct': budget_pct,
        'days_left': days_left,
        'actual_daily_avg': actual_daily_avg,
        'ideal_daily_spend': ideal_daily_spend,
        'top_buckets': top_buckets,
        'upcoming_recurring': upcoming_recurring,
    })
