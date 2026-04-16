from .models import BankAccount


def net_worth(request):
    if not request.user.is_authenticated:
        return {}

    total = (
        BankAccount.objects.filter(user=request.user, is_active=True)
        .values_list('balance', flat=True)
    )
    net_worth_value = sum(total, 0)
    return {'net_worth': net_worth_value}
