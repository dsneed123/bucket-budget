import calendar
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from savings.models import AutoSaveRule, SavingsContribution


def _advance_next_run(current_date, frequency):
    """Return the next run date after current_date based on frequency."""
    if frequency == 'weekly':
        return current_date + datetime.timedelta(days=7)
    elif frequency == 'biweekly':
        return current_date + datetime.timedelta(days=14)
    else:  # monthly
        month = current_date.month + 1
        year = current_date.year
        if month > 12:
            month = 1
            year += 1
        day = min(current_date.day, calendar.monthrange(year, month)[1])
        return current_date.replace(year=year, month=month, day=day)


class Command(BaseCommand):
    help = 'Process due auto-save rules and create contributions.'

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

        due_rules = AutoSaveRule.objects.filter(
            is_active=True,
            next_run__lte=today,
        ).select_related('user', 'goal', 'source_account')

        self.stdout.write(
            f"Processing auto-save rules due on or before {today}"
            + (' [DRY RUN]' if dry_run else '')
        )

        processed = 0
        skipped = 0

        for rule in due_rules:
            if rule.goal.is_achieved:
                self.stdout.write(
                    f"  SKIP rule {rule.pk}: goal '{rule.goal.name}' is already achieved."
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  {'[DRY RUN] ' if dry_run else ''}Rule {rule.pk}: "
                f"${rule.amount} → '{rule.goal.name}' from '{rule.source_account.name}'"
            )

            if not dry_run:
                SavingsContribution.objects.create(
                    goal=rule.goal,
                    amount=rule.amount,
                    source_account=rule.source_account,
                    date=today,
                    note=f'Auto-save ({rule.get_frequency_display().lower()})',
                )

                rule.goal.refresh_from_db()
                if rule.goal.current_amount >= rule.goal.target_amount and not rule.goal.is_achieved:
                    rule.goal.is_achieved = True
                    rule.goal.save()

                rule.next_run = _advance_next_run(rule.next_run, rule.frequency)
                rule.save()

            processed += 1

        self.stdout.write(
            self.style.SUCCESS(f'Done. Processed: {processed}, Skipped: {skipped}.')
        )
