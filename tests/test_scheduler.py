from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database import Base, Product, Variant, PriceCheck
from scheduler import check_product_prices, check_all_prices

FAKE_RAW = {
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
                "priceSpecification": [
                    {"price": 14.90, "priceCurrency": "USD"},
                    {"priceType": "https://schema.org/StrikethroughPrice", "price": 26.90, "priceCurrency": "USD"},
                ],
            },
        },
    ],
}


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=e)
    yield e
    Base.metadata.drop_all(bind=e)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def product_with_variant(session):
    product = Product(
        handle="test-motor",
        title="Test FPV Motor",
        product_url="https://www.mepsking.shop/test-motor.html",
    )
    session.add(product)
    session.flush()

    variant = Variant(
        product_id=product.id,
        external_variant_id="1111111111111111111",
        name="1900KV / Blue",
        sku="TEST-1900",
        tracked=True,
    )
    session.add(variant)
    session.flush()

    session.add(PriceCheck(variant_id=variant.id, price=16.90, compare_at_price=26.90))
    session.commit()

    return product, variant


class TestCheckProductPrices:
    def test_creates_new_price_check(self, session, product_with_variant):
        product, variant = product_with_variant

        with patch("scheduler.fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).order_by(PriceCheck.id).all()
        assert len(checks) == 2
        assert checks[-1].price == 14.90
        assert checks[-1].compare_at_price == 26.90

    def test_updates_last_checked_at(self, session, product_with_variant):
        product, _ = product_with_variant
        assert product.last_checked_at is None

        with patch("scheduler.fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        product = session.query(Product).filter_by(handle="test-motor").first()
        assert product.last_checked_at is not None

    def test_unknown_handle_is_noop(self, session):
        with patch("scheduler.fetch_product", return_value=FAKE_RAW):
            check_product_prices("nonexistent", session=session)
        session.commit()

        assert session.query(PriceCheck).count() == 0

    def test_fetch_failure_is_noop(self, session, product_with_variant):
        _, variant = product_with_variant

        with patch("scheduler.fetch_product", return_value=None):
            check_product_prices("test-motor", session=session)

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_skips_untracked_variants(self, session, product_with_variant):
        product, variant = product_with_variant
        variant.tracked = False
        session.commit()

        with patch("scheduler.fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_ignores_unknown_variant_ids_from_api(self, session, product_with_variant):
        raw = {**FAKE_RAW, "hasVariant": [{
            "sku": "9999999999999999999",
            "productId": "UNKNOWN",
            "name": "Test FPV Motor-Unknown",
            "image": [],
            "offers": {"priceSpecification": [{"price": 50.00, "priceCurrency": "USD"}]},
        }]}

        with patch("scheduler.fetch_product", return_value=raw):
            check_product_prices("test-motor", session=session)
        session.commit()

        assert session.query(PriceCheck).count() == 1

    def test_skips_price_check_when_unchanged(self, session, product_with_variant):
        _, variant = product_with_variant
        # Seed the same price that FAKE_RAW returns (14.90)
        session.query(PriceCheck).filter_by(variant_id=variant.id).delete()
        session.add(PriceCheck(variant_id=variant.id, price=14.90, compare_at_price=26.90))
        session.commit()

        with patch("scheduler.fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_own_session_path(self, engine, product_with_variant):
        with patch("scheduler.engine", engine):
            with patch("scheduler.fetch_product", return_value=FAKE_RAW):
                check_product_prices("test-motor")

        _, variant = product_with_variant
        with Session(engine) as s:
            checks = s.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 2


class TestCheckAllPrices:
    def test_checks_all_products(self, engine, session):
        for handle in ("motor-a", "motor-b"):
            p = Product(handle=handle, title=handle.upper(), product_url=f"https://www.mepsking.shop/{handle}.html")
            session.add(p)
        session.commit()

        with patch("scheduler.engine", engine):
            with patch("scheduler.check_product_prices") as mock_check:
                check_all_prices()

        handles_checked = {call.args[0] for call in mock_check.call_args_list}
        assert handles_checked == {"motor-a", "motor-b"}

    def test_empty_db_does_not_error(self, engine):
        with patch("scheduler.engine", engine):
            check_all_prices()
