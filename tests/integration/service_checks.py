"""Smoke checks against disposable PostgreSQL and Redis services."""

import os

import httpx
import pytest
import redis
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


def test_postgresql_is_migrated_and_reachable():
    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            expected_head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
            assert revision == expected_head
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()


def test_redis_is_reachable():
    client = redis.Redis.from_url(os.environ["TEST_REDIS_URL"])
    try:
        assert client.ping() is True
    finally:
        client.close()


@pytest.mark.asyncio
async def test_app_imports_and_reports_health():
    from app.main import app
    from app.db.session_async import async_engine

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        liveness = await client.get("/health/live")
        readiness = await client.get("/health/ready")
        assert liveness.json() == {"status": "alive"}
        assert readiness.json() == {"status": "ready", "database": "available"}
    await async_engine.dispose()
