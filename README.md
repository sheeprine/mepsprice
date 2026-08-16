# MepsPrice

Price tracker for [mepsking.shop](https://www.mepsking.shop/) — monitors product variant prices over time and displays history charts.

## Features

- Track any mepsking.shop product by pasting its URL
- Select which variants to monitor per product
- Hourly automatic price checks in the background
- Price history chart with 15d / 1m / 3m / 6m / All time ranges
- Per-unit pricing for multi-pack variants
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
docker build -t mepsprice .
docker run -p 8000:8000 -v mepsprice-data:/data -e ADMIN_PASSWORD=secret mepsprice
```

## Running tests

```bash
uv sync --group dev
uv run pytest
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./mepsprice.db` | SQLAlchemy connection string |
| `ADMIN_PASSWORD` | *(unset)* | Password for admin login; if unset, write routes are unprotected |
| `SESSION_SECRET` | *(random)* | Session signing key; set to a stable value to survive restarts |
