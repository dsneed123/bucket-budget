import calendar as _cal_module
import datetime
from collections import defaultdict
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Avg, Case, IntegerField, Q, Sum, Value, When
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from accounts.models import UserPreferences, UserStreak
from core.utils import make_breadcrumbs
from accounts.utils import get_current_fiscal_month, get_fiscal_month_range, get_user_fiscal_start
from banking.models import BankAccount
from buckets.models import Bucket
from insights.models import Recommendation
from insights.recommendations import refresh_recommendations
from savings.models import SavingsContribution, SavingsMilestone, SavingsGoal
from transactions.models import RecurringTransaction, Transaction


def _build_activity_feed(user, limit=10):
    _cat_icons = {'budget': '⚠️', 'savings': '🎯', 'quality': '📊', 'vendor': '🛒'}
    events = []

    for txn in Transaction.objects.filter(user=user).select_related('bucket').order_by('-created_at')[:limit]:
        icon = txn.bucket.icon if txn.bucket else ('💰' if txn.transaction_type == 'income' else '💳')
        events.append({
            'icon': icon,
            'description': txn.description,
            'timestamp': txn.created_at,
            'amount': txn.amount,
            'is_income': txn.transaction_type == 'income',
            'kind': 'transaction',
        })

    for contrib in SavingsContribution.objects.filter(goal__user=user).select_related('goal').order_by('-created_at')[:limit]:
        is_contrib = contrib.transaction_type == 'contribution'
        verb = 'Contributed to' if is_contrib else 'Withdrew from'
        events.append({
            'icon': contrib.goal.icon,
            'description': f'{verb} {contrib.goal.name}',
            'timestamp': contrib.created_at,
            'amount': contrib.amount,
            'is_income': not is_contrib,
            'kind': 'contribution',
        })

    for milestone in SavingsMilestone.objects.filter(goal__user=user).select_related('goal').order_by('-reached_at')[:limit]:
        events.append({
            'icon': '🏆',
            'description': f'Reached {milestone.percentage}% of {milestone.goal.name}',
            'timestamp': milestone.reached_at,
            'amount': None,
            'is_income': True,
            'kind': 'milestone',
        })

    for rec in Recommendation.objects.filter(user=user).order_by('-created_at')[:limit]:
        events.append({
            'icon': _cat_icons.get(rec.category, '💡'),
            'description': rec.message,
            'timestamp': rec.created_at,
            'amount': None,
            'is_income': False,
            'kind': 'alert',
        })

    events.sort(key=lambda e: e['timestamp'], reverse=True)
    return events[:limit]


def _update_streak(user, today):
    streak, _ = UserStreak.objects.get_or_create(user=user)
    if streak.last_active_date is None:
        streak.current_streak = 1
    elif streak.last_active_date == today:
        return streak
    elif streak.last_active_date == today - datetime.timedelta(days=1):
        streak.current_streak += 1
    else:
        streak.current_streak = 1
    streak.last_active_date = today
    if streak.current_streak > streak.longest_streak:
        streak.longest_streak = streak.current_streak
    streak.save()
    return streak


def index(request):
    return render(request, 'core/index.html')


def health(request):
    return HttpResponse("ok", status=200)


@login_required
def dashboard(request):
    today = datetime.date.today()
    accounts = BankAccount.objects.filter(user=request.user, is_active=True).order_by('name')
    buckets = Bucket.objects.filter(user=request.user, is_active=True).order_by('sort_order', 'name')

    fiscal_start = get_user_fiscal_start(request.user)
    fyear, fmonth = get_current_fiscal_month(today, fiscal_start)
    fstart, fend = get_fiscal_month_range(fyear, fmonth, fiscal_start)

    month_qs = Transaction.objects.filter(
        user=request.user, date__gte=fstart, date__lte=fend
    )

    _agg_cache_key = f'dashboard_agg_{request.user.pk}_{fyear}_{fmonth}'
    _agg = cache.get(_agg_cache_key)
    if _agg is None:
        _agg = month_qs.aggregate(
            income=Sum('amount', filter=Q(transaction_type='income')),
            expenses=Sum('amount', filter=Q(transaction_type='expense')),
        )
        cache.set(_agg_cache_key, _agg, 300)
    total_income = _agg['income'] or Decimal('0')
    total_expenses = _agg['expenses'] or Decimal('0')
    net = total_income - total_expenses

    # Last month's expenses for comparison
    prev_fyear, prev_fmonth = (fyear - 1, 12) if fmonth == 1 else (fyear, fmonth - 1)
    prev_fstart, prev_fend = get_fiscal_month_range(prev_fyear, prev_fmonth, fiscal_start)
    _prev_agg_cache_key = f'dashboard_agg_{request.user.pk}_{prev_fyear}_{prev_fmonth}'
    _prev_agg = cache.get(_prev_agg_cache_key)
    if _prev_agg is None:
        _prev_agg = Transaction.objects.filter(
            user=request.user, date__gte=prev_fstart, date__lte=prev_fend
        ).aggregate(expenses=Sum('amount', filter=Q(transaction_type='expense')))
        cache.set(_prev_agg_cache_key, _prev_agg, 300)
    prev_month_expenses = _prev_agg['expenses'] or Decimal('0')

    if prev_month_expenses > 0:
        spending_change_pct = int(((total_expenses - prev_month_expenses) / prev_month_expenses) * 100)
    else:
        spending_change_pct = None

    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related('account', 'bucket')
        .order_by('-date', '-created_at')[:10]
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

    days_in_month = (fend - fstart).days + 1
    days_elapsed = (today - fstart).days + 1
    days_left = (fend - today).days + 1
    actual_daily_avg = (total_expenses / Decimal(days_elapsed)).quantize(Decimal('0.01')) if days_elapsed > 0 else Decimal('0')
    monthly_income = request.user.monthly_income or Decimal('0')
    income_pct = min(int((total_income / monthly_income) * 100), 100) if monthly_income > 0 else 0
    remaining_budget = monthly_income - total_expenses
    ideal_daily_spend = (remaining_budget / Decimal(days_left)).quantize(Decimal('0.01')) if days_left > 0 and remaining_budget > 0 else Decimal('0')

    month_expenses_qs = Transaction.objects.filter(
        user=request.user, transaction_type='expense',
        date__gte=fstart, date__lte=fend,
    )
    _bucket_spending = {
        row['bucket_id']: row['s']
        for row in month_expenses_qs.values('bucket_id').annotate(s=Sum('amount'))
    }
    top_bucket_data = []
    for bucket in budget_buckets:
        spent = _bucket_spending.get(bucket.pk) or Decimal('0')
        effective_alloc = bucket.monthly_allocation
        pct = min(int((spent / effective_alloc) * 100), 100) if effective_alloc > 0 else 0
        top_bucket_data.append({'bucket': bucket, 'spent': spent, 'pct': pct, 'over': spent > effective_alloc})
    top_bucket_data.sort(key=lambda x: x['pct'], reverse=True)
    top_buckets = top_bucket_data[:3]

    # Daily spending chart
    daily_totals: dict = defaultdict(Decimal)
    for row in month_expenses_qs.values('date').annotate(total=Sum('amount')):
        daily_totals[row['date']] = row['total']

    daily_spending = []
    cur = fstart
    while cur <= min(fend, today):
        spent = daily_totals.get(cur, Decimal('0'))
        daily_spending.append({'date': cur, 'spent': spent, 'is_today': cur == today})
        cur += datetime.timedelta(days=1)

    max_daily = max((d['spent'] for d in daily_spending), default=Decimal('0'))
    if max_daily > 0:
        for d in daily_spending:
            d['bar_pct'] = int((d['spent'] / max_daily) * 100)
    else:
        for d in daily_spending:
            d['bar_pct'] = 0

    # Mark days outside the last 7 so template can hide them on small screens
    for d in daily_spending:
        d['is_recent'] = (today - d['date']).days < 7

    # Calendar widget
    cal_year, cal_month = today.year, today.month
    _cal_obj = _cal_module.Calendar(firstweekday=6)  # Sunday-first
    _month_weeks_raw = _cal_obj.monthdayscalendar(cal_year, cal_month)

    _cal_txns_qs = Transaction.objects.filter(
        user=request.user,
        date__year=cal_year,
        date__month=cal_month,
    ).values('date', 'transaction_type', 'description', 'amount').order_by('date')

    _cal_day_data: dict = defaultdict(lambda: {'has_income': False, 'has_expense': False, 'transactions': []})
    for _t in _cal_txns_qs:
        _d = _t['date'].day
        if _t['transaction_type'] == 'income':
            _cal_day_data[_d]['has_income'] = True
        elif _t['transaction_type'] == 'expense':
            _cal_day_data[_d]['has_expense'] = True
        _cal_day_data[_d]['transactions'].append({
            'desc': _t['description'],
            'amount': str(_t['amount']),
            'type': _t['transaction_type'],
        })

    _cal_expense_day_nums = {d for d, data in _cal_day_data.items() if data['has_expense']}

    calendar_weeks = []
    for _week in _month_weeks_raw:
        _row = []
        for _day_num in _week:
            if _day_num == 0:
                _row.append(None)
            else:
                _dd = _cal_day_data.get(_day_num, {})
                _is_past_or_today = (
                    cal_year < today.year
                    or (cal_year == today.year and cal_month < today.month)
                    or (cal_year == today.year and cal_month == today.month and _day_num <= today.day)
                )
                _is_no_spend = _is_past_or_today and _day_num not in _cal_expense_day_nums
                _row.append({
                    'day': _day_num,
                    'is_today': _day_num == today.day and cal_year == today.year and cal_month == today.month,
                    'has_income': _dd.get('has_income', False),
                    'has_expense': _dd.get('has_expense', False),
                    'is_no_spend': _is_no_spend,
                })
        calendar_weeks.append(_row)

    calendar_txns_by_day = {str(d): data['transactions'] for d, data in _cal_day_data.items()}

    # No-spend days calculation (within fiscal month up to today)
    _fiscal_expense_dates = set(
        month_expenses_qs.filter(date__lte=today).values_list('date', flat=True).distinct()
    )
    _days_elapsed = min((today - fstart).days + 1, days_in_month)
    no_spend_days = sum(
        1 for i in range(_days_elapsed)
        if (fstart + datetime.timedelta(days=i)) not in _fiscal_expense_dates
    )

    refresh_recommendations(request.user)
    _priority_order = {Recommendation.PRIORITY_HIGH: 0, Recommendation.PRIORITY_MEDIUM: 1, Recommendation.PRIORITY_LOW: 2}
    recommendations = sorted(
        Recommendation.objects.filter(user=request.user, is_dismissed=False),
        key=lambda r: _priority_order.get(r.priority, 3),
    )[:3]

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

    bill_countdown_end = today + datetime.timedelta(days=30)
    _bill_qs = (
        RecurringTransaction.objects.filter(
            user=request.user,
            is_active=True,
            transaction_type='expense',
            amount__gte=Decimal('50'),
            next_due__gte=today,
            next_due__lte=bill_countdown_end,
        )
        .order_by('next_due')
    )
    bill_countdown = [
        {'item': bill, 'days_until': (bill.next_due - today).days}
        for bill in _bill_qs
    ]

    activity_feed = _build_activity_feed(request.user)

    streak = _update_streak(request.user, today)

    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    widgets = prefs.get_widget_visibility()
    no_spend_goal = prefs.no_spend_goal
    widget_labels = [
        ('stats', 'Summary Stats'),
        ('daily_spending', 'Daily Spending Chart'),
        ('budget_overview', 'Budget Overview'),
        ('recent_transactions', 'Recent Transactions'),
        ('calendar', 'Calendar'),
        ('no_spend_days', 'No-Spend Days'),
        ('income_received', 'Income Received'),
        ('savings_goals', 'Savings Goals'),
        ('bill_countdown', 'Bill Countdown'),
        ('upcoming_recurring', 'Upcoming Recurring'),
        ('recommendations', 'Recommendations'),
        ('activity_feed', 'Activity Feed'),
    ]

    return render(request, 'core/dashboard.html', {
        'breadcrumbs': make_breadcrumbs(('Dashboard', None)),
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
        'bill_countdown': bill_countdown,
        'recommendations': recommendations,
        'daily_spending': daily_spending,
        'calendar_weeks': calendar_weeks,
        'calendar_txns_by_day': calendar_txns_by_day,
        'activity_feed': activity_feed,
        'streak': streak,
        'no_spend_days': no_spend_days,
        'no_spend_goal': no_spend_goal,
        'days_elapsed': _days_elapsed,
        'monthly_income': monthly_income,
        'income_pct': income_pct,
        'widgets': widgets,
        'widget_labels': widget_labels,
        'spending_change_pct': spending_change_pct,
    })


@login_required
def stats_api(request):
    today = datetime.date.today()
    fiscal_start = get_user_fiscal_start(request.user)
    fyear, fmonth = get_current_fiscal_month(today, fiscal_start)
    fstart, fend = get_fiscal_month_range(fyear, fmonth, fiscal_start)

    month_qs = Transaction.objects.filter(
        user=request.user, date__gte=fstart, date__lte=fend
    )
    total_income = month_qs.filter(transaction_type='income').aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_expenses = month_qs.filter(transaction_type='expense').aggregate(s=Sum('amount'))['s'] or Decimal('0')

    monthly_income = request.user.monthly_income or Decimal('0')
    net_worth = BankAccount.objects.filter(user=request.user, is_active=True).aggregate(s=Sum('balance'))['s'] or Decimal('0')
    budget_remaining = monthly_income - total_expenses
    savings_rate = (((total_income - total_expenses) / total_income) * 100).quantize(Decimal('0.01')) if total_income > 0 else Decimal('0')
    spending_quality = month_qs.filter(
        transaction_type='expense', necessity_score__isnull=False
    ).aggregate(avg=Avg('necessity_score'))['avg']
    spending_quality = Decimal(str(spending_quality)).quantize(Decimal('0.01')) if spending_quality is not None else None

    return JsonResponse({
        'net_worth': str(net_worth),
        'monthly_spend': str(total_expenses),
        'savings_rate': str(savings_rate),
        'spending_quality': str(spending_quality) if spending_quality is not None else None,
        'budget_remaining': str(budget_remaining),
        'fiscal_month': {'year': fyear, 'month': fmonth, 'start': fstart.isoformat(), 'end': fend.isoformat()},
    })
