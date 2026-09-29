# E-commerce API

Backend HTTP API for a store catalog and its customer and administrative workflows. It provides catalog, inventory, cart, order, payment, purchasing, promotion, loyalty, notification, and reporting endpoints.

## Architecture

- FastAPI and Pydantic for HTTP and validation.
- SQLAlchemy async sessions with PostgreSQL as the application database.
- Alembic for structural migrations.
- Redis is optional for rate limits, token blacklist, caching, and local integration checks.
- Celery tasks exist for background email/report work; this local setup does not start a worker.
- Most existing API tests use SQLite and create their schema from SQLAlchemy metadata. The PostgreSQL migration checks are separate.

## Requirements

- Python 3.13 (the verified dependency lock targets this interpreter).
- Docker Desktop or Docker Engine with Compose v2.

## Install and start locally

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
docker compose -p ecommerce-local up -d --wait db redis
```

On macOS/Linux, activate `.venv` and use `docker compose -p ecommerce-local up -d --wait db redis`.
The Compose project has its own named volume and network. Stop it with `docker compose -p ecommerce-local down`; add `-v` only when you want to discard its local database volume.

`.env.example` contains development-only credentials for the local containers. Replace both signing keys before deploying. Production requires `APP_ENV=production`, a `SECRET_KEY` of at least 32 characters, and a different `REFRESH_SECRET_KEY` of at least 32 characters. Database configuration is required by the running API. Redis is optional; leaving `REDIS_URL` unset uses the application's in-process fallbacks.

Optional provider settings are blank by default. Mercado Pago and Cloudinary operations require their respective credentials and can contact external services; no seed or CI command invokes them. Email delivery is disabled by default.

## Migrations and demo data

With the services running and `.env` configured:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

This applies the full schema to an empty PostgreSQL database. Seeds are opt-in and separate from migrations:

```powershell
.\.venv\Scripts\python.exe scripts/seed_dev_users.py
.\.venv\Scripts\python.exe scripts/seed_dev_products.py
.\.venv\Scripts\python.exe scripts/seed_product_relationships.py
```

The seeds use fictitious `.test` accounts and sample catalog content. They are designed to be re-run and do not provision provider accounts or call payment, image-hosting, or email APIs. Treat the seeded user credentials as public development data.

## Run the API

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Open `/docs` for the interactive API documentation.

## Health endpoints

- `GET /health/live` confirms the process is running and does not probe dependencies.
- `GET /health/ready` checks PostgreSQL and returns `503` if it cannot connect. Redis is optional and does not block readiness.

## Tests and checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The main suite uses SQLite test fixtures. The last measured run before this foundation work collected 70 cases; the updated count and result are recorded in the [verification evidence](docs/verification/backend-foundation.md). PostgreSQL migrations and Redis checks run separately in GitHub Actions against disposable services. Locally, after starting Compose and applying migrations, set `TEST_REDIS_URL=redis://localhost:6379/0` and run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/integration/service_checks.py
```

Dependencies are fully pinned in `requirements.txt`; install with `python -m pip install -r requirements.txt`. Dependabot checks pip and GitHub Actions weekly.

## Known limits

- Unit tests currently expose existing order/payment authorization failures; see verification evidence. This foundation work does not change their business behavior.
- The main suite creates tables through ORM metadata; it is not evidence that production schema migrations are correct. Use the dedicated PostgreSQL migration job for that check.
- No deployment, coverage percentage, production account, or third-party payment credentials are included.
- Payment correctness, inventory concurrency, order creation, webhook security, event idempotency, refunds, and promotion rules remain follow-up hardening work.
