from django import template

register = template.Library()


@register.inclusion_tag('core/breadcrumbs.html')
def render_breadcrumbs(breadcrumbs):
    return {'breadcrumbs': breadcrumbs}


@register.filter
def startswith(value, prefix):
    return str(value).startswith(prefix)


@register.simple_tag(takes_context=True)
def active_link(context, prefix):
    request = context.get('request')
    if request and request.path.startswith(prefix):
        return 'active'
    return ''
