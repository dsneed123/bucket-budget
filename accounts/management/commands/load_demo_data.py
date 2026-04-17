import datetime
import random
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from banking.models import BankAccount
from buckets.models import Bucket
from savings.models import SavingsContribution, SavingsGoal
from transactions.models import Transaction

User = get_user_model()

DEMO_EMAIL = 'demo@bucketbudget.com'
DEMO_PASSWORD = 'demo1234!'

EXPENSE_DATA = [
    # (bucket_name, vendor, amount_range, necessity_score)
    ('Food & Dining', 'Whole Foods', (45, 130), 7),
    ('Food & Dining', 'Chipotle', (12, 18), 5),
    ('Food & Dining', 'Starbucks', (6, 9), 3),
    ('Food & Dining', 'Dominos', (20, 35), 4),
    ('Food & Dining', 'Trader Joes', (50, 100), 7),
    ('Food & Dining', 'McDonalds', (8, 14), 3),
    ('Essentials', 'PG&E Electric', (80, 140), 10),
    ('Essentials', 'Water Department', (40, 65), 10),
    ('Essentials', 'Comcast Internet', (70, 90), 8),
    ('Essentials', 'Rent', (1400, 1400), 10),
    ('Transportation', 'Shell Gas Station', (45, 75), 8),
    ('Transportation', 'Uber', (12, 28), 5),
    ('Transportation', 'Lyft', (10, 25), 5),
    ('Transportation', 'Metro Transit', (5, 10), 8),
    ('Transportation', 'EZPass Tolls', (15, 30), 7),
    ('Health', 'CVS Pharmacy', (20, 60), 9),
    ('Health', '24 Hour Fitness', (35, 50), 8),
    ('Health', 'Walgreens', (15, 45), 8),
    ('Shopping', 'Amazon', (25, 120), 4),
    ('Shopping', 'Target', (30, 90), 5),
    ('Shopping', 'Home Depot', (40, 150), 6),
    ('Shopping', 'TJ Maxx', (20, 70), 3),
    ('Entertainment', 'AMC Theaters', (15, 30), 4),
    ('Entertainment', 'Steam Games', (15, 60), 2),
    ('Entertainment', 'Barnes & Noble', (15, 40), 5),
    ('Subscriptions', 'Netflix', (15, 15), 4),
    ('Subscriptions', 'Spotify', (10, 10), 5),
    ('Subscriptions', 'Adobe Creative Cloud', (55, 55), 6),
    ('Subscriptions', 'ChatGPT Plus', (20, 20), 6),
    ('Personal', 'Great Clips', (20, 35), 6),
    ('Personal', 'Amazon Books', (12, 30), 5),
]

INCOME_VENDORS = [
    ('Payroll Direct Deposit', (3200, 3500)),
    ('Freelance Payment', (400, 900)),
    ('Interest Credit', (8, 25)),
]

BUCKET_ALLOCATIONS = {
    'Essentials': Decimal('1700'),
    'Transportation': Decimal('200'),
    'Food & Dining': Decimal('400'),
    'Entertainment': Decimal('100'),
    'Health': Decimal('150'),
    'Shopping': Decimal('200'),
    'Subscriptions': Decimal('120'),
    'Personal': Decimal('100'),
    'Uncategorized': Decimal('0'),
}

SAVINGS_GOALS = [
    {
        'name': 'Emergency Fund',
        'description': '3-6 months of living expenses',
        'target_amount': Decimal('10000'),
        'current_amount': Decimal('3200'),
        'priority': 'critical',
        'goal_type': 'emergency_fund',
        'color': '#ff4757',
        'icon': '🛡️',
        'deadline': None,
    },
    {
        'name': 'Europe Vacation',
        'description': 'Two weeks in Italy and France',
        'target_amount': Decimal('4500'),
        'current_amount': Decimal('1100'),
        'priority': 'medium',
        'goal_type': 'vacation',
        'color': '#0984e3',
        'icon': '✈️',
        'deadline': datetime.date.today() + datetime.timedelta(days=240),
    },
    {
        'name': 'New Laptop',
        'description': 'MacBook Pro for work',
        'target_amount': Decimal('2500'),
        'current_amount': Decimal('800'),
        'priority': 'high',
        'goal_type': 'purchase',
        'color': '#6c5ce7',
        'icon': '💻',
        'deadline': datetime.date.today() + datetime.timedelta(days=90),
    },
]


def _random_amount(lo, hi):
    cents = random.randint(int(lo * 100), int(hi * 100))
    return Decimal(cents) / 100


def _spread_dates(start_date, end_date, count):
    """Return `count` random dates within [start_date, end_date]."""
    delta = (end_date - start_date).days
    dates = sorted(
        start_date + datetime.timedelta(days=random.randint(0, max(delta, 0)))
        for _ in range(count)
    )
    return dates


class Command(BaseCommand):
    help = 'Create a demo user with 3 months of realistic transaction data, buckets, savings goals, and bank accounts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            default=DEMO_EMAIL,
            help=f'Email for the demo user (default: {DEMO_EMAIL}).',
        )
        parser.add_argument(
            '--password',
            default=DEMO_PASSWORD,
            help='Password for the demo user.',
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete the demo user and all related data before recreating.',
        )

    def handle(self, *args, **options):
        email = options['email']
        password = options['password']

        if options['clear']:
            deleted, _ = User.objects.filter(email=email).delete()
            if deleted:
                self.stdout.write(self.style.WARNING(f'Removed existing demo user: {email}'))

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(
                f'Demo user {email} already exists. Run with --clear to reset.'
            ))
            return

        user = User.objects.create_user(
            email=email,
            password=password,
            first_name='Demo',
            last_name='User',
            monthly_income=Decimal('5500'),
        )
        self.stdout.write(f'Created user: {email}')

        self._setup_preferences(user)
        accounts = self._create_bank_accounts(user)
        self._update_bucket_allocations(user)
        goals = self._create_savings_goals(user)
        self._create_transactions(user, accounts, goals)

        self.stdout.write(self.style.SUCCESS(
            f'Demo data loaded successfully. Login: {email} / {password}'
        ))

    def _setup_preferences(self, user):
        from accounts.models import UserPreferences, UserStreak
        UserPreferences.objects.update_or_create(
            user=user,
            defaults={
                'onboarding_complete': True,
                'theme': 'dark',
                'no_spend_goal': 4,
            },
        )
        UserStreak.objects.update_or_create(
            user=user,
            defaults={'current_streak': 3, 'longest_streak': 12},
        )
        self.stdout.write('  Set up user preferences and streak.')

    def _create_bank_accounts(self, user):
        checking = BankAccount.objects.create(
            user=user,
            name='Chase Checking',
            account_type='checking',
            balance=Decimal('4823.17'),
            institution='Chase',
            color='#0984e3',
        )
        savings = BankAccount.objects.create(
            user=user,
            name='Ally Savings',
            account_type='savings',
            balance=Decimal('5100.00'),
            institution='Ally Bank',
            color='#00d4aa',
        )
        credit = BankAccount.objects.create(
            user=user,
            name='Amex Gold',
            account_type='credit',
            balance=Decimal('-642.50'),
            institution='American Express',
            color='#fd79a8',
        )
        self.stdout.write('  Created 3 bank accounts.')
        return {'checking': checking, 'savings': savings, 'credit': credit}

    def _update_bucket_allocations(self, user):
        for bucket in Bucket.objects.filter(user=user):
            alloc = BUCKET_ALLOCATIONS.get(bucket.name)
            if alloc is not None:
                bucket.monthly_allocation = alloc
                bucket.save()
        self.stdout.write('  Updated bucket monthly allocations.')

    def _create_savings_goals(self, user):
        checking = BankAccount.objects.filter(user=user, account_type='checking').first()
        goals = []
        for goal_data in SAVINGS_GOALS:
            goal = SavingsGoal.objects.create(user=user, **goal_data)
            goals.append(goal)

            contrib_amount = goal_data['current_amount']
            if contrib_amount > 0 and checking:
                SavingsContribution.objects.create(
                    goal=goal,
                    source_account=checking,
                    amount=contrib_amount,
                    transaction_type='contribution',
                    date=datetime.date.today() - datetime.timedelta(days=30),
                    note='Initial contribution',
                )
        self.stdout.write(f'  Created {len(goals)} savings goals.')
        return goals

    def _create_transactions(self, user, accounts, _goals):
        checking = accounts['checking']
        credit = accounts['credit']
        today = datetime.date.today()
        three_months_ago = today - datetime.timedelta(days=91)

        buckets_by_name = {b.name: b for b in Bucket.objects.filter(user=user)}

        transactions = []

        # Income: 3 paychecks + occasional freelance
        income_dates = _spread_dates(three_months_ago, today, 6)
        for i, d in enumerate(income_dates):
            vendor, (lo, hi) = INCOME_VENDORS[0] if i % 2 == 0 else INCOME_VENDORS[1]
            transactions.append(Transaction(
                user=user,
                account=checking,
                bucket=None,
                amount=_random_amount(lo, hi),
                transaction_type='income',
                description=vendor,
                vendor=vendor,
                date=d,
            ))

        # Expenses: pick ~60 entries spread across 3 months
        expense_sample = random.choices(EXPENSE_DATA, k=70)
        expense_dates = _spread_dates(three_months_ago, today, len(expense_sample))

        for expense_def, d in zip(expense_sample, expense_dates):
            bucket_name, vendor, (lo, hi), necessity = expense_def
            bucket = buckets_by_name.get(bucket_name)
            account = credit if bucket_name in ('Subscriptions', 'Shopping', 'Entertainment') else checking
            transactions.append(Transaction(
                user=user,
                account=account,
                bucket=bucket,
                amount=_random_amount(lo, hi),
                transaction_type='expense',
                description=vendor,
                vendor=vendor,
                date=d,
                necessity_score=necessity,
            ))

        Transaction.objects.bulk_create(transactions)
        self.stdout.write(f'  Created {len(transactions)} transactions over 3 months.')
