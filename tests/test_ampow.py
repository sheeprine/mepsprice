import httpx
import pytest
from unittest.mock import MagicMock, patch

from plugins.ampow import AmpowPlugin

plugin = AmpowPlugin()

FAKE_RAW = {
    "handle": "test-battery",
    "title": "Test LiPo Battery",
    "images": [{"src": "https://cdn.ampow.com/test-battery.jpg"}],
    "variants": [
        {
            "id": 111,
            "title": "4S 1300mAh",
            "sku": "AP-4S-1300",
            "price": "19.99",
            "compare_at_price": "24.99",
            "inventory_management": "shopify",
            "inventory_policy": "deny",
            "inventory_quantity": 10,
        },
    ],
}


class TestAmpowTracksStock:
    def test_tracks_stock_is_false(self):
        assert plugin.tracks_stock is False


class TestAmpowParseProduct:
    def test_basic_fields(self):
        result = plugin.parse_product(FAKE_RAW)
        assert result["handle"] == "test-battery"
        assert result["title"] == "Test LiPo Battery"
        assert result["image_url"] == "https://cdn.ampow.com/test-battery.jpg"
        assert result["product_url"] == "https://www.ampow.com/products/test-battery"
        assert len(result["variants"]) == 1

    def test_variant_fields(self):
        v = plugin.parse_product(FAKE_RAW)["variants"][0]
        assert v["external_variant_id"] == "111"
        assert v["name"] == "4S 1300mAh"
        assert v["sku"] == "AP-4S-1300"
        assert v["price"] == 19.99
        assert v["compare_at_price"] == 24.99
        assert v["in_stock"] is True

    def test_in_stock_when_inventory_qty_positive(self):
        raw = {**FAKE_RAW, "variants": [{**FAKE_RAW["variants"][0], "inventory_quantity": 5}]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is True

    def test_always_in_stock_regardless_of_inventory_qty(self):
        raw = {**FAKE_RAW, "variants": [{**FAKE_RAW["variants"][0], "inventory_quantity": 0}]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is True

    def test_no_compare_at_price(self):
        raw = {**FAKE_RAW, "variants": [{**FAKE_RAW["variants"][0], "compare_at_price": None}]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["compare_at_price"] is None

    def test_no_images(self):
        raw = {**FAKE_RAW, "images": []}
        result = plugin.parse_product(raw)
        assert result["image_url"] is None


class TestAmpowCanHandle:
    def test_ampow_url_is_handled(self):
        assert plugin.can_handle("https://www.ampow.com/products/test-battery") is True

    def test_mepsking_url_is_not_handled(self):
        assert plugin.can_handle("https://www.mepsking.shop/motor.html") is False

    def test_unrelated_url_is_not_handled(self):
        assert plugin.can_handle("https://www.example.com/shop") is False


class TestAmpowExtractHandle:
    def test_standard_products_url(self):
        assert plugin.extract_handle("https://www.ampow.com/products/test-battery") == "test-battery"

    def test_url_with_query_params(self):
        assert plugin.extract_handle("https://www.ampow.com/products/test-battery?variant=123") == "test-battery"

    def test_url_with_fragment(self):
        assert plugin.extract_handle("https://www.ampow.com/products/test-battery#specs") == "test-battery"

    def test_url_without_products_path_returns_none(self):
        assert plugin.extract_handle("https://www.ampow.com/collections/batteries") is None


class TestAmpowFetchProduct:
    def _mock_ok_response(self, data: dict):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.json.return_value = data
        return resp

    def _mock_error_response(self, status_code: int):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = status_code
        return resp

    def test_successful_200_returns_product_dict(self):
        mock_resp = self._mock_ok_response({"product": FAKE_RAW})
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = plugin.fetch_product("test-battery")
        assert result is not None
        assert result["handle"] == "test-battery"

    def test_non_200_returns_none(self):
        mock_resp = self._mock_error_response(404)
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.return_value = mock_resp
            result = plugin.fetch_product("nonexistent")
        assert result is None

    def test_network_exception_returns_none(self):
        with patch("httpx.Client") as mock_cls:
            mock_cls.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError("timeout")
            result = plugin.fetch_product("test-battery")
        assert result is None

    def test_requests_correct_url(self):
        mock_resp = self._mock_ok_response({"product": FAKE_RAW})
        with patch("httpx.Client") as mock_cls:
            mock_get = mock_cls.return_value.__enter__.return_value.get
            mock_get.return_value = mock_resp
            plugin.fetch_product("test-battery")
        called_url = mock_get.call_args[0][0]
        assert called_url == "https://www.ampow.com/products/test-battery.json"


class TestAmpowExtractPackCount:
    def test_first_number_in_name_is_returned(self):
        assert plugin.extract_pack_count("4S 1300mAh Battery") == 4

    def test_single_digit_name(self):
        assert plugin.extract_pack_count("2 Cell Pack") == 2

    def test_no_number_returns_1(self):
        assert plugin.extract_pack_count("LiPo Battery") == 1

    def test_zero_digit_returns_1(self):
        assert plugin.extract_pack_count("0S Pack") == 1
