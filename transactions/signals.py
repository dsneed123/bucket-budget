from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from .models import Transaction


@receiver(pre_save, sender=Transaction)
def capture_old_transaction_state(sender, instance, **kwargs):
    """Capture the DB state before an update so post_save can compute the diff."""
    if instance.pk:
        try:
            old = Transaction.objects.get(pk=instance.pk)
            instance._pre_save_account_id = old.account_id
            instance._pre_save_amount = old.amount
            instance._pre_save_type = old.transaction_type
        except Transaction.DoesNotExist:
            instance._pre_save_account_id = None
            instance._pre_save_amount = None
            instance._pre_save_type = None
    else:
        instance._pre_save_account_id = None
        instance._pre_save_amount = None
        instance._pre_save_type = None


@receiver(post_save, sender=Transaction)
def update_balance_on_save(sender, instance, created, **kwargs):
    """Apply or adjust the bank account balance when a transaction is saved."""
    from banking.models import BankAccount

    if created:
        account = BankAccount.objects.get(pk=instance.account_id)
        if instance.transaction_type == 'expense':
            account.balance -= instance.amount
        else:  # income / transfer
            account.balance += instance.amount
        account.save(change_reason='transaction', reference_id=str(instance.pk))
    else:
        old_account_id = instance._pre_save_account_id
        old_amount = instance._pre_save_amount
        old_type = instance._pre_save_type

        if old_account_id is None:
            return

        if old_account_id == instance.account_id:
            # Same account — reverse old and apply new in a single write.
            account = BankAccount.objects.get(pk=instance.account_id)
            if old_type == 'expense':
                account.balance += old_amount
            else:
                account.balance -= old_amount
            if instance.transaction_type == 'expense':
                account.balance -= instance.amount
            else:
                account.balance += instance.amount
            account.save(change_reason='transaction', reference_id=str(instance.pk))
        else:
            # Different accounts — reverse on old account, apply on new account.
            old_account = BankAccount.objects.get(pk=old_account_id)
            if old_type == 'expense':
                old_account.balance += old_amount
            else:
                old_account.balance -= old_amount
            old_account.save(change_reason='transaction', reference_id=str(instance.pk))

            new_account = BankAccount.objects.get(pk=instance.account_id)
            if instance.transaction_type == 'expense':
                new_account.balance -= instance.amount
            else:
                new_account.balance += instance.amount
            new_account.save(change_reason='transaction', reference_id=str(instance.pk))


@receiver(post_delete, sender=Transaction)
def update_balance_on_delete(sender, instance, **kwargs):
    """Reverse the balance impact when a transaction is deleted."""
    from banking.models import BankAccount

    account = BankAccount.objects.get(pk=instance.account_id)
    if instance.transaction_type == 'expense':
        account.balance += instance.amount
    else:  # income / transfer
        account.balance -= instance.amount
    account.save(change_reason='transaction', reference_id=str(instance.pk))
