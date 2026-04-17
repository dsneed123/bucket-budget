def make_breadcrumbs(*items):
    return [{'label': label, 'url': url} for label, url in items]
