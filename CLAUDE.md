# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Install with dev dependencies (pytest)
uv sync --group dev

# Run the app
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_scraper.py

# Run a single test
uv run pytest tests/test_routes.py::TestTrack::test_creates_product_in_db
```

## Architecture

The app tracks prices on [mepsking.shop](https://www.mepsking.shop/) (a custom e-commerce platform). It uses **JSON-LD structured data** embedded in each product page (`<script type="application/ld+json">`) rather than an API or HTML scraping.

**Request flow for tracking a product:**
1. User pastes a URL → `POST /lookup` extracts the handle (slug before `.html`), calls `fetch_product()`, renders `preview.html` with variant checkboxes
2. User selects variants → `POST /track` saves `Product` + `Variant` rows and records the first `PriceCheck` immediately
3. `APScheduler` runs `check_all_prices()` every hour in the background; `check_product_prices()` skips inserting a `PriceCheck` when the price and `compare_at_price` are unchanged from the last record

**Scraper strategy** (`scraper.py`):
- Product pages are at `https://www.mepsking.shop/{handle}.html`
- Each page embeds a JSON-LD `ProductGroup` block containing `hasVariant` — an array of individual `Product` entries
- Prices are in `offers.priceSpecification`: entries without `priceType` are the sale price; entries with `priceType == "https://schema.org/StrikethroughPrice"` are the original/RRP price
- Variant names are stored with the product group name as a prefix (e.g. `"Test Motor-1900KV / Blue"`); `parse_product()` strips this prefix so only the variant-specific part is saved
- The `sku` field in JSON-LD is a large numeric string used as `external_variant_id`; the `productId` field is the human-readable SKU (e.g. `AMD01020003`)

**Admin protection:**
- Write actions (`/add`, `/lookup`, `/track`, `POST /products/{handle}/check`, `POST /products/{handle}/delete`) require the session to have `is_admin = True`
- Set `ADMIN_PASSWORD` env var to enable the login wall; `GET /admin/login` and `POST /admin/login` handle auth; `POST /admin/logout` clears the session
- `SESSION_SECRET` env var controls the session signing key (auto-generated random value if unset)

**Data model** (`database.py`):
- `Product` — one row per tracked product (keyed by URL handle)
- `Variant` — one row per tracked variant; `external_variant_id` stores the JSON-LD `sku` (large numeric string); `sku` stores the human-readable `productId`; `tracked=False` soft-disables without deleting history
- `PriceCheck` — append-only price snapshot; only written when the price or `compare_at_price` changes

**Key design decisions:**
- `Product.handle` is the natural key (unique); re-tracking an existing product reuses the same row rather than duplicating it
- `external_variant_id` is `String` (not Integer) to safely hold large numeric SKUs from the JSON-LD
- `time_ago()` in `main.py` normalises naive datetimes to UTC before comparing — necessary because SQLite strips timezone info on read
- `extract_pack_count()` looks for explicit `Npcs`/`Npack` patterns only; it does NOT grab the first number in the name (which would erroneously match KV ratings like "1900KV")
- Prices are displayed in USD (`$`)
- The price history chart uses `stepped: 'before'` (Chart.js) so flat price periods render as horizontal steps; the JS carries the last known price forward and always appends a synthetic "now" label
- Time range buttons (15d / 1m / 3m / 6m / All) filter labels client-side

**Test setup** (`tests/conftest.py`):
- Uses `StaticPool` so all SQLAlchemy sessions share one in-memory SQLite connection within a test
- `client` fixture patches `main.init_db`, `main.start_scheduler`, and `main.stop_scheduler` to avoid touching the production DB or starting background jobs
- `get_db` dependency is overridden via `app.dependency_overrides` to use the test engine
- `FAKE_RAW_PRODUCT` is a JSON-LD `ProductGroup` dict — the format returned by `fetch_product()`

**Starlette 1.3.x API note:** `TemplateResponse` takes `request` as the first positional argument, not inside the context dict:
```python
# correct
templates.TemplateResponse(request, "template.html", {"key": val})
```
