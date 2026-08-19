from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database import Base, Product, Variant, PriceCheck
from plugins import get_plugin
from scheduler import check_product_prices, check_all_prices, start_scheduler, stop_scheduler

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

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW):
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

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        product = session.query(Product).filter_by(handle="test-motor").first()
        assert product.last_checked_at is not None

    def test_unknown_handle_is_noop(self, session):
        check_product_prices("nonexistent", session=session)
        session.commit()

        assert session.query(PriceCheck).count() == 0

    def test_fetch_failure_is_noop(self, session, product_with_variant):
        _, variant = product_with_variant

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=None):
            check_product_prices("test-motor", session=session)

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_skips_untracked_variants(self, session, product_with_variant):
        product, variant = product_with_variant
        variant.tracked = False
        session.commit()

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_ignores_unknown_variant_ids_from_api(self, session, product_with_variant):
        _, variant = product_with_variant
        raw = {**FAKE_RAW, "hasVariant": [{
            "sku": "9999999999999999999",
            "productId": "UNKNOWN",
            "name": "Test FPV Motor-Unknown",
            "image": [],
            "offers": {"priceSpecification": [{"price": 50.00, "priceCurrency": "USD"}]},
        }]}

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=raw):
            check_product_prices("test-motor", session=session)
        session.commit()

        # The tracked variant disappeared from the page → marked out-of-stock (2 checks total)
        # The unknown variant from the page does NOT get a check
        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).order_by(PriceCheck.id).all()
        assert len(checks) == 2
        assert checks[-1].in_stock is False

    def test_marks_missing_variant_as_out_of_stock(self, session, product_with_variant):
        _, variant = product_with_variant
        # Seed the variant as explicitly in-stock
        session.query(PriceCheck).filter_by(variant_id=variant.id).delete()
        session.add(PriceCheck(variant_id=variant.id, price=14.90, compare_at_price=26.90, in_stock=True))
        session.commit()

        # Page no longer lists the tracked variant
        raw_empty = {**FAKE_RAW, "hasVariant": []}
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=raw_empty):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).order_by(PriceCheck.id).all()
        assert len(checks) == 2
        assert checks[-1].in_stock is False
        assert checks[-1].price == 14.90

    def test_does_not_duplicate_out_of_stock_for_already_missing_variant(self, session, product_with_variant):
        _, variant = product_with_variant
        # Variant already recorded as out-of-stock
        session.query(PriceCheck).filter_by(variant_id=variant.id).delete()
        session.add(PriceCheck(variant_id=variant.id, price=14.90, compare_at_price=26.90, in_stock=False))
        session.commit()

        raw_empty = {**FAKE_RAW, "hasVariant": []}
        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=raw_empty):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_skips_price_check_when_unchanged(self, session, product_with_variant):
        _, variant = product_with_variant
        # Seed the same price that FAKE_RAW returns (14.90)
        session.query(PriceCheck).filter_by(variant_id=variant.id).delete()
        session.add(PriceCheck(variant_id=variant.id, price=14.90, compare_at_price=26.90))
        session.commit()

        plugin = get_plugin("mepsking")
        with patch.object(plugin, "fetch_product", return_value=FAKE_RAW):
            check_product_prices("test-motor", session=session)
        session.commit()

        session.expire_all()
        checks = session.query(PriceCheck).filter_by(variant_id=variant.id).all()
        assert len(checks) == 1

    def test_own_session_path(self, engine, product_with_variant):
        plugin = get_plugin("mepsking")
        with patch("scheduler.engine", engine):
            with patch.object(plugin, "fetch_product", return_value=FAKE_RAW):
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


class TestCheckProductPricesUnknownPlugin:
    def test_unknown_site_is_noop(self, session, product_with_variant):
        product, variant = product_with_variant
        product.site = "nonexistent_plugin"
        session.commit()

        count_before = session.query(PriceCheck).filter_by(variant_id=variant.id).count()
        check_product_prices("test-motor", session=session)
        count_after = session.query(PriceCheck).filter_by(variant_id=variant.id).count()

        assert count_before == count_after


class TestStartStopScheduler:
    def test_start_scheduler_adds_job_and_starts(self):
        with patch("scheduler.scheduler") as mock_sched:
            start_scheduler(interval_hours=2)
        mock_sched.add_job.assert_called_once_with(
            check_all_prices,
            "interval",
            hours=2,
            id="price_check",
            replace_existing=True,
        )
        mock_sched.start.assert_called_once()

    def test_start_scheduler_defaults_to_1_hour(self):
        with patch("scheduler.scheduler") as mock_sched:
            start_scheduler()
        _, kwargs = mock_sched.add_job.call_args
        assert kwargs["hours"] == 1

    def test_stop_scheduler_shuts_down_when_running(self):
        with patch("scheduler.scheduler") as mock_sched:
            mock_sched.running = True
            stop_scheduler()
        mock_sched.shutdown.assert_called_once()

    def test_stop_scheduler_noop_when_not_running(self):
        with patch("scheduler.scheduler") as mock_sched:
            mock_sched.running = False
            stop_scheduler()
        mock_sched.shutdown.assert_not_called()
