import datetime

from django.utils import timezone

from transactions.models import RecurringTransaction, Transaction
from transactions.utils import advance_next_due


class ProcessRecurringMiddleware:
    """Run process_recurring for the authenticated user once per day (tracked in session)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            today = timezone.now().date()
            session_key = 'recurring_processed_date'
            last_processed = request.session.get(session_key)

            if last_processed != today.isoformat():
                self._process_for_user(request.user, today)
                request.session[session_key] = today.isoformat()

        return self.get_response(request)

    def _process_for_user(self, user, today):
        due = RecurringTransaction.objects.filter(
            user=user,
            is_active=True,
            next_due__lte=today,
        ).select_related('account', 'bucket')

        for rt in due:
            if rt.end_date and rt.next_due > rt.end_date:
                continue

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
