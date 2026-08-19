# FPV Prices

Price tracker for FPV gear — monitors product variant prices over time and displays history charts.

Supported sites:
- [mepsking.shop](https://www.mepsking.shop/) — JSON-LD structured data, USD, stock tracking
- [ampow.com](https://www.ampow.com/) — Shopify JSON API, EUR

## Features

- Track products from mepsking.shop and ampow.com by pasting a URL
- Select which variants to monitor per product
- Hourly automatic price checks in the background
- Price history chart with 15d / 1m / 3m / 6m / All time ranges
- Per-unit pricing for multi-pack variants
- Stock status tracking (mepsking.shop only)
- Admin password protection for write actions

## Running locally

```bash
# Install dependencies
uv sync

# Start the app (http://localhost:8000)
uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Set `ADMIN_PASSWORD` to protect the add/delete/check actions:

```bash
ADMIN_PASSWORD=secret uv run uvicorn main:app --reload
```

## Running with Docker

```bash
docker build -t fpvprices .
docker run -p 8000:8000 -v fpvprices-data:/data -e ADMIN_PASSWORD=secret fpvprices
```

## Running tests

```bash
uv sync --group dev
uv run pytest
```

## Migrating from ovoprice

If you have an existing `ovoprice.db`, run the migration script to import its data:

```bash
# Preview what will be migrated (no writes)
uv run python migrate_ovoprice.py --dry-run

# Run the migration
uv run python migrate_ovoprice.py

# Custom paths
uv run python migrate_ovoprice.py /path/to/ovoprice.db /path/to/fpvprices.db
```

The target `fpvprices.db` must already exist (created on first app startup). The script is idempotent — safe to re-run.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./fpvprices.db` | SQLAlchemy connection string |
| `ADMIN_PASSWORD` | *(unset)* | Password for admin login; if unset, write routes are unprotected |
| `SESSION_SECRET` | *(random)* | Session signing key; set to a stable value to survive restarts |
