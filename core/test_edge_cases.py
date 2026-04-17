import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse

from accounts.currencies import format_currency
from accounts.utils import get_current_fiscal_month, get_fiscal_month_range
from banking.models import BankAccount
from buckets.models import Bucket
from savings.models import SavingsContribution, SavingsGoal
from transactions.models import Transaction
from transactions.views import _parse_csv_rows

User = get_user_model()


class ZeroAmountTransactionTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='zero@example.com',
            password='testpass',
            first_name='Zero',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('500.00'),
        )
        self.client.login(email='zero@example.com', password='testpass')

    def _post(self, **overrides):
        data = {
            'amount': '25.00',
            'transaction_type': 'expense',
            'description': 'Test',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-01-15',
        }
        data.update(overrides)
        return self.client.post(reverse('transaction_add'), data)

    def test_zero_amount_expense_rejected(self):
        response = self._post(amount='0')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'greater than zero')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_zero_amount_income_rejected(self):
        response = self._post(amount='0', transaction_type='income')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'greater than zero')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_minimum_valid_amount_accepted(self):
        response = self._post(amount='0.01')
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.amount, Decimal('0.01'))

    def test_zero_amount_does_not_alter_balance(self):
        # View rejects zero, so balance must remain unchanged
        self._post(amount='0')
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal('500.00'))

    def test_model_allows_zero_amount_directly(self):
        # No model-level validator blocks zero — enforcement is in the view
        txn = Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal('0.00'),
            transaction_type='expense',
            description='Zero txn',
            date=datetime.date(2026, 1, 15),
        )
        txn.refresh_from_db()
        self.assertEqual(txn.amount, Decimal('0.00'))


class NegativeBalanceTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='negbal@example.com',
            password='testpass',
            first_name='Neg',
            last_name='User',
        )
        self.client.login(email='negbal@example.com', password='testpass')

    def test_expense_can_push_account_negative(self):
        account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('10.00'),
        )
        self.client.post(reverse('transaction_add'), {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Overdraft expense',
            'vendor': '',
            'bucket': '',
            'account': str(account.pk),
            'date': '2026-01-31',
        })
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('-40.00'))

    def test_credit_account_starts_negative(self):
        account = BankAccount.objects.create(
            user=self.user,
            name='Credit Card',
            account_type='credit',
            balance=Decimal('-500.00'),
        )
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('-500.00'))

    def test_income_brings_negative_balance_toward_zero(self):
        account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('-100.00'),
        )
        self.client.post(reverse('transaction_add'), {
            'amount': '60.00',
            'transaction_type': 'income',
            'description': 'Paycheck',
            'vendor': '',
            'bucket': '',
            'account': str(account.pk),
            'date': '2026-01-31',
        })
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal('-40.00'))

    def test_balance_history_records_negative_result(self):
        from banking.models import BalanceHistory
        account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('20.00'),
        )
        self.client.post(reverse('transaction_add'), {
            'amount': '100.00',
            'transaction_type': 'expense',
            'description': 'Big expense',
            'vendor': '',
            'bucket': '',
            'account': str(account.pk),
            'date': '2026-01-31',
        })
        account.refresh_from_db()
        history = BalanceHistory.objects.filter(account=account).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.new_balance, Decimal('-80.00'))


class BucketOverBudgetTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='overbudget@example.com',
            password='testpass',
            first_name='Over',
            last_name='User',
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Dining',
            monthly_allocation=Decimal('200.00'),
        )

    def test_remaining_is_negative_when_over_budget(self):
        self.bucket.spent_this_month = lambda: Decimal('250.00')
        self.assertEqual(self.bucket.remaining_this_month(), Decimal('-50.00'))

    def test_percentage_capped_at_100_when_over_budget(self):
        self.bucket.spent_this_month = lambda: Decimal('400.00')
        self.assertEqual(self.bucket.percentage_used(), 100)

    def test_percentage_exactly_100_at_budget(self):
        self.bucket.spent_this_month = lambda: Decimal('200.00')
        self.assertEqual(self.bucket.percentage_used(), 100)

    def test_alert_threshold_triggers_at_full_spend(self):
        self.bucket.alert_threshold = 90
        self.bucket.spent_this_month = lambda: Decimal('200.00')
        pct = self.bucket.percentage_used()
        self.assertGreaterEqual(pct, self.bucket.alert_threshold)

    def test_zero_allocation_never_goes_negative(self):
        zero_bucket = Bucket.objects.create(
            user=self.user,
            name='Misc',
            monthly_allocation=Decimal('0.00'),
        )
        self.assertEqual(zero_bucket.remaining_this_month(), Decimal('0.00'))

    def test_remaining_correctly_reports_exact_overage(self):
        self.bucket.spent_this_month = lambda: Decimal('350.00')
        self.assertEqual(self.bucket.remaining_this_month(), Decimal('-150.00'))


class SavingsGoalExceededTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='goalexceed@example.com',
            password='testpass',
            first_name='Goal',
            last_name='User',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Savings',
            account_type='savings',
            balance=Decimal('5000.00'),
        )
        self.goal = SavingsGoal.objects.create(
            user=self.user,
            name='Vacation',
            target_amount=Decimal('1000.00'),
            current_amount=Decimal('900.00'),
        )
        self.client.login(email='goalexceed@example.com', password='testpass')

    def _contribute(self, amount):
        return self.client.post(
            reverse('savings:savings_goal_contribute', kwargs={'goal_id': self.goal.pk}),
            {
                'amount': str(amount),
                'source_account': str(self.account.pk),
                'note': '',
            },
        )

    def _withdraw(self, amount):
        return self.client.post(
            reverse('savings:savings_goal_withdraw', kwargs={'goal_id': self.goal.pk}),
            {
                'amount': str(amount),
                'target_account': str(self.account.pk),
                'note': '',
            },
        )

    def test_contribution_reaching_target_sets_is_achieved(self):
        self._contribute('100.00')
        self.goal.refresh_from_db()
        self.assertTrue(self.goal.is_achieved)

    def test_contribution_exceeding_target_still_sets_is_achieved(self):
        self._contribute('500.00')
        self.goal.refresh_from_db()
        self.assertTrue(self.goal.is_achieved)
        self.assertEqual(self.goal.current_amount, Decimal('1400.00'))

    def test_100_percent_milestone_created_on_reaching_target(self):
        from savings.models import SavingsMilestone
        self._contribute('100.00')
        self.goal.refresh_from_db()
        self.assertTrue(SavingsMilestone.objects.filter(goal=self.goal, percentage=100).exists())

    def test_withdrawal_below_target_clears_is_achieved(self):
        self.goal.is_achieved = True
        self.goal.current_amount = Decimal('1000.00')
        self.goal.save()

        self._withdraw('200.00')
        self.goal.refresh_from_db()
        self.assertFalse(self.goal.is_achieved)

    def test_current_amount_exceeds_target_no_validation_error(self):
        # Over-contribution is allowed at model level
        contribution = SavingsContribution.objects.create(
            goal=self.goal,
            amount=Decimal('500.00'),
            source_account=self.account,
            date=datetime.date(2026, 4, 16),
        )
        self.goal.refresh_from_db()
        self.assertGreater(self.goal.current_amount, self.goal.target_amount)
        self.assertIsNotNone(contribution.pk)


class DuplicateTransactionEdgeCaseTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='dupedge@example.com',
            password='testpass',
            first_name='Dup',
            last_name='Edge',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.client.login(email='dupedge@example.com', password='testpass')

    def _existing(self, date, amount='50.00', vendor='Test Store'):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            amount=Decimal(amount),
            transaction_type='expense',
            description='Existing purchase',
            vendor=vendor,
            date=date,
        )

    def _post(self, date, amount='50.00', vendor='Test Store', txn_type='expense'):
        return self.client.post(reverse('transaction_add'), {
            'amount': amount,
            'transaction_type': txn_type,
            'description': 'New purchase',
            'vendor': vendor,
            'bucket': '',
            'account': str(self.account.pk),
            'date': date,
        })

    def test_transaction_exactly_7_days_later_triggers_warning(self):
        self._existing(datetime.date(2026, 4, 9))
        response = self._post('2026-04-16')
        self.assertContains(response, 'Similar transaction found')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_transaction_exactly_7_days_earlier_triggers_warning(self):
        self._existing(datetime.date(2026, 4, 23))
        response = self._post('2026-04-16')
        self.assertContains(response, 'Similar transaction found')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_different_amount_same_vendor_no_duplicate(self):
        self._existing(datetime.date(2026, 4, 16))
        response = self._post('2026-04-16', amount='99.99')
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_income_type_does_not_trigger_duplicate_check(self):
        # Duplicate detection only runs when vendor is present AND transaction is saved
        # Income transactions can still have vendors — window applies equally
        # But the concern is different amounts for income won't flag
        self._existing(datetime.date(2026, 4, 16), vendor='Employer')
        response = self._post('2026-04-16', vendor='Employer', txn_type='income')
        # Same amount+vendor+date — should trigger even for income
        self.assertContains(response, 'Similar transaction found')

    def test_force_save_bypasses_duplicate_warning(self):
        self._existing(datetime.date(2026, 4, 16))
        response = self.client.post(reverse('transaction_add'), {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Forced duplicate',
            'vendor': 'Test Store',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-04-16',
            'force_save': '1',
        })
        self.assertRedirects(response, reverse('transaction_list'))
        self.assertEqual(Transaction.objects.count(), 2)

    def test_no_vendor_skips_duplicate_detection(self):
        self._existing(datetime.date(2026, 4, 16), vendor='')
        # Post with same amount/date but no vendor — no warning
        response = self._post('2026-04-16', vendor='')
        # Without vendor, should proceed to save without warning
        self.assertRedirects(response, reverse('transaction_list'))


class CsvImportBadDataTest(TestCase):
    """Tests for _parse_csv_rows with malformed input."""

    def setUp(self):
        self.user = User.objects.create_user(
            email='csvbad@example.com',
            password='testpass',
            first_name='CSV',
            last_name='Bad',
        )
        self.bucket = Bucket.objects.create(
            user=self.user,
            name='Groceries',
            monthly_allocation=Decimal('300.00'),
        )
        self.mapping = {'date': 'date', 'description': 'description', 'amount': 'amount'}
        self.bucket_map = {'groceries': self.bucket}

    def _parse(self, rows):
        return _parse_csv_rows(rows, self.mapping, self.bucket_map)

    def test_invalid_date_format_produces_error_row(self):
        preview, importable = self._parse([
            {'date': '16-04-2026', 'description': 'Groceries', 'amount': '-30.00'},
        ])
        self.assertEqual(preview[0]['status'], 'error')
        self.assertIn('unrecognised date', preview[0]['error'])
        self.assertEqual(len(importable), 0)

    def test_non_numeric_amount_produces_error_row(self):
        preview, importable = self._parse([
            {'date': '2026-04-16', 'description': 'Groceries', 'amount': 'N/A'},
        ])
        self.assertEqual(preview[0]['status'], 'error')
        self.assertIn('invalid amount', preview[0]['error'])
        self.assertEqual(len(importable), 0)

    def test_missing_description_produces_error_row(self):
        preview, importable = self._parse([
            {'date': '2026-04-16', 'description': '', 'amount': '-20.00'},
        ])
        self.assertEqual(preview[0]['status'], 'error')
        self.assertIn('missing description', preview[0]['error'])

    def test_missing_amount_produces_error_row(self):
        preview, importable = self._parse([
            {'date': '2026-04-16', 'description': 'Test', 'amount': ''},
        ])
        self.assertEqual(preview[0]['status'], 'error')
        self.assertIn('missing amount', preview[0]['error'])

    def test_missing_date_produces_error_row(self):
        preview, importable = self._parse([
            {'date': '', 'description': 'Test', 'amount': '-10.00'},
        ])
        self.assertEqual(preview[0]['status'], 'error')
        self.assertIn('missing date', preview[0]['error'])

    def test_mixed_rows_separates_good_from_bad(self):
        preview, importable = self._parse([
            {'date': '2026-04-16', 'description': 'Good row', 'amount': '-50.00'},
            {'date': 'bad-date', 'description': 'Bad row', 'amount': '-20.00'},
            {'date': '2026-04-17', 'description': 'Another good', 'amount': '100.00'},
        ])
        self.assertEqual(len(preview), 3)
        self.assertEqual(preview[0]['status'], 'ok')
        self.assertEqual(preview[1]['status'], 'error')
        self.assertEqual(preview[2]['status'], 'ok')
        self.assertEqual(len(importable), 2)

    def test_amount_with_commas_is_valid(self):
        preview, importable = self._parse([
            {'date': '2026-04-16', 'description': 'Big purchase', 'amount': '-1,500.00'},
        ])
        self.assertEqual(preview[0]['status'], 'ok')
        self.assertEqual(preview[0]['amount'], '1500.00')

    def test_positive_amount_inferred_as_income(self):
        preview, _ = self._parse([
            {'date': '2026-04-16', 'description': 'Paycheck', 'amount': '2000.00'},
        ])
        self.assertEqual(preview[0]['transaction_type'], 'income')

    def test_negative_amount_inferred_as_expense(self):
        preview, _ = self._parse([
            {'date': '2026-04-16', 'description': 'Groceries', 'amount': '-50.00'},
        ])
        self.assertEqual(preview[0]['transaction_type'], 'expense')

    def test_multiple_errors_in_same_row_reported_together(self):
        preview, _ = self._parse([
            {'date': '', 'description': '', 'amount': ''},
        ])
        error_text = preview[0]['error']
        self.assertIn('missing date', error_text)
        self.assertIn('missing description', error_text)
        self.assertIn('missing amount', error_text)

    def test_empty_rows_list_returns_empty_results(self):
        preview, importable = self._parse([])
        self.assertEqual(preview, [])
        self.assertEqual(importable, [])

    def test_upload_empty_csv_shows_error(self):
        client = Client()
        client.login(email='csvbad@example.com', password='testpass')
        account = BankAccount.objects.create(
            user=self.user, name='Checking', account_type='checking', balance=Decimal('0'),
        )
        f = io.BytesIO(b'date,description,amount\n')
        f.name = 'empty.csv'
        response = client.post(reverse('transaction_import_csv'), {
            'step': 'upload',
            'account': str(account.pk),
            'csv_file': f,
        })
        self.assertContains(response, 'no data rows')

    def test_upload_csv_with_no_header_shows_error(self):
        client = Client()
        client.login(email='csvbad@example.com', password='testpass')
        account = BankAccount.objects.create(
            user=self.user, name='Checking2', account_type='checking', balance=Decimal('0'),
        )
        f = io.BytesIO(b'')
        f.name = 'noheader.csv'
        response = client.post(reverse('transaction_import_csv'), {
            'step': 'upload',
            'account': str(account.pk),
            'csv_file': f,
        })
        self.assertContains(response, 'empty')


class CurrencyFormattingTest(TestCase):
    def test_usd_formats_with_dollar_symbol(self):
        self.assertEqual(format_currency(Decimal('1234.56'), 'USD'), '$1,234.56')

    def test_eur_formats_with_euro_symbol(self):
        self.assertEqual(format_currency(Decimal('1234.56'), 'EUR'), '€1,234.56')

    def test_gbp_formats_with_pound_symbol(self):
        self.assertEqual(format_currency(Decimal('99.99'), 'GBP'), '£99.99')

    def test_jpy_formats_with_no_decimals(self):
        self.assertEqual(format_currency(1500, 'JPY'), '¥1,500')

    def test_inr_formats_with_rupee_symbol(self):
        self.assertEqual(format_currency(Decimal('500.00'), 'INR'), '₹500.00')

    def test_cad_formats_correctly(self):
        self.assertEqual(format_currency(Decimal('100.00'), 'CAD'), 'CA$100.00')

    def test_unknown_currency_falls_back_to_code_prefix(self):
        result = format_currency(Decimal('50.00'), 'XYZ')
        self.assertIn('XYZ', result)
        self.assertIn('50.00', result)

    def test_zero_amount_usd(self):
        self.assertEqual(format_currency(Decimal('0.00'), 'USD'), '$0.00')

    def test_large_number_has_comma_separator(self):
        result = format_currency(Decimal('1000000.00'), 'USD')
        self.assertIn(',', result)
        self.assertEqual(result, '$1,000,000.00')

    def test_lowercase_currency_code_accepted(self):
        self.assertEqual(format_currency(Decimal('10.00'), 'usd'), '$10.00')

    def test_non_numeric_value_returned_as_is(self):
        result = format_currency('not-a-number', 'USD')
        self.assertEqual(result, 'not-a-number')

    def test_none_value_returned_as_is(self):
        result = format_currency(None, 'USD')
        self.assertIsNone(result)

    def test_jpy_large_amount_no_decimal_point(self):
        result = format_currency(10000, 'JPY')
        self.assertNotIn('.', result)
        self.assertEqual(result, '¥10,000')


class DateBoundaryTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            email='dateboundary@example.com',
            password='testpass',
            first_name='Date',
            last_name='Boundary',
        )
        self.account = BankAccount.objects.create(
            user=self.user,
            name='Checking',
            account_type='checking',
            balance=Decimal('1000.00'),
        )
        self.client.login(email='dateboundary@example.com', password='testpass')

    def test_transaction_on_january_31(self):
        response = self.client.post(reverse('transaction_add'), {
            'amount': '50.00',
            'transaction_type': 'expense',
            'description': 'Jan 31 purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-01-31',
        })
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.date, datetime.date(2026, 1, 31))

    def test_transaction_on_february_28(self):
        response = self.client.post(reverse('transaction_add'), {
            'amount': '30.00',
            'transaction_type': 'expense',
            'description': 'Feb 28 purchase',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-02-28',
        })
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.date, datetime.date(2026, 2, 28))

    def test_transaction_on_december_31(self):
        response = self.client.post(reverse('transaction_add'), {
            'amount': '75.00',
            'transaction_type': 'expense',
            'description': 'New Years Eve',
            'vendor': '',
            'bucket': '',
            'account': str(self.account.pk),
            'date': '2026-12-31',
        })
        self.assertRedirects(response, reverse('transaction_list'))
        txn = Transaction.objects.get(user=self.user)
        self.assertEqual(txn.date, datetime.date(2026, 12, 31))

    def test_fiscal_month_range_standard_january(self):
        start, end = get_fiscal_month_range(2026, 1, 1)
        self.assertEqual(start, datetime.date(2026, 1, 1))
        self.assertEqual(end, datetime.date(2026, 1, 31))

    def test_fiscal_month_range_standard_february_non_leap(self):
        start, end = get_fiscal_month_range(2026, 2, 1)
        self.assertEqual(start, datetime.date(2026, 2, 1))
        self.assertEqual(end, datetime.date(2026, 2, 28))

    def test_fiscal_month_range_standard_february_leap_year(self):
        start, end = get_fiscal_month_range(2024, 2, 1)
        self.assertEqual(start, datetime.date(2024, 2, 1))
        self.assertEqual(end, datetime.date(2024, 2, 29))

    def test_fiscal_month_range_standard_december(self):
        start, end = get_fiscal_month_range(2026, 12, 1)
        self.assertEqual(start, datetime.date(2026, 12, 1))
        self.assertEqual(end, datetime.date(2026, 12, 31))

    def test_fiscal_month_range_custom_start_crosses_year(self):
        # fiscal_month_start=15: December's period = Dec 15 to Jan 14
        start, end = get_fiscal_month_range(2026, 12, 15)
        self.assertEqual(start, datetime.date(2026, 12, 15))
        self.assertEqual(end, datetime.date(2027, 1, 14))

    def test_get_current_fiscal_month_last_day_of_month(self):
        # On the last day of the month with fiscal_month_start=1, still in current month
        today = datetime.date(2026, 1, 31)
        year, month = get_current_fiscal_month(today, 1)
        self.assertEqual((year, month), (2026, 1))

    def test_get_current_fiscal_month_custom_before_boundary(self):
        # fiscal_month_start=15: April 14 → labeled as March
        today = datetime.date(2026, 4, 14)
        year, month = get_current_fiscal_month(today, 15)
        self.assertEqual((year, month), (2026, 3))

    def test_get_current_fiscal_month_custom_on_boundary(self):
        # fiscal_month_start=15: April 15 → labeled as April
        today = datetime.date(2026, 4, 15)
        year, month = get_current_fiscal_month(today, 15)
        self.assertEqual((year, month), (2026, 4))

    def test_get_current_fiscal_month_january_before_boundary(self):
        # fiscal_month_start=15: Jan 10 → labeled as December of prior year
        today = datetime.date(2026, 1, 10)
        year, month = get_current_fiscal_month(today, 15)
        self.assertEqual((year, month), (2025, 12))

    def test_csv_import_end_of_month_date_parsed_correctly(self):
        mapping = {'date': 'date', 'description': 'description', 'amount': 'amount'}
        bucket_map = {}
        preview, importable = _parse_csv_rows(
            [{'date': '2026-01-31', 'description': 'Jan end', 'amount': '-10.00'}],
            mapping, bucket_map,
        )
        self.assertEqual(preview[0]['status'], 'ok')
        self.assertEqual(preview[0]['date'], '2026-01-31')

    def test_csv_import_feb_28_date_parsed_correctly(self):
        mapping = {'date': 'date', 'description': 'description', 'amount': 'amount'}
        bucket_map = {}
        preview, importable = _parse_csv_rows(
            [{'date': '2026-02-28', 'description': 'Feb end', 'amount': '-20.00'}],
            mapping, bucket_map,
        )
        self.assertEqual(preview[0]['status'], 'ok')
        self.assertEqual(preview[0]['date'], '2026-02-28')
