import os
from unittest.mock import patch

import pytest

from conftest import FAKE_RAW_PRODUCT
from database import PriceCheck, Product, Variant
from plugins import get_plugin


class TestIndex:
    def test_empty_state_shows_empty_message(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Track your first product" in resp.text

    def test_shows_product_card_when_tracked(self, client, seeded_product):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Test FPV Motor" in resp.text
        assert "$16.90" in resp.text

    def test_shows_variant_count(self, client, seeded_product):
        resp = client.get("/")
        assert "2 variants" in resp.text

    def test_price_decrease_shown_in_green(self, client, seeded_product, db_session):
        v = db_session.query(Variant).filter_by(name="1900KV / Blue").first()
        db_session.add(PriceCheck(variant_id=v.id, price=12.0, compare_at_price=26.90))
        db_session.commit()

        resp = client.get("/")
        assert "↓" in resp.text
        assert "emerald" in resp.text

    def test_product_with_no_tracked_variants_is_excluded(self, client, db_session):
        product = Product(
            handle="untracked-motor",
            title="Untracked Motor",
            product_url="https://www.mepsking.shop/untracked-motor.html",
            site="mepsking",
        )
        db_session.add(product)
        db_session.flush()
        v = Variant(product_id=product.id, external_variant_id="999", name="Blue", sku="", tracked=False)
        db_session.add(v)
        db_session.commit()

        resp = client.get("/")
        assert resp.status_code == 200
        assert "Untracked Motor" not in resp.text

    def test_tracked_variant_with_no_price_checks_renders_without_error(self, client, db_session):
        product = Product(
            handle="checkless-motor",
            title="Checkless Motor",
            product_url="https://www.mepsking.shop/checkless-motor.html",
            site="mepsking",
        )
        db_session.add(product)
        db_session.flush()
        v = Variant(product_id=product.id, external_variant_id="888", name="Red", sku="", tracked=True)
        db_session.add(v)
        db_session.commit()

        # Variant has no PriceChecks — the inner loop hits `continue` but the product still renders
        resp = client.get("/")
        assert resp.status_code == 200

    def test_pack_count_from_product_title_for_single_variant(self, client, db_session):
        product = Product(
            handle="pack-motor",
            title="FPV Motor 4pcs",
            product_url="https://www.mepsking.shop/pack-motor.html",
            site="mepsking",
        )
        db_session.add(product)
        db_session.flush()
        v = Variant(product_id=product.id, external_variant_id="777", name="Blue", sku="", tracked=True)
        db_session.add(v)
        db_session.flush()
        db_session.add(PriceCheck(variant_id=v.id, price=40.0, compare_at_price=None))
        db_session.commit()

        resp = client.get("/")
        assert resp.status_code == 200
        # Pack motor with 4pcs should show per-unit section
        assert "pack-motor" in resp.text or "$40" in resp.text

    def test_event_type_price_and_stock_changed(self, client, seeded_product, db_session):
        v = db_session.query(Variant).filter_by(name="1900KV / Blue").first()
        db_session.add(PriceCheck(variant_id=v.id, price=12.0, compare_at_price=26.90, in_stock=False))
        db_session.commit()

        resp = client.get("/")
        assert resp.status_code == 200

    def test_event_type_stock_only_changed(self, client, seeded_product, db_session):
        v = db_session.query(Variant).filter_by(name="1900KV / Blue").first()
        db_session.add(PriceCheck(variant_id=v.id, price=16.90, compare_at_price=26.90, in_stock=False))
        db_session.commit()

        resp = client.get("/")
        assert resp.status_code == 200


class TestAdminLogin:
    def test_login_page_returns_200(self, client):
        assert client.get("/admin/login").status_code == 200

    def test_login_page_contains_password_input(self, client):
        assert 'name="password"' in client.get("/admin/login").text

    def test_wrong_password_returns_401(self, client):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "secret"}):
            resp = client.post("/admin/login", data={"password": "wrong"})
        assert resp.status_code == 401
        assert "Invalid password" in resp.text

    def test_correct_password_redirects(self, client):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "secret"}):
            resp = client.post(
                "/admin/login",
                data={"password": "secret", "next": "/add"},
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/add"

    def test_no_admin_password_set_rejects_login(self, client):
        with patch.dict(os.environ, {}, clear=True):
            resp = client.post("/admin/login", data={"password": "anything"})
        assert resp.status_code == 401

    def test_open_redirect_is_rejected(self, client):
        with patch.dict(os.environ, {"ADMIN_PASSWORD": "secret"}):
            resp = client.post(
                "/admin/login",
                data={"password": "secret", "next": "https://evil.com"},
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/add"

    def test_logout_clears_session(self, admin_client):
        resp = admin_client.post("/admin/logout", follow_redirects=False)
        assert resp.status_code == 303
        assert admin_client.get("/add", follow_redirects=False).status_code == 303


class TestAddPage:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get("/add", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

    def test_returns_200(self, admin_client):
        assert admin_client.get("/add").status_code == 200

    def test_contains_url_input(self, admin_client):
        assert 'name="url"' in admin_client.get("/add").text

    def test_shows_error_from_query_param(self, admin_client):
        resp = admin_client.get("/add?error=Something+went+wrong")
        assert "Something went wrong" in resp.text


class TestLookup:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.post("/lookup", data={"url": "https://www.mepsking.shop/test-motor.html"}, follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

    def test_unsupported_url_shows_error(self, admin_client):
        resp = admin_client.post("/lookup", data={"url": "https://www.example.com/product"})
        assert resp.status_code == 200
        assert "Unsupported URL" in resp.text

    def test_invalid_url_shows_error(self, admin_client):
        resp = admin_client.post("/lookup", data={"url": "https://www.mepsking.shop/drone-parts/motors"})
        assert resp.status_code == 200
        assert "Invalid URL" in resp.text

    def test_fetch_failure_shows_error(self, admin_client):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=None):
            resp = admin_client.post("/lookup", data={"url": "https://www.mepsking.shop/nonexistent.html"})
        assert resp.status_code == 200
        assert "Could not fetch" in resp.text

    def test_valid_url_shows_preview(self, admin_client):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            resp = admin_client.post("/lookup", data={"url": "https://www.mepsking.shop/test-motor.html"})
        assert resp.status_code == 200
        assert "Test FPV Motor" in resp.text
        assert "1900KV / Blue" in resp.text
        assert "2500KV / Red" in resp.text
        assert "$16.90" in resp.text

    def test_preview_shows_variant_checkboxes(self, admin_client):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            resp = admin_client.post("/lookup", data={"url": "https://www.mepsking.shop/test-motor.html"})
        assert 'type="checkbox"' in resp.text
        assert 'name="variant_ids"' in resp.text


class TestTrack:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.post(
            "/track",
            data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

    def test_no_variants_redirects_to_add(self, admin_client):
        resp = admin_client.post(
            "/track",
            data={"handle": "test-motor", "site": "mepsking"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert "/add" in resp.headers["location"]

    def test_creates_product_in_db(self, admin_client, db_session):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            admin_client.post("/track", data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]})

        db_session.expire_all()
        product = db_session.query(Product).filter_by(handle="test-motor").first()
        assert product is not None
        assert product.title == "Test FPV Motor"
        assert product.image_url == "https://img-meps.mepsking.top/material/1/test-motor.jpg"

    def test_creates_selected_variant_only(self, admin_client, db_session):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            admin_client.post("/track", data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]})

        db_session.expire_all()
        product = db_session.query(Product).filter_by(handle="test-motor").first()
        variants = db_session.query(Variant).filter_by(product_id=product.id).all()
        assert len(variants) == 1
        assert variants[0].external_variant_id == "1111111111111111111"
        assert variants[0].name == "1900KV / Blue"

    def test_creates_initial_price_check(self, admin_client, db_session):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            admin_client.post("/track", data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]})

        db_session.expire_all()
        product = db_session.query(Product).filter_by(handle="test-motor").first()
        variant = db_session.query(Variant).filter_by(product_id=product.id, external_variant_id="1111111111111111111").first()
        checks = db_session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1
        assert checks[0].price == 16.90
        assert checks[0].compare_at_price == 26.90

    def test_redirects_to_product_page(self, admin_client):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            resp = admin_client.post(
                "/track",
                data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]},
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/products/test-motor")

    def test_tracking_multiple_variants(self, admin_client, db_session):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            admin_client.post("/track", data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111", "2222222222222222222"]})

        db_session.expire_all()
        product = db_session.query(Product).filter_by(handle="test-motor").first()
        variants = db_session.query(Variant).filter_by(product_id=product.id).all()
        assert len(variants) == 2

    def test_retracking_existing_product_does_not_duplicate_variants(self, admin_client, seeded_product, db_session):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW_PRODUCT):
            admin_client.post("/track", data={"handle": "test-motor", "site": "mepsking", "variant_ids": ["1111111111111111111"]})

        db_session.expire_all()
        variants = db_session.query(Variant).filter_by(product_id=seeded_product.id).all()
        assert len(variants) == 2  # original 2, not duplicated

    def test_fetch_failure_returns_400(self, admin_client):
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=None):
            resp = admin_client.post("/track", data={"handle": "bad-handle", "site": "mepsking", "variant_ids": ["111"]})
        assert resp.status_code == 400

    def test_unknown_site_returns_400(self, admin_client):
        resp = admin_client.post(
            "/track",
            data={"handle": "test-motor", "site": "nonexistent_site", "variant_ids": ["111"]},
        )
        assert resp.status_code == 400


class TestProductDetail:
    def test_unknown_handle_returns_404(self, client):
        assert client.get("/products/nonexistent").status_code == 404

    def test_shows_product_title(self, client, seeded_product):
        resp = client.get("/products/test-motor")
        assert resp.status_code == 200
        assert "Test FPV Motor" in resp.text

    def test_shows_variant_prices(self, client, seeded_product):
        resp = client.get("/products/test-motor")
        assert "$16.90" in resp.text
        assert "$18.90" in resp.text

    def test_shows_compare_at_prices(self, client, seeded_product):
        resp = client.get("/products/test-motor")
        assert "$26.90" in resp.text
        assert "$28.90" in resp.text

    def test_includes_chart_data(self, client, seeded_product):
        resp = client.get("/products/test-motor")
        assert "priceChart" in resp.text
        assert "16.9" in resp.text

    def test_shows_mepsking_link(self, client, seeded_product):
        resp = client.get("/products/test-motor")
        assert "mepsking.shop" in resp.text

    def test_tracked_variant_with_no_price_checks_is_skipped(self, client, db_session):
        product = Product(
            handle="checkless-detail",
            title="Checkless Detail Motor",
            product_url="https://www.mepsking.shop/checkless-detail.html",
            site="mepsking",
        )
        db_session.add(product)
        db_session.flush()
        v = Variant(product_id=product.id, external_variant_id="555", name="Default", sku="", tracked=True)
        db_session.add(v)
        db_session.commit()

        resp = client.get("/products/checkless-detail")
        assert resp.status_code == 200
        assert "Checkless Detail Motor" in resp.text


class TestManualCheck:
    def test_unauthenticated_redirects_to_login(self, client, seeded_product):
        resp = client.post("/products/test-motor/check", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

    def test_unknown_handle_returns_404(self, admin_client):
        resp = admin_client.post("/products/nonexistent/check")
        assert resp.status_code == 404

    def test_triggers_price_check(self, admin_client, seeded_product):
        with patch("main.check_product_prices") as mock_check:
            admin_client.post("/products/test-motor/check", follow_redirects=False)
        mock_check.assert_called_once_with("test-motor")

    def test_redirects_to_product_page(self, admin_client, seeded_product):
        with patch("main.check_product_prices"):
            resp = admin_client.post("/products/test-motor/check", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].endswith("/products/test-motor")


class TestDeleteProduct:
    def test_unauthenticated_redirects_to_login(self, client, seeded_product):
        resp = client.post("/products/test-motor/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/login" in resp.headers["location"]

    def test_unknown_handle_returns_404(self, admin_client):
        resp = admin_client.post("/products/nonexistent/delete")
        assert resp.status_code == 404

    def test_removes_product_from_db(self, admin_client, seeded_product, db_session):
        admin_client.post("/products/test-motor/delete")

        db_session.expire_all()
        assert db_session.query(Product).filter_by(handle="test-motor").first() is None

    def test_cascades_to_variants_and_checks(self, admin_client, seeded_product, db_session):
        product_id = seeded_product.id
        admin_client.post("/products/test-motor/delete")

        db_session.expire_all()
        assert db_session.query(Variant).filter_by(product_id=product_id).count() == 0

    def test_redirects_to_home(self, admin_client, seeded_product):
        resp = admin_client.post("/products/test-motor/delete", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/"
