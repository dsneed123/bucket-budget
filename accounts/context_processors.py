from .models import UserPreferences


def user_theme(request):
    if not request.user.is_authenticated:
        return {'user_theme': 'dark'}
    prefs, _ = UserPreferences.objects.get_or_create(user=request.user)
    return {'user_theme': prefs.theme}
