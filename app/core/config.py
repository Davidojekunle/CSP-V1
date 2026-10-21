# app/core/config.py
"""
Centralized configuration management.
All settings come from environment variables (or a local .env file).
"""
from functools import lru_cache
from typing import List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_async_database_url(url: str) -> str:
    """
    Accepts the connection strings Supabase/Heroku/etc. hand out
    (postgres://, postgresql://, postgresql+psycopg2://) and returns the
    asyncpg form the app needs. libpq-only query params (sslmode, ...) are
    dropped because asyncpg does not understand them; SSL is configured via DB_SSL.
    """
    if url.startswith("sqlite"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1) if "+aiosqlite" not in url else url
    for prefix in ("postgres://", "postgresql://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in {"sslmode", "ssl", "pgbouncer", "connect_timeout"}]
    return urlunsplit(parts._replace(query=urlencode(query)))


def to_sync_database_url(url: str) -> str:
    """Sync (psycopg 3) variant of a database URL, for scripts."""
    url = normalize_async_database_url(url)
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1).replace("sqlite+aiosqlite://", "sqlite://", 1)


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    APP_NAME: str = "School Management System API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "production"
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database - discrete PostgreSQL settings (used by docker-compose)
    POSTGRES_USER: Optional[str] = None
    POSTGRES_PASSWORD: Optional[str] = None
    POSTGRES_HOST: Optional[str] = None
    POSTGRES_PORT: Optional[str] = None
    POSTGRES_DB: Optional[str] = None

    # Database URL used by the running app. For Supabase use the pooler
    # connection string (Project Settings -> Database -> Connection string).
    DATABASE_URL: str = "sqlite+aiosqlite:///school_management.db"
    # Optional separate URL for Alembic migrations / data import (Supabase
    # "direct" or "session pooler" string). Falls back to DATABASE_URL.
    MIGRATION_DATABASE_URL: Optional[str] = None

    # Connection pool (per app process). Keep pool_size * workers below your
    # Supabase plan's connection limit.
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    # "require", "disable", or unset (auto: require for Supabase hosts)
    DB_SSL: Optional[str] = None
    # True when connecting through a transaction-mode pooler (Supabase port
    # 6543 / PgBouncer). Auto-detected from the port when unset.
    DB_TRANSACTION_POOLER: Optional[bool] = None

    # Startup behaviour. In production the schema is managed by Alembic and
    # no demo accounts are created.
    AUTO_CREATE_TABLES: Optional[bool] = None
    SEED_SAMPLE_DATA: Optional[bool] = None

    # SQLite legacy path
    SQLITE_DB_PATH: str = "school_management.db"

    # JWT Authentication (CRITICAL - preserve exact behavior)
    SECRET_KEY: str  # Required
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 60 * 24 = 1 day (matches original)

    # CORS Settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://172.20.10.3:5173",
        "https://school-dashboard-pink.vercel.app"
    ]
    CORS_CREDENTIALS: bool = True
    CORS_METHODS: List[str] = ["*"]
    CORS_HEADERS: List[str] = ["*"]

    # Frontend base URL, used to build links in emails (password reset)
    FRONTEND_URL: str = "https://school-dashboard-pink.vercel.app"

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            if v.strip() == "*":
                return ["*"]
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    # Email Configuration (FastAPI-Mail)
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False
    EMAIL_ENABLED: bool = False

    # File Upload & Storage
    # Cloudinary Integration (for image uploads)
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # PDF Generation
    PDF_TEMPLATE_DIR: str = "templates/pdf"
    PDF_OUTPUT_DIR: str = "outputs/pdf"
    PDF_LOGO_PATH: str = "school_logo.png"

    # Paystack Integration
    PAYSTACK_SECRET_KEY: Optional[str] = None
    PAYSTACK_PUBLIC_KEY: Optional[str] = None
    PAYSTACK_CALLBACK_URL: Optional[str] = None

    # Activity Logging
    ACTIVITY_LOG_ENABLED: bool = True

    # Security
    ALLOWED_HOSTS: List[str] = ["*"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @field_validator("DATABASE_URL", "MIGRATION_DATABASE_URL", mode="before")
    @classmethod
    def strip_url(cls, v):
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def apply_environment_defaults(self):
        if self.AUTO_CREATE_TABLES is None:
            self.AUTO_CREATE_TABLES = not self.is_production
        if self.SEED_SAMPLE_DATA is None:
            self.SEED_SAMPLE_DATA = self.is_development
        return self

    # --- Database helpers ---
    @property
    def async_database_url(self) -> str:
        return normalize_async_database_url(self.DATABASE_URL)

    @property
    def migration_database_url(self) -> str:
        return normalize_async_database_url(self.MIGRATION_DATABASE_URL or self.DATABASE_URL)

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    def db_ssl_required(self, url: Optional[str] = None) -> bool:
        url = url or self.DATABASE_URL
        if self.DB_SSL is not None:
            return self.DB_SSL.lower() not in ("disable", "false", "0", "off")
        host = urlsplit(normalize_async_database_url(url)).hostname or ""
        return host.endswith(("supabase.co", "supabase.com")) or "sslmode=require" in url

    def uses_transaction_pooler(self, url: Optional[str] = None) -> bool:
        if self.DB_TRANSACTION_POOLER is not None:
            return self.DB_TRANSACTION_POOLER
        return urlsplit(normalize_async_database_url(url or self.DATABASE_URL)).port == 6543

    def get_database_url(self) -> str:
        """Get database URL."""
        return self.async_database_url

    def get_postgres_url(self) -> Optional[str]:
        """Construct PostgreSQL URL if credentials provided."""
        if all([
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
            self.POSTGRES_HOST,
            self.POSTGRES_PORT,
            self.POSTGRES_DB
        ]):
            return (
                f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
            )
        return None

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT.lower() in ("development", "dev", "local")


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached settings instance.
    Uses lru_cache to ensure settings are loaded only once.
    """
    return Settings()


# Global settings instance
settings = get_settings()
