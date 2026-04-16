from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Avg, Sum
from django.utils import timezone

from budget.models import BudgetSummary
from buckets.models import Bucket
from transactions.models import Transaction


def _completed_months(ref_date):
    """Yield (year, month) tuples for all months before ref_date's current month."""
    year, month = ref_date.year, ref_date.month
    # Step back one month to get the last completed month
    if month == 1:
        return (year - 1, 12)
    return (year, month - 1)


def _build_summary(user, year, month):
    """Compute and upsert a BudgetSummary for (user, year, month)."""
    from accounts.utils import get_fiscal_month_range, get_user_fiscal_start
    fiscal_start = get_user_fiscal_start(user)
    first_day, last_day = get_fiscal_month_range(year, month, fiscal_start)

    expenses = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__gte=first_day,
        date__lte=last_day,
    )
    income_txns = Transaction.objects.filter(
        user=user,
        transaction_type='income',
        date__gte=first_day,
        date__lte=last_day,
    )

    total_spent = expenses.aggregate(s=Sum('amount'))['s'] or 0
    income_from_txns = income_txns.aggregate(s=Sum('amount'))['s'] or 0
    # Prefer income from transactions if present, else fall back to user profile income
    income = income_from_txns if income_from_txns else user.monthly_income

    total_allocated = (
        Bucket.objects.filter(user=user, is_active=True)
        .aggregate(s=Sum('monthly_allocation'))['s'] or 0
    )

    necessity_avg = expenses.aggregate(a=Avg('necessity_score'))['a']

    # total_saved = income - spent (money not consumed by expenses)
    total_saved = income - total_spent
    surplus_deficit = income - total_spent

    summary, created = BudgetSummary.objects.update_or_create(
        user=user,
        month=month,
        year=year,
        defaults=dict(
            income=income,
            total_allocated=total_allocated,
            total_spent=total_spent,
            total_saved=total_saved,
            necessity_avg=necessity_avg,
            surplus_deficit=surplus_deficit,
        ),
    )
    return summary, created


class Command(BaseCommand):
    help = (
        'Generate BudgetSummary records for completed months. '
        'Defaults to the most recently completed month. Use --all-months to backfill all history.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=int,
            metavar='USER_ID',
            help='Generate summary for a specific user ID only',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Generate summaries for all active users',
        )
        parser.add_argument(
            '--month',
            type=int,
            metavar='MONTH',
            help='Month number (1-12) to generate summary for',
        )
        parser.add_argument(
            '--year',
            type=int,
            metavar='YEAR',
            help='Year to generate summary for',
        )
        parser.add_argument(
            '--all-months',
            action='store_true',
            help='Backfill summaries for all months that have transaction data',
        )

    def handle(self, *args, **options):
        User = get_user_model()
        today = timezone.now().date()

        if options['user']:
            users = User.objects.filter(pk=options['user'])
        elif options['all_users']:
            users = User.objects.filter(is_active=True)
        else:
            self.stderr.write('Specify --user USER_ID or --all-users.')
            return

        if options['month'] and options['year']:
            months_to_process = [(options['year'], options['month'])]
        elif options['all_months']:
            months_to_process = None  # determined per user below
        else:
            year, month = _completed_months(today)
            months_to_process = [(year, month)]

        created_count = 0
        updated_count = 0

        for user in users:
            if options['all_months']:
                earliest = (
                    Transaction.objects.filter(user=user)
                    .order_by('date')
                    .values_list('date', flat=True)
                    .first()
                )
                if not earliest:
                    continue
                target_months = []
                y, m = earliest.year, earliest.month
                end_year, end_month = _completed_months(today)
                while (y, m) <= (end_year, end_month):
                    target_months.append((y, m))
                    m += 1
                    if m > 12:
                        m = 1
                        y += 1
            else:
                target_months = months_to_process

            for year, month in target_months:
                _, created = _build_summary(user, year, month)
                if created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Created: {created_count}, Updated: {updated_count}.'
            )
        )
