from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from .models import SavingsContribution, SavingsGoal

_MILESTONE_THRESHOLDS = (25, 50, 75, 100)


@receiver(post_save, sender=SavingsGoal)
def check_milestones(sender, instance, **kwargs):
    """Create milestone records when a goal crosses 25%, 50%, 75%, or 100% thresholds."""
    from .models import SavingsMilestone

    if instance.target_amount <= 0:
        return

    current_pct = int((instance.current_amount / instance.target_amount) * 100)

    for threshold in _MILESTONE_THRESHOLDS:
        if current_pct >= threshold:
            SavingsMilestone.objects.get_or_create(goal=instance, percentage=threshold)


@receiver(pre_save, sender=SavingsContribution)
def capture_old_contribution_state(sender, instance, **kwargs):
    """Capture the DB state before an update so post_save can compute the diff."""
    if instance.pk:
        try:
            old = SavingsContribution.objects.get(pk=instance.pk)
            instance._pre_save_goal_id = old.goal_id
            instance._pre_save_amount = old.amount
            instance._pre_save_account_id = old.source_account_id
            instance._pre_save_transaction_type = old.transaction_type
        except SavingsContribution.DoesNotExist:
            instance._pre_save_goal_id = None
            instance._pre_save_amount = None
            instance._pre_save_account_id = None
            instance._pre_save_transaction_type = None
    else:
        instance._pre_save_goal_id = None
        instance._pre_save_amount = None
        instance._pre_save_account_id = None
        instance._pre_save_transaction_type = None


def _apply_contribution(account, goal, amount, tx_type, change_reason, reference_id):
    """Apply a contribution or withdrawal to account balance and goal current_amount."""
    if tx_type == 'withdrawal':
        account.balance += amount
        account.save(change_reason=change_reason, reference_id=reference_id)
        goal.current_amount -= amount
    else:
        account.balance -= amount
        account.save(change_reason=change_reason, reference_id=reference_id)
        goal.current_amount += amount
    goal.save()


def _reverse_contribution(account, goal, amount, tx_type, change_reason, reference_id):
    """Reverse a previously applied contribution or withdrawal."""
    if tx_type == 'withdrawal':
        account.balance -= amount
        account.save(change_reason=change_reason, reference_id=reference_id)
        goal.current_amount += amount
    else:
        account.balance += amount
        account.save(change_reason=change_reason, reference_id=reference_id)
        goal.current_amount -= amount
    goal.save()


@receiver(post_save, sender=SavingsContribution)
def update_balances_on_save(sender, instance, created, **kwargs):
    """Update bank account balance and goal current_amount when a contribution is saved."""
    from banking.models import BankAccount
    from .models import SavingsGoal

    ref = str(instance.pk)

    if created:
        account = BankAccount.objects.get(pk=instance.source_account_id)
        goal = SavingsGoal.objects.get(pk=instance.goal_id)
        _apply_contribution(account, goal, instance.amount, instance.transaction_type,
                            'savings_contribution', ref)
    else:
        old_goal_id = instance._pre_save_goal_id
        old_amount = instance._pre_save_amount
        old_account_id = instance._pre_save_account_id
        old_tx_type = instance._pre_save_transaction_type

        if old_amount is None:
            return

        old_account = BankAccount.objects.get(pk=old_account_id)
        old_goal = SavingsGoal.objects.get(pk=old_goal_id)
        _reverse_contribution(old_account, old_goal, old_amount, old_tx_type,
                              'savings_contribution', ref)

        new_account = BankAccount.objects.get(pk=instance.source_account_id)
        new_goal = SavingsGoal.objects.get(pk=instance.goal_id)
        _apply_contribution(new_account, new_goal, instance.amount, instance.transaction_type,
                            'savings_contribution', ref)


@receiver(post_delete, sender=SavingsContribution)
def update_balances_on_delete(sender, instance, **kwargs):
    """Reverse the balance and goal impact when a contribution is deleted."""
    from banking.models import BankAccount
    from .models import SavingsGoal

    account = BankAccount.objects.get(pk=instance.source_account_id)
    goal = SavingsGoal.objects.get(pk=instance.goal_id)
    _reverse_contribution(account, goal, instance.amount, instance.transaction_type,
                          'savings_contribution', str(instance.pk))
