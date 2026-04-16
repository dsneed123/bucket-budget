import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from rankings.models import NecessitySnapshot
from transactions.models import Transaction

# necessity_score bands: want=1-3, useful=4-7, need=8-10
WANT_MAX = 3
USEFUL_MAX = 7


def _week_bounds(ref_date):
    """Return (monday, sunday) for the ISO week containing ref_date."""
    monday = ref_date - datetime.timedelta(days=ref_date.weekday())
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def _month_bounds(ref_date):
    """Return (first, last) day of the month containing ref_date."""
    first = ref_date.replace(day=1)
    if ref_date.month == 12:
        last = ref_date.replace(month=12, day=31)
    else:
        last = ref_date.replace(month=ref_date.month + 1, day=1) - datetime.timedelta(days=1)
    return first, last


def _build_snapshot(user, period_start, period_end):
    """Compute and upsert a NecessitySnapshot for (user, period_start, period_end)."""
    expenses = Transaction.objects.filter(
        user=user,
        transaction_type='expense',
        date__gte=period_start,
        date__lte=period_end,
    )

    totals = expenses.aggregate(
        total=Sum('amount'),
        count=Count('id'),
        avg=Avg('necessity_score'),
    )

    total_spend = totals['total'] or 0
    transaction_count = totals['count'] or 0
    avg_score = totals['avg']

    want_spend = expenses.filter(necessity_score__lte=WANT_MAX).aggregate(s=Sum('amount'))['s'] or 0
    useful_spend = expenses.filter(
        necessity_score__gt=WANT_MAX,
        necessity_score__lte=USEFUL_MAX,
    ).aggregate(s=Sum('amount'))['s'] or 0
    need_spend = expenses.filter(necessity_score__gt=USEFUL_MAX).aggregate(s=Sum('amount'))['s'] or 0
    unscored_spend = expenses.filter(necessity_score__isnull=True).aggregate(s=Sum('amount'))['s'] or 0

    snapshot, created = NecessitySnapshot.objects.update_or_create(
        user=user,
        period_start=period_start,
        period_end=period_end,
        defaults=dict(
            avg_score=avg_score,
            total_spend=total_spend,
            want_spend=want_spend,
            useful_spend=useful_spend,
            need_spend=need_spend,
            unscored_spend=unscored_spend,
            transaction_count=transaction_count,
        ),
    )
    return snapshot, created


class Command(BaseCommand):
    help = (
        'Generate NecessitySnapshot records for weekly or monthly periods. '
        'Defaults to the current period. Use --all-users to run for every user.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--period',
            choices=['weekly', 'monthly'],
            default='weekly',
            help='Period type to snapshot (default: weekly)',
        )
        parser.add_argument(
            '--user',
            type=int,
            metavar='USER_ID',
            help='Generate snapshot for a specific user ID only',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Generate snapshots for all active users',
        )
        parser.add_argument(
            '--date',
            help='Reference date (YYYY-MM-DD) to determine the period (default: today)',
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options['date']:
            ref_date = datetime.date.fromisoformat(options['date'])
        else:
            ref_date = timezone.now().date()

        if options['period'] == 'weekly':
            period_start, period_end = _week_bounds(ref_date)
        else:
            period_start, period_end = _month_bounds(ref_date)

        self.stdout.write(
            f"Generating {options['period']} snapshot for {period_start} – {period_end}"
        )

        if options['user']:
            users = User.objects.filter(pk=options['user'])
        elif options['all_users']:
            users = User.objects.filter(is_active=True)
        else:
            self.stderr.write('Specify --user USER_ID or --all-users.')
            return

        created_count = 0
        updated_count = 0

        for user in users:
            _, created = _build_snapshot(user, period_start, period_end)
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Done. Created: {created_count}, Updated: {updated_count}.'
            )
        )
