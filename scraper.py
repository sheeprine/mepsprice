# Backward-compatibility wrapper — delegates to the mepsking plugin.
# Kept so existing tests that import from scraper continue to work.

def _plugin():
    from plugins import get_plugin
    return get_plugin("mepsking")


def extract_handle(url):
    return _plugin().extract_handle(url)


def fetch_product(handle):
    return _plugin().fetch_product(handle)


def parse_product(raw):
    return _plugin().parse_product(raw)
