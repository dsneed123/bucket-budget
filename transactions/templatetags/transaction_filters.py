import re

from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def highlight_search(value, search_term):
    """
    Wrap occurrences of search_term in <mark> tags for highlighting.
    HTML-escapes the value first to prevent XSS.
    """
    if not value or not search_term:
        return value
    escaped = escape(value)
    escaped_term = re.escape(escape(search_term))
    highlighted = re.sub(
        f'({escaped_term})',
        r'<mark class="search-highlight">\1</mark>',
        escaped,
        flags=re.IGNORECASE,
    )
    return mark_safe(highlighted)


@register.filter
def render_notes(value):
    """
    Render notes with basic markdown-like formatting:
    - **text** becomes <strong>text</strong>
    - Line breaks are preserved (single \n -> <br>, double \n\n -> paragraph break)

    HTML is escaped before processing to prevent XSS.
    """
    if not value:
        return ''
    escaped = escape(value)
    # Replace **bold** with <strong>bold</strong>
    bolded = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    # Split into paragraphs on double newlines, convert single newlines to <br>
    paragraphs = re.split(r'\n\n+', bolded)
    result = ''.join(
        '<p>' + p.replace('\n', '<br>') + '</p>'
        for p in paragraphs
        if p.strip()
    )
    return mark_safe(result)
