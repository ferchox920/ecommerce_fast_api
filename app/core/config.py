"""Application configuration with strict environment validation."""

from pathlib import Path
import warnings
from urllib.parse import urlsplit
from pydantic import Field, field_validator, model_validator, EmailStr
from pydantic_settings import BaseSettings, SettingsConfigDict


_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Settings loaded from environment variables or .env file."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE if _ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Security & database ---
    APP_ENV: str = "development"
    SECRET_KEY: str = Field(..., min_length=16)
    REFRESH_SECRET_KEY: str | None = None
    # Cambia el valor predeterminado si usas PostgreSQL por defecto
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/appdb" # Ejemplo PostgreSQL
    # DATABASE_URL: str = "sqlite:///./test.db" # Ejemplo SQLite anterior
    ASYNC_DATABASE_URL: str | None = None
    REDIS_URL: str | None = None
    SECRET_KEY_FALLBACKS: list[str] = Field(default_factory=list)
    REFRESH_SECRET_KEY_FALLBACKS: list[str] = Field(default_factory=list)
    JWT_BLACKLIST_ENABLED: bool = False
    JWT_BLACKLIST_TTL_LEEWAY_SECONDS: int = 300
    LOG_LEVEL: str = "INFO"
    METRICS_ENABLED: bool = True
    METRICS_NAMESPACE: str = "fastapi"
    METRICS_LATENCY_BUCKETS: list[float] = Field(default_factory=lambda: [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0])
    STRICT_TRANSPORT_SECURITY: str = "max-age=63072000; includeSubDomains; preload"
    # Incluye cdn.jsdelivr.net y recursos de FastAPI para que Swagger UI cargue correctamente.
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
    )
    X_FRAME_OPTIONS: str = "DENY"
    X_CONTENT_TYPE_OPTIONS: str = "nosniff"
    REFERRER_POLICY: str = "no-referrer"
    MAX_REQUEST_SIZE_BYTES: int = 2 * 1024 * 1024  # 2MB default

    # --- Tokens ---
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    VERIFY_TOKEN_EXPIRE_HOURS: int = 24
    ENFORCE_EMAIL_VERIFICATION: bool = True

    # --- API metadata ---
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "E-Commerce API"
    JWT_ALGORITHM: str = "HS256"

    # --- Emails ---
    EMAILS_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TLS: bool = True
    EMAIL_FROM: str = "no-reply@example.com"

    # --- URLs ---
    API_BASE_URL: str = "http://127.0.0.1:8000"
    FRONTEND_URL: str = ""
    GOOGLE_OAUTH_CLIENT_ID: str = ""

    # --- Payments / Mercado Pago ---
    MERCADO_PAGO_ACCESS_TOKEN: str = ""
    MERCADO_PAGO_API_BASE_URL: str = "https://api.mercadopago.com"
    MERCADO_PAGO_NOTIFICATION_URL: str = ""
    MERCADO_PAGO_SUCCESS_URL: str = ""
    MERCADO_PAGO_FAILURE_URL: str = ""
    MERCADO_PAGO_PENDING_URL: str = ""
    MERCADO_PAGO_WEBHOOK_SECRET: str = ""
    MERCADO_PAGO_WEBHOOK_TOLERANCE_SECONDS: int = 300
    MERCADO_PAGO_WEBHOOK_REPLAY_TTL_SECONDS: int = 86400

    # --- Cloudinary / Media storage ---
    CLOUD_NAME_CLOUDINARY: str | None = None
    API_KEY_CLOUDINARY: str | None = None
    API_SECRET_CLOUDINARY: str | None = None
    CLOUDINARY_UPLOAD_FOLDER: str = "products"
    CLOUDINARY_SECURE_DELIVERY: bool = True

    # --- Exposure engine defaults ---
    EXPOSURE_POPULARITY_WEIGHT: float = 0.7
    EXPOSURE_STRATEGIC_WEIGHT: float = 0.3
    EXPOSURE_CATEGORY_CAP: int = 3
    EXPOSURE_COLD_THRESHOLD: float = 0.6
    EXPOSURE_STOCK_THRESHOLD: int = 15
    EXPOSURE_FRESHNESS_THRESHOLD: float = 0.7
    EXPOSURE_CACHE_TTL: int = 600

    # --- Rate limiting ---
    RATE_LIMIT_REGISTRATION_PER_MINUTE: int = 5
    RATE_LIMIT_REGISTRATION_WINDOW_SECONDS: int = 60
    RATE_LIMIT_REPORTS_PER_MINUTE: int = 30
    RATE_LIMIT_REPORTS_WINDOW_SECONDS: int = 60

    # --- Scoring defaults ---
    SCORING_WINDOW_DAYS: int = 14
    SCORING_HALF_LIFE_DAYS: float = 3.0
    SCORING_FRESHNESS_HALF_LIFE: float = 1.5

    # --- Celery / broker configuration ---
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"
    CELERY_TASK_ALWAYS_EAGER: bool = True
    CELERY_TASK_DEFAULT_QUEUE: str = "default"
    EMAIL_QUEUE: str = "emails"
    REPORTS_QUEUE: str = "reports"
    SCORING_QUEUE: str = "scoring"
    PROMOTION_EVENTS_QUEUE: str = "promotion-events"
    LOYALTY_EVENTS_QUEUE: str = "loyalty-events"
    WISH_QUEUE: str = "wish-events"
    TASK_RESULT_TIMEOUT: int = 30

    # --- Configuración del Admin Inicial ---
    INITIAL_ADMIN_EMAIL: EmailStr | None = Field(default=None, description="Email for the first admin user created on startup if none exists.")
    INITIAL_ADMIN_PASSWORD: str | None = Field(default=None, min_length=8, description="Password for the first admin user.")


    @staticmethod
    def _split_list(value: str | list[str] | None) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [item for item in value if isinstance(item, str) and item.strip()]

    @staticmethod
    def _split_float_list(value: str | list[float] | None) -> list[float]:
        if value is None:
            return []
        if isinstance(value, str):
            items = [item.strip() for item in value.split(",") if item.strip()]
            floats: list[float] = []
            for item in items:
                try:
                    floats.append(float(item))
                except ValueError:
                    continue
            return floats
        floats = []
        for item in value:
            try:
                floats.append(float(item))
            except (TypeError, ValueError):
                continue
        return floats

    @field_validator("SECRET_KEY_FALLBACKS", "REFRESH_SECRET_KEY_FALLBACKS", mode="before")
    @classmethod
    def validate_fallbacks(cls, value: str | list[str] | None) -> list[str]:
        return cls._split_list(value)

    @field_validator("METRICS_LATENCY_BUCKETS", mode="before")
    @classmethod
    def validate_metric_buckets(cls, value: str | list[float] | None) -> list[float]:
        floats = cls._split_float_list(value)
        # Asegúrate que default_factory exista o proporciona un valor predeterminado directamente
        default_buckets = [0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
        return floats or default_buckets

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, value: str) -> str:
        if not value or value.lower() == "changeme":
            raise ValueError("SECRET_KEY must be set to a non-default, secure value.")
        return value

    @field_validator("MAX_REQUEST_SIZE_BYTES")
    @classmethod
    def validate_request_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_REQUEST_SIZE_BYTES must be positive.")
        return value

    @model_validator(mode="after")
    def validate_payment_test_boundary(self) -> "Settings":
        url = self.MERCADO_PAGO_API_BASE_URL.rstrip("/")
        if url != "https://api.mercadopago.com":
            parsed = urlsplit(url)
            if (
                self.APP_ENV.lower() not in {"test", "testing"}
                or parsed.scheme != "http"
                or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("MERCADO_PAGO_API_BASE_URL override requires test mode and a loopback HTTP origin.")
        self.MERCADO_PAGO_API_BASE_URL = url
        return self

    @model_validator(mode="after")
    def ensure_async_database_url(self) -> "Settings":
        """Ensure an async URL is always available."""
        if self.APP_ENV.lower() not in {"development", "dev", "test", "testing", "production", "prod"}:
            raise ValueError("APP_ENV must be development, test, or production.")
        if not self.ASYNC_DATABASE_URL:
            self.ASYNC_DATABASE_URL = self._derive_async_url(self.DATABASE_URL)
        # Valida que la URL asíncrona no sea None después de derivarla
        if not self.ASYNC_DATABASE_URL:
             raise ValueError(f"Could not derive async database URL from: {self.DATABASE_URL}")
        if self.APP_ENV.lower() in {"production", "prod"}:
            if len(self.SECRET_KEY) < 32 or "local-only" in self.SECRET_KEY.lower():
                raise ValueError("SECRET_KEY must contain at least 32 characters in production.")
            if not self.REFRESH_SECRET_KEY or "local-only" in self.REFRESH_SECRET_KEY.lower():
                raise ValueError("REFRESH_SECRET_KEY must be configured in production.")
            if len(self.REFRESH_SECRET_KEY) < 32:
                raise ValueError("REFRESH_SECRET_KEY must contain at least 32 characters in production.")
            if self.SECRET_KEY == self.REFRESH_SECRET_KEY:
                raise ValueError("Production SECRET_KEY and REFRESH_SECRET_KEY must be different.")
            database_url = self.DATABASE_URL.lower()
            if "user:password@" in database_url or "app:app@" in database_url:
                raise ValueError("DATABASE_URL must not use the example credentials in production.")
        return self

    # Validador para admin inicial
    @model_validator(mode="after")
    def check_initial_admin_config(self) -> "Settings":
        # Asegúrate que este validador se ejecute después de ensure_async_database_url
        # Pydantic v2 ejecuta validadores en el orden definido
        if self.INITIAL_ADMIN_EMAIL and not self.INITIAL_ADMIN_PASSWORD:
            raise ValueError("INITIAL_ADMIN_PASSWORD must be set if INITIAL_ADMIN_EMAIL is set.")
        if not self.INITIAL_ADMIN_EMAIL and self.INITIAL_ADMIN_PASSWORD:
            warnings.warn("INITIAL_ADMIN_PASSWORD is set but INITIAL_ADMIN_EMAIL is not; initial admin will not be created.")
        return self


    @staticmethod
    def _derive_async_url(url: str | None) -> str | None: # Permitir None como entrada y salida
        """Best-effort conversion from sync to async driver."""
        if not url: # Añadir chequeo por si DATABASE_URL no está definida
             return None
        if "+asyncpg" in url or "+aiosqlite" in url:
            return url
        if url.startswith("sqlite"):
            # Ensure compatibility with aiosqlite if DATABASE_URL is just sqlite:///path
            if url.startswith("sqlite:///"):
                return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
            # Asegura que solo reemplace una vez al principio
            if url.startswith("sqlite:"):
                 return url.replace("sqlite:", "sqlite+aiosqlite:", 1)
            return url # Devuelve url original si no coincide con los patrones esperados
        if "://" not in url:
            # Podría ser una URL inválida o un DSN, devolverla tal cual o None/Error
            return url # O considera lanzar un error si esperas siempre un formato URL

        scheme, rest = url.split("://", 1)
        if scheme.startswith("postgres"):
            base = "postgresql"
            driver = None
            if "+" in scheme:
                base_part, driver_part = scheme.split("+", 1)
                # Asegura que base sea postgresql incluso si viene como postgres+driver
                base = "postgresql" # if base_part.startswith("postgres") else base_part (simplificado)
                driver = driver_part
            # Simplificado: si no es asyncpg, intenta usar asyncpg
            if driver != "asyncpg":
                async_scheme = f"{base}+asyncpg"
            else:
                 async_scheme = scheme # Ya tiene asyncpg

            return f"{async_scheme}://{rest}"

        # Devuelve url original si no es sqlite o postgres
        return url

    @property
    def refresh_secret_fallback(self) -> str:
        """Return the refresh secret or fallback to the main secret."""
        # Asegúrate que SECRET_KEY siempre tenga un valor (ya validado)
        return self.REFRESH_SECRET_KEY or self.SECRET_KEY


settings = Settings()

# Validar explícitamente después de la inicialización si hay problemas
# try:
#     settings = Settings()
# except ValidationError as e:
#     print(f"Error loading settings: {e}")
#     import sys
#     sys.exit(1)
