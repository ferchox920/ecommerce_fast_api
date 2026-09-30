# E-commerce API

Backend HTTP API for a store catalog and its customer and administrative workflows. It provides catalog, inventory, cart, order, payment, purchasing, promotion, loyalty, notification, and reporting endpoints.

The separate [e-fast frontend](https://github.com/ferchox920/e-fast) is the Next.js/RTK Query client. Its README documents the reproducible production journey with PostgreSQL, Redis and a local payment provider. The [evaluation guide and screenshots](https://github.com/ferchox920/e-fast/blob/main/docs/review/author-review.md) distinguish automated verification from the pending human visual review. The local provider does not validate real Mercado Pago checkout or perform real charges.

## Architecture

- FastAPI and Pydantic for HTTP and validation.
- SQLAlchemy async sessions with PostgreSQL as the application database.
- Alembic for structural migrations.
- Redis is used for rate limits and token blacklist where configured; the commercial integration job runs it alongside PostgreSQL.
- Celery tasks exist for background email/report work; this local setup does not start a worker.
- The unit API suite uses SQLite. A separate CI job exercises the real API, PostgreSQL transactions, Redis readiness, and a deterministic Mercado Pago double.

## Demonstrated commercial flow

```mermaid
flowchart LR
    Catalog[Catalog and variants] --> Cart[Customer cart]
    Cart --> Order[Order and stock reservation]
    Order --> Preference[Mercado Pago preference]
    Preference --> Webhook[Signed webhook]
    Webhook --> Sale[Paid order and stock sale]
    Sale --> Refund[Partial or full refund]
    Order --> Notification[Committed notification]
    Sale --> Notification
```

The [commercial API test](tests/integration/commerce_flow.py) creates a product, receives inventory, authenticates users, builds a cart, applies a product promotion, creates an order, simulates a payment preference and a signed webhook, then checks the stock sale, notification, duplicate webhook, access denial, and idempotent partial refund. It uses the application and migrated PostgreSQL schema; only Mercado Pago calls are replaced by a controlled double.

PostgreSQL row locks serialize stock changes per variant and refunds per payment. Database constraints enforce nonnegative stock and `reserved <= on_hand`. Inventory movements record signed adjustments and optional idempotency keys. Direct sales cannot consume an order's reservation. A cart can be converted once; direct order creation accepts an `Idempotency-Key` header. Product prices and promotion discounts are calculated at checkout rather than accepted from request totals. Order lines retain unit price, line total, SKU, and product title as purchase-time snapshots.

Webhook validation uses Mercado Pago's `x-signature`, `x-request-id`, and URL `data.id` contract, including millisecond timestamps. The handler retrieves the payment from Mercado Pago, checks its order reference, amount, and currency, then applies a legal transition. Duplicate and stale events do not repeat effects. Refund requests accept `Idempotency-Key`; the key is forwarded to Mercado Pago and stored with the refund record. Provider failures leave the database transaction uncommitted. Notification delivery is queued until commit. See [Mercado Pago's webhook contract](https://www.mercadopago.com.ar/developers/en/docs/wallet-connect/notifications) and [idempotency guidance](https://www.mercadopago.com.ar/developers/en/news/2023/01/04/Idempotency-key-usage-will-be-mandatory).

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

To verify idempotency on a fresh, migrated PostgreSQL database, run `python -m scripts.verify_seed_idempotency` twice. Each invocation executes the three documented seeds twice, checks row counts and references, and rejects external connections. Use a disposable database; this command inserts the sample data.

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
.\.venv\Scripts\python.exe -m ruff check app tests migrations scripts
```

The main suite uses SQLite test fixtures. PostgreSQL migrations and Redis checks run separately in GitHub Actions against disposable services. Locally, after starting Compose and applying migrations, configure `DATABASE_URL`, `ASYNC_DATABASE_URL`, `REDIS_URL`, and `TEST_REDIS_URL` for your local services, then run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/integration/service_checks.py
.\.venv\Scripts\python.exe -m pytest -q tests/integration/inventory_concurrency.py tests/integration/refund_concurrency.py tests/integration/commerce_flow.py
```

For the Compose defaults, the URLs are `postgresql+psycopg://app:app@localhost:5433/ecommerce`, `postgresql+asyncpg://app:app@localhost:5433/ecommerce`, and `redis://localhost:6379/0`. Run `alembic upgrade head` against an empty PostgreSQL database before the tests. The [technical evaluation guide](docs/verification/backend-hardening.md) records the exact commands and observed local evidence.

Dependencies are fully pinned in `requirements.txt`; install with `python -m pip install -r requirements.txt`. Dependabot checks pip and GitHub Actions weekly.

## Known limits

- Only product and category promotions with `discount_percent` are applied at checkout. Other promotion types have eligibility endpoints but are not checkout discounts.
- Full refunds restore item stock only for paid, unfulfilled orders. Partial refunds do not automatically restore items.
- Guest cart tokens act as possession credentials. Keep them private; this API does not add an account recovery flow for guests.
- The main suite uses ORM-created SQLite tables. Use the dedicated PostgreSQL job to verify migrations, concurrency, and the commercial API path.
- External payment calls are simulated in tests. No production credentials, deployment, coverage percentage, or performance claim is included.
