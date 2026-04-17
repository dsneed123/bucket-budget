import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from transactions.models import RecurringTransaction, Transaction
from transactions.utils import advance_next_due


class Command(BaseCommand):
    help = 'Process due recurring transactions and create Transaction records.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes.',
        )
        parser.add_argument(
            '--date',
            help='Reference date (YYYY-MM-DD) instead of today.',
        )

    def handle(self, *args, **options):
        if options['date']:
            today = datetime.date.fromisoformat(options['date'])
        else:
            today = timezone.now().date()

        dry_run = options['dry_run']

        due_recurring = RecurringTransaction.objects.filter(
            is_active=True,
            next_due__lte=today,
        ).select_related('user', 'account', 'bucket')

        self.stdout.write(
            f"Processing recurring transactions due on or before {today}"
            + (' [DRY RUN]' if dry_run else '')
        )

        processed = 0
        skipped = 0

        for rt in due_recurring:
            if rt.end_date and rt.next_due > rt.end_date:
                self.stdout.write(
                    f"  SKIP recurring {rt.pk}: past end_date {rt.end_date}."
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  {'[DRY RUN] ' if dry_run else ''}Recurring {rt.pk}: "
                f"${rt.amount} {rt.transaction_type} '{rt.description}' "
                f"(due {rt.next_due}, {rt.frequency})"
            )

            if not dry_run:
                Transaction.objects.create(
                    user=rt.user,
                    account=rt.account,
                    bucket=rt.bucket,
                    amount=rt.amount,
                    transaction_type=rt.transaction_type,
                    description=rt.description,
                    vendor=rt.vendor,
                    date=rt.next_due,
                    is_recurring=True,
                )

                rt.last_generated = rt.next_due
                rt.next_due = advance_next_due(rt.next_due, rt.frequency)
                rt.save()

            processed += 1

        self.stdout.write(
            self.style.SUCCESS(f'Done. Processed: {processed}, Skipped: {skipped}.')
        )
