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

The app tracks FPV gear prices across multiple e-commerce sites. Each site is handled by a **plugin** (`plugins/`) that implements scraping, URL parsing, and site-specific behaviour. A shared core handles routes, scheduling, templates, and the database.

**Request flow for tracking a product:**
1. User pastes a URL → `POST /lookup` calls `get_plugin_for_url()` to find the right plugin, extracts the handle, fetches and parses the product, renders `preview.html` with variant checkboxes
2. User selects variants → `POST /track` receives the `site` form field, re-fetches via the plugin, saves `Product` (with `site`) + `Variant` rows and records the first `PriceCheck`
3. `APScheduler` runs `check_all_prices()` every hour; `check_product_prices()` looks up the product's plugin via `product.site`, skips writing a `PriceCheck` when price, `compare_at_price`, and (if `plugin.tracks_stock`) `in_stock` are all unchanged

**Plugin system** (`plugins/`):
- `plugins/__init__.py` — `SitePlugin` ABC + registry (`register`, `get_plugin`, `get_plugin_for_url`)
- `plugins/mepsking.py` — `MepskingPlugin`: scrapes JSON-LD `ProductGroup` from HTML, `currency="$"`, `tracks_stock=True`
- `plugins/ampow.py` — `AmpowPlugin`: calls Shopify JSON API (`/products/{handle}.json`), `currency="€"`, `tracks_stock=False`
- `scraper.py` — thin backward-compat wrapper delegating to `MepskingPlugin`; kept so existing scraper tests don't need changes

**Adding a new site:** create `plugins/<site>.py` with a class extending `SitePlugin`, implement `can_handle`, `extract_handle`, `fetch_product`, `parse_product`, and optionally override `extract_pack_count`. Register the instance at the bottom of `plugins/__init__.py`.

**MepsKing scraper strategy** (`plugins/mepsking.py`):
- Product pages are at `https://www.mepsking.shop/{handle}.html`
- Each page embeds a JSON-LD `ProductGroup` block containing `hasVariant` — an array of individual `Product` entries
- Prices are in `offers.priceSpecification`: entries without `priceType` are the sale price; entries with `priceType == "https://schema.org/StrikethroughPrice"` are the original/RRP price
- Variant names are stored with the product group name as a prefix (e.g. `"Test Motor-1900KV / Blue"`); `parse_product()` strips this prefix so only the variant-specific part is saved
- The `sku` field in JSON-LD is a large numeric string used as `external_variant_id`; the `productId` field is the human-readable SKU (e.g. `AMD01020003`)

**Ampow scraper strategy** (`plugins/ampow.py`):
- Shopify store; fetches `https://www.ampow.com/products/{handle}.json`
- Variant IDs are Shopify integers, stored as strings in `external_variant_id`
- No stock availability in the API; `in_stock` is always stored as `True`

**Admin protection:**
- Write actions (`/lookup`, `/track`, `POST /products/{handle}/check`, `POST /products/{handle}/delete`) require the session to have `is_admin = True`
- Set `ADMIN_PASSWORD` env var to enable the login wall; `GET /admin/login` and `POST /admin/login` handle auth; `POST /admin/logout` clears the session
- `SESSION_SECRET` env var controls the session signing key (auto-generated random value if unset)

**Data model** (`database.py`):
- `Product` — one row per tracked product (keyed by URL handle); `site` column stores the plugin name (e.g. `"mepsking"`, `"ampow"`)
- `Variant` — one row per tracked variant; `external_variant_id` stores the site-specific variant ID as a string; `sku` stores the human-readable SKU; `tracked=False` soft-disables without deleting history
- `PriceCheck` — append-only price snapshot; `in_stock` is `True` for plugins that don't track stock

**Key design decisions:**
- `Product.handle` is the natural key (unique across all sites); re-tracking an existing product reuses the same row
- `external_variant_id` is `String` (not Integer) to hold both large numeric mepsking SKUs and Shopify integer IDs
- Plugin currency (`plugin.currency`) and stock-column visibility (`plugin.tracks_stock`) are resolved at render time from `product.site`
- `extract_pack_count()` is plugin-specific: mepsking matches explicit `Npcs`/`Npack` patterns only (avoids matching KV ratings like "1900KV"); ampow matches the first number in the name
- `time_ago()` in `main.py` normalises naive datetimes to UTC before comparing — necessary because SQLite strips timezone info on read
- The price history chart uses `stepped: 'before'` (Chart.js) so flat price periods render as horizontal steps; the JS carries the last known price forward and always appends a synthetic "now" label
- Time range buttons (15d / 1m / 3m / 6m / All) filter labels client-side
- Stock-based dashed-line rendering in the chart is gated on the `tracksStock` JS variable so ampow charts are unaffected

**Test setup** (`tests/conftest.py`):
- Uses `StaticPool` so all SQLAlchemy sessions share one in-memory SQLite connection within a test
- `client` fixture patches `main.init_db`, `main.start_scheduler`, and `main.stop_scheduler` to avoid touching the production DB or starting background jobs
- `get_db` dependency is overridden via `app.dependency_overrides` to use the test engine
- `FAKE_RAW_PRODUCT` is a JSON-LD `ProductGroup` dict — the format `MepskingPlugin.fetch_product()` returns
- Plugin methods are mocked via `patch.object(get_plugin("mepsking"), "fetch_product", ...)` rather than patching module-level names; `/track` form data must include `site="mepsking"`

**Starlette 1.3.x API note:** `TemplateResponse` takes `request` as the first positional argument, not inside the context dict:
```python
# correct
templates.TemplateResponse(request, "template.html", {"key": val})
```
