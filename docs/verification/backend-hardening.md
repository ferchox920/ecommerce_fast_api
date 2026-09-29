# Technical evaluation guide: commercial guarantees

This work continues the backend foundation at starting commit `62a19628637a162aa2ea81ba94c98c3bb82eeefe` on `portfolio/backend-foundation` (PR #1). The foundation evidence is in [backend-foundation.md](backend-foundation.md).

## Reproduce locally

Use Python 3.13, install `requirements.txt`, start disposable PostgreSQL 16 and Redis 7 from `docker-compose.yml`, and apply `python -m alembic upgrade head` to an **empty** PostgreSQL database. Set:

```text
APP_ENV=test
SECRET_KEY=<local test-only value>
DATABASE_URL=postgresql+psycopg://app:app@localhost:5433/ecommerce
ASYNC_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/ecommerce
REDIS_URL=redis://localhost:6379/0
TEST_REDIS_URL=redis://localhost:6379/0
```

Then run:

```text
python -m pytest -q
python -m pytest -q tests/integration/service_checks.py tests/integration/inventory_concurrency.py tests/integration/refund_concurrency.py tests/integration/commerce_flow.py
```

The integration files have explicit names so the SQLite unit command does not collect tests that require PostgreSQL. The CI `commerce-integration` job runs them against fresh services and uploads JUnit and service diagnostics on failure.

## Invariants and evidence

| Guarantee | Enforcement | Executed local evidence |
| --- | --- | --- |
| Last unit has one claimant | PostgreSQL variant row lock and database stock checks | Two concurrent sessions; only one reserve or sale succeeds. |
| Retry does not repeat inventory movement | Unique `(variant_id, idempotency_key)` and comparison under row lock | Concurrent same-key retry leaves one movement. |
| An order's reservation belongs to that order | Reservation ledger keyed by `order:<id>` | Another order cannot release or sell it; direct sale uses only unreserved stock. |
| Failed order leaves no reservation | Order and movements share one transaction | Second-line failure followed by rollback leaves no order, reservation, or movement. |
| Refund cannot exceed payment | Payment row lock, refundable balance check, unique refund key | Two concurrent 70-unit requests against 100 yield one refund; same-key retry makes no second call. |
| Webhook is authentic and bound to its order | HMAC over URL `data.id`, request ID, timestamp; provider lookup checks external reference, amount, currency | Missing, changed, stale, unconfigured, wrong-order, duplicate, and out-of-order cases in `tests/test_payments.py`. |
| API journey works on migrated PostgreSQL | Real app sessions and Redis, controlled Mercado Pago boundary | Product, stock, login, cart, promotion, order, payment, webhook, notification, access denial, and refund in `commerce_flow.py`. |

Executed locally for the final closeout: SQLite suite **88 passed, 0 failed, 0 skipped**; empty PostgreSQL migration through `e2b7a93c4d10` succeeded; PostgreSQL/Redis service checks **3 passed** and commercial integration **8 passed**. The seed verification ran four passes across two invocations on a separate migrated PostgreSQL database. Hosted CI evidence for the final SHA is recorded in PR #1.

## Review points

- `app/services/inventory_service.py` owns stock transitions. `product_service/variants.py` routes administrative stock edits into audited transitions.
- `app/services/order_service.py` computes the price and promotional discount, reserves stock, and marks payment transitions in the caller's transaction.
- New order lines snapshot SKU and product title as well as price; the snapshot migration backfills existing lines from the current catalog.
- `app/services/payment_service.py` verifies provider data and serializes refunds. `payment_providers/mercado_pago.py` contains the provider-specific HTTP and HMAC contract.
- `app/services/notification_service.py` queues delivery until commit. Database notification rows and commercial effects share the transaction.

## Limits

The product and category percentage discount path is demonstrated; customer and loyalty promotion eligibility does not imply checkout application. A client must reuse its idempotency key on retries. A timeout after a provider refund requires reconciliation with Mercado Pago using the same key. Unit tests run on SQLite, while transactional and concurrency guarantees are evaluated on PostgreSQL. Provider APIs are simulated in CI.

Mercado Pago preference creation, payment lookup and refunds now await `httpx.AsyncClient` requests, each with a 15-second timeout and an automatically closed client. The refund provider call still occurs while the PostgreSQL payment row is locked in the caller's transaction; a slow provider can therefore hold that lock for up to the timeout. This local change does not add distributed refund orchestration. The unit suite validates seeded image URL structure offline; it does not test the remote image host's availability.
