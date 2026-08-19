from plugins import SitePlugin


class _StubPlugin(SitePlugin):
    """Minimal concrete plugin that inherits base extract_pack_count without overriding it."""
    name = "stub"
    display_name = "Stub"
    currency = "$"
    tracks_stock = False

    def can_handle(self, url): return False
    def extract_handle(self, url): return None
    def fetch_product(self, handle): return None
    def parse_product(self, raw): return {}


_stub = _StubPlugin()


class TestBaseExtractPackCount:
    def test_multi_pcs_returns_count(self):
        assert _stub.extract_pack_count("4pcs Motor") == 4

    def test_multi_pack_returns_count(self):
        assert _stub.extract_pack_count("3 pack Kit") == 3

    def test_case_insensitive(self):
        assert _stub.extract_pack_count("6PCS Propellers") == 6

    def test_1pcs_returns_1(self):
        assert _stub.extract_pack_count("1pcs Item") == 1

    def test_no_match_returns_1(self):
        assert _stub.extract_pack_count("Blue Motor 1900KV") == 1
