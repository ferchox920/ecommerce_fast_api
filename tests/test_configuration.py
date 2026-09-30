import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("environment,url", [
    ("production", "http://127.0.0.1:59001"),
    ("development", "http://localhost:59001"),
    ("test", "https://example.com"),
    ("test", "http://localhost:59001/other"),
    ("test", "http://user:password@localhost:59001"),
])
def test_payment_test_boundary_rejects_unsafe_configuration(environment, url):
    with pytest.raises(ValidationError, match="MERCADO_PAGO_API_BASE_URL"):
        Settings(
            _env_file=None,
            APP_ENV=environment,
            SECRET_KEY="a-secure-test-secret-key-long-enough",
            REFRESH_SECRET_KEY="a-different-test-refresh-key-long-enough",
            DATABASE_URL="sqlite:///./test.db",
            MERCADO_PAGO_API_BASE_URL=url,
        )


def test_payment_test_boundary_accepts_explicit_loopback_in_test():
    config = Settings(
        _env_file=None,
        APP_ENV="test",
        SECRET_KEY="a-secure-test-secret-key-long-enough",
        MERCADO_PAGO_API_BASE_URL="http://127.0.0.1:59001/",
    )
    assert config.MERCADO_PAGO_API_BASE_URL == "http://127.0.0.1:59001"


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
