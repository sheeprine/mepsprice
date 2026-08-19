import json
import httpx
from unittest.mock import MagicMock, patch

from plugins.dfr import DFRPlugin

plugin = DFRPlugin()

FAKE_RAW = {
    "title": "Test FPV Stack",
    "sku": "TEST-001",
    "image": "https://www.drone-fpv-racer.com/12345-home_default/test-fpv-stack.jpg",
    "price": 89.90,
    "compare_at_price": 99.90,
    "in_stock": True,
    "handle": "test-fpv-stack-12345",
    "url": "https://www.drone-fpv-racer.com/en/test-fpv-stack-12345.html",
    "product_id": "12345",
}

FAKE_JSONLD = {
    "@context": "https://schema.org/",
    "@type": "Product",
    "name": "Test FPV Stack",
    "sku": "TEST-001",
    "image": "https://www.drone-fpv-racer.com/12345-home_default/test-fpv-stack.jpg",
    "offers": {
        "@type": "Offer",
        "priceCurrency": "EUR",
        "price": "89.90",
        "availability": "http://schema.org/InStock",
    },
}


def _make_html(jsonld: dict, regular_price: str = None) -> str:
    parts = [f'<script type="application/ld+json">{json.dumps(jsonld)}</script>']
    if regular_price:
        parts.append(f'<span class="regular-price">€{regular_price}</span>')
    return "\n".join(parts)


class TestDFRCanHandle:
    def test_dfr_url_is_handled(self):
        assert plugin.can_handle("https://www.drone-fpv-racer.com/en/test-product-123.html") is True

    def test_mepsking_url_is_not_handled(self):
        assert plugin.can_handle("https://www.mepsking.shop/motor.html") is False

    def test_unrelated_url_is_not_handled(self):
        assert plugin.can_handle("https://www.example.com/shop") is False


class TestDFRExtractHandle:
    def test_english_url(self):
        url = "https://www.drone-fpv-racer.com/en/goku-f722-pro-v2-55a-bl32-30x30-stack-by-flywoo-13511.html"
        assert plugin.extract_handle(url) == "goku-f722-pro-v2-55a-bl32-30x30-stack-by-flywoo-13511"

    def test_french_url(self):
        url = "https://www.drone-fpv-racer.com/stack-goku-f722-pro-v2-55a-bl32-30x30-flywoo-13511.html"
        assert plugin.extract_handle(url) == "stack-goku-f722-pro-v2-55a-bl32-30x30-flywoo-13511"

    def test_url_with_query_params(self):
        url = "https://www.drone-fpv-racer.com/en/test-product-123.html?ref=search"
        assert plugin.extract_handle(url) == "test-product-123"

    def test_url_with_fragment(self):
        url = "https://www.drone-fpv-racer.com/en/test-product-123.html#reviews"
        assert plugin.extract_handle(url) == "test-product-123"

    def test_url_without_html_returns_none(self):
        assert plugin.extract_handle("https://www.drone-fpv-racer.com/en/474-stack-fcesc") is None

    def test_empty_string_returns_none(self):
        assert plugin.extract_handle("") is None


class TestDFRParseProduct:
    def test_basic_fields(self):
        result = plugin.parse_product(FAKE_RAW)
        assert result["handle"] == "test-fpv-stack-12345"
        assert result["title"] == "Test FPV Stack"
        assert result["image_url"] == "https://www.drone-fpv-racer.com/12345-home_default/test-fpv-stack.jpg"
        assert result["product_url"] == "https://www.drone-fpv-racer.com/en/test-fpv-stack-12345.html"
        assert len(result["variants"]) == 1

    def test_variant_fields(self):
        v = plugin.parse_product(FAKE_RAW)["variants"][0]
        assert v["external_variant_id"] == "12345"
        assert v["name"] == "Default"
        assert v["sku"] == "TEST-001"
        assert v["price"] == 89.90
        assert v["compare_at_price"] == 99.90
        assert v["in_stock"] is True

    def test_out_of_stock_variant(self):
        raw = {**FAKE_RAW, "in_stock": False}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is False

    def test_no_compare_at_price(self):
        raw = {**FAKE_RAW, "compare_at_price": None}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["compare_at_price"] is None

    def test_empty_image_becomes_none(self):
        raw = {**FAKE_RAW, "image": ""}
        result = plugin.parse_product(raw)
        assert result["image_url"] is None


class TestDFRParseHtml:
    def test_parses_title_sku_price(self):
        html = _make_html(FAKE_JSONLD)
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://www.drone-fpv-racer.com/en/test-fpv-stack-12345.html")
        assert result["title"] == "Test FPV Stack"
        assert result["sku"] == "TEST-001"
        assert result["price"] == 89.90

    def test_in_stock_from_jsonld(self):
        html = _make_html(FAKE_JSONLD)
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://x.com")
        assert result["in_stock"] is True

    def test_out_of_stock_from_jsonld(self):
        ld = {**FAKE_JSONLD, "offers": {**FAKE_JSONLD["offers"], "availability": "http://schema.org/OutOfStock"}}
        html = _make_html(ld)
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://x.com")
        assert result["in_stock"] is False

    def test_compare_at_price_from_regular_price_span(self):
        html = _make_html(FAKE_JSONLD, regular_price="99.90")
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://x.com")
        assert result["compare_at_price"] == 99.90

    def test_no_regular_price_span_means_no_compare_at(self):
        html = _make_html(FAKE_JSONLD)
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://x.com")
        assert result["compare_at_price"] is None

    def test_product_id_extracted_from_handle(self):
        html = _make_html(FAKE_JSONLD)
        result = plugin._parse_html(html, "test-fpv-stack-12345", "https://x.com")
        assert result["product_id"] == "12345"

    def test_handle_without_trailing_id_uses_full_handle(self):
        html = _make_html(FAKE_JSONLD)
        result = plugin._parse_html(html, "test-fpv-stack", "https://x.com")
        assert result["product_id"] == "test-fpv-stack"

    def test_missing_jsonld_returns_none(self):
        result = plugin._parse_html("<html><body>No JSON-LD</body></html>", "handle", "https://x.com")
        assert result is None

    def test_non_product_jsonld_returns_none(self):
        ld = {**FAKE_JSONLD, "@type": "Organization"}
        html = _make_html(ld)
        result = plugin._parse_html(html, "handle", "https://x.com")
        assert result is None


class TestDFRFetchProduct:
    def _mock_ok_response(self, html: str, url: str = "https://www.drone-fpv-racer.com/en/test-12345.html"):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.text = html
        resp.url = url
        return resp

    def _mock_error_response(self, status_code: int):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        return resp

    def test_successful_200_returns_parsed_dict(self):
        html = _make_html(FAKE_JSONLD)
        mock_resp = self._mock_ok_response(html)
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = plugin.fetch_product("test-fpv-stack-12345")
        assert result is not None
        assert result["title"] == "Test FPV Stack"

    def test_non_200_tries_second_url_then_returns_none(self):
        mock_resp = self._mock_error_response(404)
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = plugin.fetch_product("nonexistent-99999")
        assert result is None

    def test_network_exception_returns_none(self):
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("timeout")
            result = plugin.fetch_product("test-fpv-stack-12345")
        assert result is None

    def test_html_without_jsonld_tries_second_url(self):
        mock_resp = self._mock_ok_response("<html><body>No JSON-LD</body></html>")
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = plugin.fetch_product("test-fpv-stack-12345")
        assert result is None

    def test_requests_english_url_first(self):
        html = _make_html(FAKE_JSONLD)
        mock_resp = self._mock_ok_response(html)
        with patch("httpx.Client") as mock_cls:
            mock_get = mock_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_resp
            plugin.fetch_product("test-fpv-stack-12345")
        first_url = mock_get.call_args_list[0][0][0]
        assert first_url == "https://www.drone-fpv-racer.com/en/test-fpv-stack-12345.html"

    def test_falls_back_to_bare_url_when_english_404s(self):
        html = _make_html(FAKE_JSONLD)
        error_resp = self._mock_error_response(404)
        ok_resp = self._mock_ok_response(html, url="https://www.drone-fpv-racer.com/test-fr-handle-12345.html")
        with patch("httpx.Client") as mock_cls:
            mock_get = mock_cls.return_value.__enter__.return_value.get
            mock_get.side_effect = [error_resp, ok_resp]
            result = plugin.fetch_product("test-fr-handle-12345")
        assert result is not None
        second_url = mock_get.call_args_list[1][0][0]
        assert second_url == "https://www.drone-fpv-racer.com/test-fr-handle-12345.html"
