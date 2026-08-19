import pytest
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
    def test_tracks_stock_is_true(self):
        assert plugin.tracks_stock is True


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

    def test_out_of_stock_when_deny_policy_and_zero_qty(self):
        raw = {**FAKE_RAW, "variants": [{**FAKE_RAW["variants"][0], "inventory_quantity": 0}]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is False

    def test_out_of_stock_when_deny_policy_and_negative_qty(self):
        raw = {**FAKE_RAW, "variants": [{**FAKE_RAW["variants"][0], "inventory_quantity": -3}]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is False

    def test_in_stock_when_continue_policy_regardless_of_qty(self):
        raw = {**FAKE_RAW, "variants": [{
            **FAKE_RAW["variants"][0],
            "inventory_policy": "continue",
            "inventory_quantity": 0,
        }]}
        v = plugin.parse_product(raw)["variants"][0]
        assert v["in_stock"] is True

    def test_in_stock_when_no_inventory_management(self):
        raw = {**FAKE_RAW, "variants": [{
            **FAKE_RAW["variants"][0],
            "inventory_management": None,
            "inventory_quantity": 0,
        }]}
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
