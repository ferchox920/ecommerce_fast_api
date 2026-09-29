import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_local_example_credentials():
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            SECRET_KEY="local-only-change-before-deployment-1234567890",
            REFRESH_SECRET_KEY="production-refresh-secret-that-is-long-enough",
            DATABASE_URL="postgresql+psycopg://prod:secure@db:5432/ecommerce",
        )

    with pytest.raises(ValidationError, match="example credentials"):
        Settings(
            _env_file=None,
            APP_ENV="production",
            SECRET_KEY="production-secret-key-that-is-long-enough",
            REFRESH_SECRET_KEY="production-refresh-secret-that-is-long-enough",
            DATABASE_URL="postgresql+psycopg://app:app@db:5432/ecommerce",
        )
