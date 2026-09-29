# Backend foundation verification

## Revision

- Initial `origin/main`: `19cebcff8eae1f94c82d705a39c41dc20d2a81de`
- Final implementation SHA: `6eb798baeccab7d5b71843e5168441b55403e5b0` (the evidence and README are committed separately afterward).
- Work branch: `portfolio/backend-foundation`

## Commands run and observed results

- `git fetch origin --prune`; `git rev-parse origin/main` returned the initial SHA above.
- Python used: `3.13.3` on Windows.
- Initial `pip install -r requirements.txt` succeeded, but the original list did not include Alembic and selected unbounded latest packages. Initial `pytest -q` could not collect because `SECRET_KEY` was missing.
- With a test-only `SECRET_KEY`, the original 70-case suite reported **59 passed, 11 failed**. All 11 failures involved order/payment authorization and expectations; no tests were skipped.
- `python -m pip install -r requirements.txt` in a new `.venv-repro`, followed by `python -m pip check`: installation succeeded and reported `No broken requirements found`.
- Final `pytest -q --junitxml=unit.xml`: **62 passed, 11 failed** (73 collected). The same 11 existing order/payment authorization cases fail with `403 Not enough permissions` or assertions that rely on the blocked customer flow. The three added configuration/health checks pass.
- `ruff check tests/test_configuration.py tests/test_health.py tests/integration/service_checks.py`: passed.
- `docker compose -p backend-foundation down -v`, then `up -d --wait db redis`: started fresh task-owned PostgreSQL 16 and Redis 7 containers with an empty named volume and healthy status.
- `python -m alembic upgrade head`: applied the migration history from an empty PostgreSQL database through `c4d5e6f7a8b9`.
- `python -m alembic current`: returned `c4d5e6f7a8b9 (head)`.
- With `DATABASE_URL`, `ASYNC_DATABASE_URL`, and `TEST_REDIS_URL` set to those local containers, `pytest -q tests/integration/service_checks.py`: **3 passed**. This checked the migration revision, PostgreSQL and Redis connectivity, app import, liveness, and readiness.
- Existing seed tests in the main suite passed, including repeat-run count checks. Seeds remain separate scripts and were not run against the PostgreSQL integration database.

## Test model and external services

The existing API suite uses SQLite tables created from SQLAlchemy metadata in `tests/conftest.py`; it does not validate Alembic. The separate integration checks use PostgreSQL and Redis. No tests were omitted. CI will keep the existing 11 order/payment failures visible until their functional work is addressed.

The test suite emitted SQLAlchemy deprecation warnings during the initial baseline; the captured baseline summary counted 369 warnings, primarily from deprecated `Session.flush(objects)` usage.

## Remaining work for Sol

- Resolve the order/payment authorization behavior and align existing tests with intended rules. Several current tests expect customer order creation but receive `403 Not enough permissions`; other blocked-flow assertions fail downstream.
- Continue the requested functional hardening: stock and reservation concurrency, order creation, payment processing, webhook signatures and event idempotency, refunds, and promotion rules.
- Review the existing SQLAlchemy `Session.flush(objects)` deprecation warnings.
- Run CI on GitHub after publishing this branch; no hosted CI result is claimed by this local evidence.

## Structural decisions to retain

- `requirements.txt` is the only fully pinned Python dependency source; install with `python -m pip install -r requirements.txt`. Alembic and Ruff are included so migrations and the narrow CI lint check work from the same lock.
- PostgreSQL schema changes belong in Alembic. Seeds stay opt-in and do not run during migrations or app startup.
- `/health/live` is process-only. `/health/ready` probes PostgreSQL, the API's required datastore. Redis remains explicitly optional and cannot make API readiness fail.
- Unit tests remain SQLite-based for speed, with a separate required PostgreSQL/Redis integration job to cover service-dependent behavior.
- No Celery worker is part of local Compose or CI because no service-backed worker flow is needed for these foundation checks.
