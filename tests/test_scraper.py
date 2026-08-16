import json
import pytest
import httpx
from unittest.mock import patch, MagicMock

from scraper import extract_handle, fetch_product, parse_product

FAKE_PRODUCT_GROUP = {
    "@context": "https://schema.org/",
    "@type": "ProductGroup",
    "name": "Test FPV Motor",
    "url": "https://www.mepsking.shop/test-motor.html",
    "productGroupID": "9999999999999999999",
    "hasVariant": [
        {
            "@type": "Product",
            "sku": "1111111111111111111",
            "productId": "TEST-1900",
            "name": "Test FPV Motor-1900KV / Blue",
            "image": ["https://img-meps.mepsking.top/material/1/test-motor.jpg"],
            "offers": {
                "@type": "Offer",
                "url": "https://www.mepsking.shop/test-motor.html?spec=1900KV",
                "priceSpecification": [
                    {"@type": "UnitPriceSpecification", "price": 16.90, "priceCurrency": "USD"},
                    {"@type": "UnitPriceSpecification", "priceType": "https://schema.org/StrikethroughPrice", "price": 26.90, "priceCurrency": "USD"},
                ],
            },
        },
        {
            "@type": "Product",
            "sku": "2222222222222222222",
            "productId": "TEST-2500",
            "name": "Test FPV Motor-2500KV / Red",
            "image": ["https://img-meps.mepsking.top/material/1/test-motor.jpg"],
            "offers": {
                "@type": "Offer",
                "url": "https://www.mepsking.shop/test-motor.html?spec=2500KV",
                "priceSpecification": [
                    {"@type": "UnitPriceSpecification", "price": 18.90, "priceCurrency": "USD"},
                    {"@type": "UnitPriceSpecification", "priceType": "https://schema.org/StrikethroughPrice", "price": 28.90, "priceCurrency": "USD"},
                ],
            },
        },
    ],
}


def _make_html(product_group: dict) -> str:
    return f'<script type="application/ld+json">{json.dumps([product_group])}</script>'


class TestExtractHandle:
    def test_full_url_with_www(self):
        assert extract_handle("https://www.mepsking.shop/sz2408-fpv-freestyle-motor.html") == "sz2408-fpv-freestyle-motor"

    def test_full_url_without_www(self):
        assert extract_handle("https://mepsking.shop/sz2408-fpv-freestyle-motor.html") == "sz2408-fpv-freestyle-motor"

    def test_url_with_query_params(self):
        assert extract_handle("https://www.mepsking.shop/test-motor.html?spec=1900KV") == "test-motor"

    def test_url_with_fragment(self):
        assert extract_handle("https://www.mepsking.shop/test-motor.html#reviews") == "test-motor"

    def test_url_with_hyphenated_handle(self):
        handle = extract_handle("https://www.mepsking.shop/meps-neoncore-f405-60a-4-in-1-fpv-stack.html")
        assert handle == "meps-neoncore-f405-60a-4-in-1-fpv-stack"

    def test_non_html_url_returns_none(self):
        assert extract_handle("https://www.mepsking.shop/drone-parts/motors") is None

    def test_empty_string_returns_none(self):
        assert extract_handle("") is None

    def test_unrelated_url_returns_none(self):
        assert extract_handle("https://example.com/page") is None


class TestParseProduct:
    def test_full_product(self):
        result = parse_product(FAKE_PRODUCT_GROUP)

        assert result["handle"] == "test-motor"
        assert result["title"] == "Test FPV Motor"
        assert result["image_url"] == "https://img-meps.mepsking.top/material/1/test-motor.jpg"
        assert result["product_url"] == "https://www.mepsking.shop/test-motor.html"
        assert len(result["variants"]) == 2

    def test_variant_fields(self):
        result = parse_product(FAKE_PRODUCT_GROUP)
        v = result["variants"][0]

        assert v["external_variant_id"] == "1111111111111111111"
        assert v["name"] == "1900KV / Blue"
        assert v["sku"] == "TEST-1900"
        assert v["price"] == 16.90
        assert v["compare_at_price"] == 26.90

    def test_variant_name_strips_product_prefix(self):
        result = parse_product(FAKE_PRODUCT_GROUP)
        assert result["variants"][0]["name"] == "1900KV / Blue"
        assert result["variants"][1]["name"] == "2500KV / Red"

    def test_no_variants(self):
        raw = {**FAKE_PRODUCT_GROUP, "hasVariant": []}
        result = parse_product(raw)
        assert result["variants"] == []
        assert result["image_url"] is None

    def test_variant_without_compare_at_price(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Test",
            "url": "https://www.mepsking.shop/test.html",
            "hasVariant": [
                {
                    "sku": "111",
                    "productId": "T-001",
                    "name": "Test-Default",
                    "image": [],
                    "offers": {
                        "priceSpecification": [
                            {"@type": "UnitPriceSpecification", "price": 19.99, "priceCurrency": "USD"},
                        ]
                    },
                }
            ],
        }
        v = parse_product(raw)["variants"][0]
        assert v["price"] == 19.99
        assert v["compare_at_price"] is None

    def test_variant_name_falls_back_to_default_when_empty(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Test Motor",
            "url": "https://www.mepsking.shop/test-motor.html",
            "hasVariant": [
                {
                    "sku": "111",
                    "productId": "",
                    "name": "Test Motor",
                    "image": [],
                    "offers": {"priceSpecification": [{"price": 10.0, "priceCurrency": "USD"}]},
                }
            ],
        }
        v = parse_product(raw)["variants"][0]
        assert v["name"] == "Default"

    def test_multiple_variants_prices(self):
        result = parse_product(FAKE_PRODUCT_GROUP)
        assert result["variants"][0]["price"] == 16.90
        assert result["variants"][1]["price"] == 18.90
        assert result["variants"][1]["compare_at_price"] == 28.90


class TestFetchProduct:
    def _mock_response(self, status_code: int, html: str):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        resp.text = html
        return resp

    def test_success_returns_product_group(self):
        html = _make_html(FAKE_PRODUCT_GROUP)
        mock_resp = self._mock_response(200, html)

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = fetch_product("test-motor")

        assert result is not None
        assert result["@type"] == "ProductGroup"
        assert result["name"] == "Test FPV Motor"

    def test_404_returns_none(self):
        mock_resp = self._mock_response(404, "")

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = fetch_product("nonexistent")

        assert result is None

    def test_network_error_returns_none(self):
        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("timeout")
            result = fetch_product("test-motor")

        assert result is None

    def test_html_without_jsonld_returns_none(self):
        mock_resp = self._mock_response(200, "<html><body>No JSON-LD here</body></html>")

        with patch("httpx.Client") as mock_client_cls:
            mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = fetch_product("test-motor")

        assert result is None

    def test_requests_correct_url(self):
        html = _make_html(FAKE_PRODUCT_GROUP)
        mock_resp = self._mock_response(200, html)

        with patch("httpx.Client") as mock_client_cls:
            mock_get = mock_client_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_resp
            fetch_product("test-motor")

        called_url = mock_get.call_args[0][0]
        assert called_url == "https://www.mepsking.shop/test-motor.html"
