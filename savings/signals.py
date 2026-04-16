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
        except SavingsContribution.DoesNotExist:
            instance._pre_save_goal_id = None
            instance._pre_save_amount = None
            instance._pre_save_account_id = None
    else:
        instance._pre_save_goal_id = None
        instance._pre_save_amount = None
        instance._pre_save_account_id = None


@receiver(post_save, sender=SavingsContribution)
def update_balances_on_save(sender, instance, created, **kwargs):
    """Deduct from bank account and add to goal's current_amount when a contribution is saved."""
    from banking.models import BankAccount
    from .models import SavingsGoal

    if created:
        account = BankAccount.objects.get(pk=instance.source_account_id)
        account.balance -= instance.amount
        account.save(change_reason='savings_contribution', reference_id=str(instance.pk))

        goal = SavingsGoal.objects.get(pk=instance.goal_id)
        goal.current_amount += instance.amount
        goal.save()
    else:
        old_goal_id = instance._pre_save_goal_id
        old_amount = instance._pre_save_amount
        old_account_id = instance._pre_save_account_id

        if old_amount is None:
            return

        # Reverse old account deduction
        old_account = BankAccount.objects.get(pk=old_account_id)
        old_account.balance += old_amount
        old_account.save(change_reason='savings_contribution', reference_id=str(instance.pk))

        # Apply new account deduction
        new_account = BankAccount.objects.get(pk=instance.source_account_id)
        new_account.balance -= instance.amount
        new_account.save(change_reason='savings_contribution', reference_id=str(instance.pk))

        # Reverse old goal addition
        old_goal = SavingsGoal.objects.get(pk=old_goal_id)
        old_goal.current_amount -= old_amount
        old_goal.save()

        # Apply new goal addition
        new_goal = SavingsGoal.objects.get(pk=instance.goal_id)
        new_goal.current_amount += instance.amount
        new_goal.save()


@receiver(post_delete, sender=SavingsContribution)
def update_balances_on_delete(sender, instance, **kwargs):
    """Reverse the balance and goal impact when a contribution is deleted."""
    from banking.models import BankAccount
    from .models import SavingsGoal

    account = BankAccount.objects.get(pk=instance.source_account_id)
    account.balance += instance.amount
    account.save(change_reason='savings_contribution', reference_id=str(instance.pk))

    goal = SavingsGoal.objects.get(pk=instance.goal_id)
    goal.current_amount -= instance.amount
    goal.save()
