from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from database import engine, Product, Variant, PriceCheck
from scraper import fetch_product, parse_product

scheduler = BackgroundScheduler()


def check_all_prices():
    with Session(engine) as session:
        products = session.query(Product).all()
        for product in products:
            check_product_prices(product.handle, session)
        session.commit()


def check_product_prices(handle: str, session: Session | None = None):
    own_session = session is None
    if own_session:
        session = Session(engine)

    try:
        raw = fetch_product(handle)
        if not raw:
            return

        data = parse_product(raw)
        now = datetime.now(timezone.utc)

        product = session.query(Product).filter_by(handle=handle).first()
        if not product:
            return

        product.last_checked_at = now

        variant_map = {v.external_variant_id: v for v in product.variants}

        for v_data in data["variants"]:
            variant = variant_map.get(v_data["external_variant_id"])
            if variant and variant.tracked:
                last = (
                    session.query(PriceCheck)
                    .filter_by(variant_id=variant.id)
                    .order_by(PriceCheck.checked_at.desc())
                    .first()
                )
                if (
                    last
                    and last.price == v_data["price"]
                    and last.compare_at_price == v_data["compare_at_price"]
                    and last.in_stock == v_data["in_stock"]
                ):
                    continue
                check = PriceCheck(
                    variant_id=variant.id,
                    price=v_data["price"],
                    compare_at_price=v_data["compare_at_price"],
                    in_stock=v_data["in_stock"],
                    checked_at=now,
                )
                session.add(check)

        if own_session:
            session.commit()
    finally:
        if own_session:
            session.close()


def start_scheduler(interval_hours: int = 1):
    scheduler.add_job(
        check_all_prices,
        "interval",
        hours=interval_hours,
        id="price_check",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
