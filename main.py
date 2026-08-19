from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
import json
import os
import re
import secrets

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from database import init_db, get_db, Product, Variant, PriceCheck
from scraper import extract_handle, fetch_product, parse_product
from scheduler import start_scheduler, stop_scheduler, check_product_prices

SESSION_SECRET = os.environ.get("SESSION_SECRET") or secrets.token_hex(32)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler(interval_hours=1)
    yield
    stop_scheduler()


app = FastAPI(title="MepsPrice", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
templates = Jinja2Templates(directory="templates")


class AdminRequired(Exception):
    pass


@app.exception_handler(AdminRequired)
async def admin_required_handler(request: Request, exc: AdminRequired):
    return RedirectResponse(f"/admin/login?next={request.url.path}", status_code=303)


def require_admin(request: Request) -> None:
    if not request.session.get("is_admin"):
        raise AdminRequired()


def time_ago(dt: Optional[datetime]) -> str:
    if not dt:
        return "never"
    # SQLite returns naive datetimes; treat them as UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        m = int(delta.total_seconds() / 60)
        return f"{m}m ago"
    if delta < timedelta(days=1):
        h = int(delta.total_seconds() / 3600)
        return f"{h}h ago"
    d = delta.days
    return f"{d}d ago"


templates.env.globals["time_ago"] = time_ago


def extract_pack_count(name: str) -> int:
    # Look for explicit pack/pcs patterns: "4pcs", "* 4pcs", "4 Pack", "x4"
    m = re.search(r'(\d+)\s*(?:pcs|pack)', name, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        return n if n > 1 else 1
    return 1


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    products = db.query(Product).order_by(Product.created_at.desc()).all()

    product_summaries = []
    for product in products:
        tracked = [v for v in product.variants if v.tracked]
        if not tracked:
            continue

        min_price = None
        first_price = None
        best_per_unit = None
        best_per_unit_variant = None
        has_multi_pack = False
        for variant in tracked:
            checks = (
                db.query(PriceCheck)
                .filter_by(variant_id=variant.id)
                .order_by(PriceCheck.checked_at.asc())
                .all()
            )
            if not checks:
                continue
            latest = checks[-1].price
            first = checks[0].price
            pack_count = extract_pack_count(variant.name)
            if pack_count == 1 and len(tracked) == 1:
                pack_count = extract_pack_count(product.title)
            if pack_count > 1:
                has_multi_pack = True
            per_unit = latest / pack_count
            if min_price is None or latest < min_price:
                min_price = latest
            if first_price is None or first < first_price:
                first_price = first
            if best_per_unit is None or per_unit < best_per_unit:
                best_per_unit = per_unit
                best_per_unit_variant = variant.name

        change_pct = None
        if min_price is not None and first_price and first_price > 0:
            change_pct = round((min_price - first_price) / first_price * 100, 1)

        product_summaries.append(
            {
                "product": product,
                "min_price": min_price,
                "first_price": first_price,
                "change_pct": change_pct,
                "variant_count": len(tracked),
                "best_per_unit": best_per_unit,
                "best_per_unit_variant": best_per_unit_variant,
                "has_multi_pack": has_multi_pack,
            }
        )

    return templates.TemplateResponse(request, "index.html", {"summaries": product_summaries})


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request, next: str = "/add"):
    return templates.TemplateResponse(request, "admin_login.html", {"next": next})


@app.post("/admin/login")
def admin_login_post(request: Request, password: str = Form(...), next: str = Form(default="/add")):
    if not next.startswith("/"):
        next = "/add"
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if admin_password and password == admin_password:
        request.session["is_admin"] = True
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(
        request, "admin_login.html", {"error": "Invalid password", "next": next}, status_code=401
    )


@app.post("/admin/logout")
def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/add", response_class=HTMLResponse)
def add_page(request: Request, error: Optional[str] = None, _=Depends(require_admin)):
    return templates.TemplateResponse(request, "add.html", {"error": error})


@app.post("/lookup", response_class=HTMLResponse)
def lookup_product(request: Request, url: str = Form(...), _=Depends(require_admin)):
    handle = extract_handle(url)
    if not handle:
        return templates.TemplateResponse(request, "add.html", {"error": "Invalid URL. Please paste a valid mepsking.shop product URL."})

    raw = fetch_product(handle)
    if not raw:
        return templates.TemplateResponse(request, "add.html", {"error": f"Could not fetch product '{handle}'. Check the URL and try again."})

    product_data = parse_product(raw)
    return templates.TemplateResponse(request, "preview.html", {"product": product_data})


@app.post("/track")
def track_product(
    request: Request,
    handle: str = Form(...),
    variant_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    _=Depends(require_admin),
):
    if not variant_ids:
        return RedirectResponse(f"/add?error=Select+at+least+one+variant", status_code=303)

    existing = db.query(Product).filter_by(handle=handle).first()

    raw = fetch_product(handle)
    if not raw:
        raise HTTPException(status_code=400, detail="Could not fetch product")

    data = parse_product(raw)

    if not existing:
        product = Product(
            handle=data["handle"],
            title=data["title"],
            image_url=data["image_url"],
            product_url=data["product_url"],
        )
        db.add(product)
        db.flush()
    else:
        product = existing

    for v_data in data["variants"]:
        if v_data["external_variant_id"] not in variant_ids:
            continue
        existing_variant = (
            db.query(Variant)
            .filter_by(product_id=product.id, external_variant_id=v_data["external_variant_id"])
            .first()
        )
        if not existing_variant:
            variant = Variant(
                product_id=product.id,
                external_variant_id=v_data["external_variant_id"],
                name=v_data["name"],
                sku=v_data["sku"],
                tracked=True,
            )
            db.add(variant)
            db.flush()
            check = PriceCheck(
                variant_id=variant.id,
                price=v_data["price"],
                compare_at_price=v_data["compare_at_price"],
                in_stock=v_data["in_stock"],
            )
            db.add(check)
        else:
            existing_variant.tracked = True

    product.last_checked_at = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(f"/products/{handle}", status_code=303)


@app.get("/products/{handle}", response_class=HTMLResponse)
def product_detail(request: Request, handle: str, db: Session = Depends(get_db)):
    product = db.query(Product).filter_by(handle=handle).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    tracked_variants = [v for v in product.variants if v.tracked]

    variant_data = []
    chart_datasets = []
    all_labels = set()

    for variant in tracked_variants:
        checks = (
            db.query(PriceCheck)
            .filter_by(variant_id=variant.id)
            .order_by(PriceCheck.checked_at.asc())
            .all()
        )
        if not checks:
            continue

        first_price = checks[0].price
        latest_price = checks[-1].price
        compare_at = checks[-1].compare_at_price
        in_stock = checks[-1].in_stock
        change_pct = round((latest_price - first_price) / first_price * 100, 1) if first_price else 0
        pack_count = extract_pack_count(variant.name)
        if pack_count == 1 and len(tracked_variants) == 1:
            pack_count = extract_pack_count(product.title)

        variant_data.append(
            {
                "variant": variant,
                "first_price": first_price,
                "latest_price": latest_price,
                "compare_at_price": compare_at,
                "in_stock": in_stock,
                "change_pct": change_pct,
                "change_count": sum(1 for i in range(1, len(checks)) if checks[i].price != checks[i-1].price),
                "pack_count": pack_count,
                "price_per_unit": latest_price / pack_count,
            }
        )

        labels = [c.checked_at.strftime("%Y-%m-%d %H:%M") for c in checks]
        prices = [c.price for c in checks]
        stock = [c.in_stock for c in checks]
        for label in labels:
            all_labels.add(label)

        chart_datasets.append(
            {
                "label": variant.name,
                "labels": labels,
                "data": prices,
                "stock": stock,
            }
        )

    sorted_labels = sorted(all_labels)

    has_multi_pack = any(v["pack_count"] > 1 for v in variant_data)

    return templates.TemplateResponse(request, "product.html", {
        "product": product,
        "variant_data": variant_data,
        "chart_datasets_json": json.dumps(chart_datasets),
        "chart_labels_json": json.dumps(sorted_labels),
        "has_multi_pack": has_multi_pack,
    })


@app.post("/products/{handle}/check")
def manual_check(handle: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    product = db.query(Product).filter_by(handle=handle).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    check_product_prices(handle)
    return RedirectResponse(f"/products/{handle}", status_code=303)


@app.post("/products/{handle}/delete")
def delete_product(handle: str, db: Session = Depends(get_db), _=Depends(require_admin)):
    product = db.query(Product).filter_by(handle=handle).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    db.delete(product)
    db.commit()
    return RedirectResponse("/", status_code=303)


def main():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
