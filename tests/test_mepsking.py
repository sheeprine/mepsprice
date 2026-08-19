import json

from plugins.mepsking import MepskingPlugin

plugin = MepskingPlugin()


class TestMepskingCanHandle:
    def test_mepsking_url_is_handled(self):
        assert plugin.can_handle("https://www.mepsking.shop/test-motor.html") is True

    def test_ampow_url_is_not_handled(self):
        assert plugin.can_handle("https://www.ampow.com/products/battery") is False

    def test_unrelated_url_is_not_handled(self):
        assert plugin.can_handle("https://www.example.com/product") is False


class TestMepskingExtractHandle:
    def test_standard_product_url(self):
        assert plugin.extract_handle("https://www.mepsking.shop/test-motor.html") == "test-motor"

    def test_url_without_html_extension_returns_none(self):
        assert plugin.extract_handle("https://www.mepsking.shop/category/motors") is None


class TestExtractProductGroup:
    def test_invalid_json_block_is_skipped_and_returns_none(self):
        html = '<script type="application/ld+json">{ not valid json ! }</script>'
        result = plugin._extract_product_group(html)
        assert result is None

    def test_valid_product_group_is_returned(self):
        pg = {"@type": "ProductGroup", "name": "Motor", "hasVariant": []}
        html = f'<script type="application/ld+json">{json.dumps(pg)}</script>'
        result = plugin._extract_product_group(html)
        assert result == pg

    def test_list_json_ld_with_product_group_is_found(self):
        pg = {"@type": "ProductGroup", "name": "Motor", "hasVariant": []}
        other = {"@type": "BreadcrumbList", "itemListElement": []}
        html = f'<script type="application/ld+json">{json.dumps([other, pg])}</script>'
        result = plugin._extract_product_group(html)
        assert result == pg

    def test_json_ld_without_product_group_type_returns_none(self):
        data = {"@type": "BreadcrumbList"}
        html = f'<script type="application/ld+json">{json.dumps(data)}</script>'
        result = plugin._extract_product_group(html)
        assert result is None


class TestMepskingParseProductEdgeCases:
    def test_variant_name_not_starting_with_product_name_is_kept_as_is(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Product A",
            "url": "https://www.mepsking.shop/test.html",
            "hasVariant": [{
                "sku": "111",
                "productId": "T-001",
                "name": "Completely Different Name",
                "image": [],
                "offers": {"priceSpecification": [{"price": 10.0}]},
            }]
        }
        v = plugin.parse_product(raw)["variants"][0]
        assert v["name"] == "Completely Different Name"

    def test_fallback_price_from_offers_price_field(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Test",
            "url": "https://www.mepsking.shop/test.html",
            "hasVariant": [{
                "sku": "111",
                "productId": "T-001",
                "name": "Test-Variant",
                "image": [],
                "offers": {
                    "price": 25.0,
                    "priceSpecification": [],
                },
            }]
        }
        v = plugin.parse_product(raw)["variants"][0]
        assert v["price"] == 25.0

    def test_price_defaults_to_zero_when_completely_absent(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Test",
            "url": "https://www.mepsking.shop/test.html",
            "hasVariant": [{
                "sku": "111",
                "productId": "T-001",
                "name": "Test-Variant",
                "image": [],
                "offers": {},
            }]
        }
        v = plugin.parse_product(raw)["variants"][0]
        assert v["price"] == 0.0

    def test_handle_falls_back_to_product_group_id_when_no_url_match(self):
        raw = {
            "@type": "ProductGroup",
            "name": "Test",
            "url": "https://www.mepsking.shop/",
            "productGroupID": "fallback-id",
            "hasVariant": [],
        }
        result = plugin.parse_product(raw)
        assert result["handle"] == "fallback-id"


class TestMepskingExtractPackCount:
    def test_4pcs_returns_4(self):
        assert plugin.extract_pack_count("4pcs Motor Set") == 4

    def test_2pack_returns_2(self):
        assert plugin.extract_pack_count("2 pack Bundle") == 2

    def test_case_insensitive_pcs(self):
        assert plugin.extract_pack_count("4PCS Motor") == 4

    def test_1pcs_returns_1(self):
        assert plugin.extract_pack_count("1pcs Standalone") == 1

    def test_no_pcs_or_pack_keyword_returns_1(self):
        assert plugin.extract_pack_count("1900KV Blue Motor") == 1
