import hashlib

from django import template

register = template.Library()

AVATAR_COLORS = [
    '#00d4aa',  # teal (accent-green)
    '#0984e3',  # blue (accent-blue)
    '#f9ca24',  # gold (accent-gold)
    '#a29bfe',  # purple
    '#fd79a8',  # pink
    '#e17055',  # orange
    '#74b9ff',  # light blue
    '#55efc4',  # mint
]


@register.filter
def avatar_initials(user):
    """Return up to two initials: first letter of first_name + first letter of last_name."""
    first = (user.first_name or '').strip()
    last = (user.last_name or '').strip()
    if first and last:
        return (first[0] + last[0]).upper()
    if first:
        return first[0].upper()
    email = (user.email or '').strip()
    return email[0].upper() if email else '?'


@register.filter
def avatar_color(email):
    """Return a deterministic color from the palette based on the email hash."""
    digest = hashlib.md5((email or '').encode('utf-8')).hexdigest()
    index = int(digest, 16) % len(AVATAR_COLORS)
    return AVATAR_COLORS[index]
