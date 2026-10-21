# app/core/database.py
"""
Async database engine and session management.

Works with:
- PostgreSQL / Supabase via asyncpg (production)
- SQLite via aiosqlite (local development and tests)
"""
import logging
from typing import AsyncGenerator
from uuid import uuid4

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.core.config import settings

logger = logging.getLogger(__name__)


def engine_options(url: str, *, pooled: bool = True) -> dict:
    """create_async_engine() keyword arguments appropriate for the given URL."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}

    connect_args = {
        "server_settings": {"application_name": settings.APP_NAME[:60]},
        "command_timeout": 60,
    }
    if settings.db_ssl_required(url):
        connect_args["ssl"] = "require"
    if settings.uses_transaction_pooler(url):
        # Transaction-mode poolers (Supabase :6543, PgBouncer) can hand each
        # transaction a different server connection, so asyncpg must not reuse
        # named prepared statements.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"

    options = {"connect_args": connect_args, "pool_pre_ping": True}
    if pooled:
        options.update(
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=settings.DB_MAX_OVERFLOW,
            pool_timeout=settings.DB_POOL_TIMEOUT,
            pool_recycle=settings.DB_POOL_RECYCLE,
        )
    return options


def _with_pooler_params(url: str) -> str:
    # The asyncpg dialect's own prepared statement cache is configured via the URL
    if url.startswith("postgresql") and settings.uses_transaction_pooler(url) and "prepared_statement_cache_size" not in url:
        return url + ("&" if "?" in url else "?") + "prepared_statement_cache_size=0"
    return url


def _enable_sqlite_foreign_keys(engine: AsyncEngine):
    @event.listens_for(engine.sync_engine, "connect")
    def on_connect(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.close()


def create_engine_for(url: str, *, pooled: bool = True) -> AsyncEngine:
    engine = create_async_engine(_with_pooler_params(url), echo=settings.DEBUG, **engine_options(url, pooled=pooled))
    if url.startswith("sqlite"):
        _enable_sqlite_foreign_keys(engine)
    return engine


async_engine = create_engine_for(settings.async_database_url)

# expire_on_commit=False: objects stay usable after commit inside a request
AsyncSessionFactory = async_sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an asynchronous database session
    for each request and ensures it's closed afterward.
    """
    async with AsyncSessionFactory() as session:
        yield session


async def create_db_and_tables():
    """
    Creates any missing tables. Only used for local development/tests;
    production schemas are managed by Alembic (`alembic upgrade head`).
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    logger.info("Database tables checked/created")


async def check_database_connection() -> bool:
    from sqlalchemy import text
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("Database connectivity check failed")
        return False
