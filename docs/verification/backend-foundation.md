# Backend foundation verification

## Revision

- Initial `origin/main`: `19cebcff8eae1f94c82d705a39c41dc20d2a81de`
- Final implementation SHA at PR creation: `6301dc075b4379b67109745519e77c186c252856` (the later evidence update changes documentation only).
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
- GitHub Actions on PR commit `6301dc075b4379b67109745519e77c186c252856`: the PostgreSQL/Redis job passed, including install, migrations, and all three integration checks; CodeQL passed; the unit job failed on the same 11 order/payment cases. [Backend CI run](https://github.com/ferchox920/ecommerce_fast_api/actions/runs/36508629271) · [CodeQL run](https://github.com/ferchox920/ecommerce_fast_api/actions/runs/36508629274).
- Existing seed tests in the main suite passed, including repeat-run count checks. Seeds remain separate scripts and were not run against the PostgreSQL integration database.

## Test model and external services

The existing API suite uses SQLite tables created from SQLAlchemy metadata in `tests/conftest.py`; it does not validate Alembic. The separate integration checks use PostgreSQL and Redis. No tests were omitted. CI will keep the existing 11 order/payment failures visible until their functional work is addressed.

The test suite emitted SQLAlchemy deprecation warnings during the initial baseline; the captured baseline summary counted 369 warnings, primarily from deprecated `Session.flush(objects)` usage.

## Historical follow-up at the foundation checkpoint

- Resolve the order/payment authorization behavior and align existing tests with intended rules. Several current tests expect customer order creation but receive `403 Not enough permissions`; other blocked-flow assertions fail downstream.
- Continue the requested functional hardening: stock and reservation concurrency, order creation, payment processing, webhook signatures and event idempotency, refunds, and promotion rules.
- Review the existing SQLAlchemy `Session.flush(objects)` deprecation warnings.
- At that checkpoint, the unit job was red for the documented functional failures. Later commits resolved them; see the closeout evidence below.

## PR #1 technical closeout (2026-09-29)

- Initial local and remote SHA: `476e25c05dfa66e77c13b2bba190625cdbbebf44`; base remains `main` at `19cebcff8eae1f94c82d705a39c41dc20d2a81de`.
- Fresh Windows virtual environment, Python 3.13.3: `python -m pip install -r requirements.txt` succeeded; `python -m pip check` found no broken requirements.
- Initial `python -m ruff check app tests`: **39 errors**. Final `python -m ruff check app tests` and the CI command `python -m ruff check app tests migrations scripts`: **0 errors**. `ruff.toml` checks all four trees; six explicit E402 exceptions are only for entry points that establish the import path or test environment before importing the app. No directory is excluded.
- SQLite suite: **88 passed, 0 failed, 0 skipped**; one Starlette/AnyIO deprecation warning remains. Mercado Pago is tested through async HTTP doubles with no provider traffic.
- Disposable PostgreSQL 16 and Redis 7: migrations from an empty database reached `e2b7a93c4d10 (head)`. Service checks: **3 passed**. Inventory, refund and commercial flow: **8 passed** on a separate fresh database without seed data.
- On an empty migrated PostgreSQL database, `python -m scripts.verify_seed_idempotency` was invoked twice. Each invocation ran the three documented seeds twice. The 12 relevant table counts stayed identical across all four passes: users 4, categories 2, brands 2, suppliers 2, products 3, variants 5, images 6, questions 3, wishes 3, movements 3, promotions 2, promotion-product links 1. Referential and duplicate-key checks passed; external connections: **0**.
- GitHub Actions use official Node.js 24 action majors: [checkout v6](https://github.com/actions/checkout/releases/tag/v6.0.0), [setup-python v6](https://github.com/actions/setup-python/releases/tag/v6.0.0), [upload-artifact v6](https://github.com/actions/upload-artifact/releases/tag/v6.0.0), and [CodeQL v4](https://github.com/github/codeql-action/releases). Hosted CI evidence and the final SHA are recorded in PR #1 after publication.

## Structural decisions to retain

- `requirements.txt` is the only fully pinned Python dependency source; install with `python -m pip install -r requirements.txt`. Alembic and Ruff are included so migrations and the narrow CI lint check work from the same lock.
- PostgreSQL schema changes belong in Alembic. Seeds stay opt-in and do not run during migrations or app startup.
- `/health/live` is process-only. `/health/ready` probes PostgreSQL, the API's required datastore. Redis remains explicitly optional and cannot make API readiness fail.
- Unit tests remain SQLite-based for speed, with a separate required PostgreSQL/Redis integration job to cover service-dependent behavior.
- No Celery worker is part of local Compose or CI because no service-backed worker flow is needed for these foundation checks.
