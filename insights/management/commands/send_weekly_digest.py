import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.db.models import Avg, Count, Sum
from django.utils import timezone

from buckets.models import Bucket
from transactions.models import Transaction

from insights.models import Recommendation
from insights.recommendations import refresh_recommendations


def _week_date_range(ref_date):
    """Return (start, end) for the 7-day period ending on ref_date."""
    end = ref_date
    start = end - datetime.timedelta(days=6)
    return start, end


def _week_expenses(user, start, end):
    return (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=start, date__lte=end,
        ).aggregate(s=Sum('amount'))['s'] or Decimal('0')
    )


def _top_categories(user, start, end, limit=5):
    """Return list of (bucket_name, total_spent) sorted by total descending."""
    rows = (
        Transaction.objects.filter(
            user=user, transaction_type='expense',
            date__gte=start, date__lte=end,
            bucket__isnull=False,
        )
        .values('bucket__name')
        .annotate(total=Sum('amount'))
        .order_by('-total')[:limit]
    )
    return [(r['bucket__name'], r['total']) for r in rows]


def _spending_quality(user, start, end):
    """Return (avg_score, scored_count) for the period, or (None, 0)."""
    result = Transaction.objects.filter(
        user=user, transaction_type='expense',
        date__gte=start, date__lte=end,
        necessity_score__isnull=False,
    ).aggregate(avg=Avg('necessity_score'), count=Count('id'))
    if not result['count']:
        return None, 0
    return round(Decimal(str(result['avg'])), 1), result['count']


def _quality_label(score):
    if score is None:
        return 'No scored transactions'
    if score >= 7:
        return f'{score}/10 — Excellent'
    if score >= 4:
        return f'{score}/10 — Fair'
    return f'{score}/10 — Needs attention'


def _build_digest(user, start, end):
    """Return a dict of digest data for the user."""
    total_spent = _week_expenses(user, start, end)
    top_cats = _top_categories(user, start, end)
    quality_score, scored_count = _spending_quality(user, start, end)
    refresh_recommendations(user)
    recs = list(
        Recommendation.objects.filter(user=user, is_dismissed=False)
        .order_by('-priority', '-created_at')[:5]
    )
    return {
        'user': user,
        'start': start,
        'end': end,
        'total_spent': total_spent,
        'top_categories': top_cats,
        'quality_score': quality_score,
        'quality_label': _quality_label(quality_score),
        'scored_count': scored_count,
        'recommendations': recs,
    }


def _render_text(digest):
    user = digest['user']
    name = user.first_name or user.email
    currency = getattr(user, 'currency', 'USD')
    lines = [
        f'Hi {name},',
        '',
        f'Here\'s your weekly spending digest for {digest["start"]} – {digest["end"]}.',
        '',
        f'TOTAL SPENT: {currency} {digest["total_spent"]:,.2f}',
        '',
        'TOP CATEGORIES:',
    ]
    if digest['top_categories']:
        for cat_name, total in digest['top_categories']:
            lines.append(f'  • {cat_name}: {currency} {total:,.2f}')
    else:
        lines.append('  No categorized spending this week.')
    lines += [
        '',
        f'SPENDING QUALITY: {digest["quality_label"]}',
        f'  ({digest["scored_count"]} scored transaction{"s" if digest["scored_count"] != 1 else ""})',
        '',
    ]
    if digest['recommendations']:
        lines.append('RECOMMENDATIONS:')
        for rec in digest['recommendations']:
            lines.append(f'  [{rec.priority.upper()}] {rec.message}')
    else:
        lines.append('RECOMMENDATIONS: None this week — great job!')
    lines += [
        '',
        '— Bucket Budget',
    ]
    return '\n'.join(lines)


def _render_html(digest):
    user = digest['user']
    name = user.first_name or user.email
    currency = getattr(user, 'currency', 'USD')

    cat_rows = ''
    if digest['top_categories']:
        for cat_name, total in digest['top_categories']:
            cat_rows += (
                f'<tr><td style="padding:4px 8px">{cat_name}</td>'
                f'<td style="padding:4px 8px;text-align:right">'
                f'{currency} {total:,.2f}</td></tr>'
            )
    else:
        cat_rows = '<tr><td colspan="2" style="padding:4px 8px">No categorized spending this week.</td></tr>'

    rec_items = ''
    if digest['recommendations']:
        for rec in digest['recommendations']:
            priority_color = {'high': '#d63031', 'medium': '#e17055', 'low': '#00b894'}.get(rec.priority, '#636e72')
            rec_items += (
                f'<li style="margin-bottom:8px">'
                f'<span style="color:{priority_color};font-weight:bold;text-transform:uppercase">'
                f'{rec.priority}</span> — {rec.message}</li>'
            )
    else:
        rec_items = '<li>None this week — great job!</li>'

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:20px;color:#2d3436">
  <h2 style="color:#0984e3">Weekly Spending Digest</h2>
  <p>Hi {name},</p>
  <p>Here's your spending summary for <strong>{digest['start']}</strong> – <strong>{digest['end']}</strong>.</p>

  <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
    <tr style="background:#0984e3;color:#fff">
      <td style="padding:8px 12px;font-size:18px" colspan="2">
        Total Spent: {currency} {digest['total_spent']:,.2f}
      </td>
    </tr>
  </table>

  <h3 style="border-bottom:2px solid #dfe6e9;padding-bottom:6px">Top Categories</h3>
  <table style="width:100%;border-collapse:collapse;margin-bottom:20px">
    {cat_rows}
  </table>

  <h3 style="border-bottom:2px solid #dfe6e9;padding-bottom:6px">Spending Quality</h3>
  <p style="margin-bottom:4px"><strong>{digest['quality_label']}</strong></p>
  <p style="color:#636e72;font-size:14px">
    {digest['scored_count']} scored transaction{"s" if digest['scored_count'] != 1 else ""}
  </p>

  <h3 style="border-bottom:2px solid #dfe6e9;padding-bottom:6px">Recommendations</h3>
  <ul style="padding-left:20px">{rec_items}</ul>

  <hr style="border:none;border-top:1px solid #dfe6e9;margin:24px 0">
  <p style="color:#636e72;font-size:12px">— Bucket Budget</p>
</body>
</html>"""


def send_digest(user, start, end, dry_run=False):
    """Build and send the weekly digest email for a single user. Returns True if sent."""
    if not user.email:
        return False
    digest = _build_digest(user, start, end)
    subject = f'Your Weekly Spending Digest ({start} – {end})'
    text_body = _render_text(digest)
    html_body = _render_html(digest)

    if dry_run:
        return True

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        to=[user.email],
    )
    msg.attach_alternative(html_body, 'text/html')
    msg.send()
    return True


class Command(BaseCommand):
    help = (
        'Send a weekly spending digest email to users. '
        'Includes total spent, top categories, spending quality, and recommendations.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=int,
            metavar='USER_ID',
            help='Send digest for a specific user ID only',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Send digest to all active users with an email address',
        )
        parser.add_argument(
            '--date',
            metavar='YYYY-MM-DD',
            help='Reference date for the 7-day window ending on this date (default: today)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Compute digests but do not send any emails',
        )

    def handle(self, *args, **options):
        User = get_user_model()

        if options['user']:
            users = User.objects.filter(pk=options['user'], is_active=True)
        elif options['all_users']:
            users = User.objects.filter(is_active=True).exclude(email='')
        else:
            self.stderr.write('Specify --user USER_ID or --all-users.')
            return

        if options['date']:
            ref_date = datetime.date.fromisoformat(options['date'])
        else:
            ref_date = timezone.now().date()

        start, end = _week_date_range(ref_date)
        dry_run = options['dry_run']

        sent = 0
        skipped = 0
        for user in users:
            ok = send_digest(user, start, end, dry_run=dry_run)
            if ok:
                sent += 1
            else:
                skipped += 1

        mode = '[DRY RUN] ' if dry_run else ''
        self.stdout.write(
            self.style.SUCCESS(
                f'{mode}Done. Sent: {sent}, Skipped: {skipped}.'
            )
        )
