# app/core/database.py
"""
Database connection and session management.
PRESERVED: SQLite support with UUID handling and foreign key enforcement.
ADDED: PostgreSQL support for future migration.
"""
from sqlmodel import create_engine, SQLModel, Session, inspect
from sqlalchemy import event, text
from uuid import UUID
import sqlite3
from app.models import user, activity_log, result, staff, academic, student, enrollment, finance # Ensure models are imported
from app.core.config import settings

# Create engine based on DATABASE_URL from settings
engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,  # Log SQL queries in debug mode
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

# Track if UUID listener is attached (prevents duplicate listeners)
_is_sqlite_uuid_listener_attached = False


def setup_sqlite_uuid_support(db_engine):
    """
    Adds listener to handle UUIDs and enforce FK constraints in SQLite.
    PRESERVED: Exact same UUID handling as original implementation.
    """
    global _is_sqlite_uuid_listener_attached
    
    if db_engine.dialect.name == "sqlite" and not _is_sqlite_uuid_listener_attached:
        @event.listens_for(db_engine, "connect")
        def on_connect(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.close()
            sqlite3.register_adapter(UUID, str)
        
        _is_sqlite_uuid_listener_attached = True


# Initialize UUID support if using SQLite
setup_sqlite_uuid_support(engine)


def create_db_and_tables():
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        print("⚠️ Tables already exist, skipping create_all")
        return

    SQLModel.metadata.create_all(engine)
    print("✅ Tables created")


def drop_db():
    """
    Drop all database tables.
    PRESERVED: Exact same functionality as original.
    """
    SQLModel.metadata.drop_all(engine)
    print("🗑️ All tables dropped successfully!")


def get_session():
    """
    Provide a database session.
    PRESERVED: Exact same session management as original.
    
    Yields:
        Session: SQLModel database session
    """
    with Session(engine) as session:
        yield session


def clear_all_tables():
    """
    Delete all data from every table in the SQLite database.
    PRESERVED: Exact same functionality as original.
    """
    with engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys = OFF;"))
        
        result = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        )
        tables = [row[0] for row in result.fetchall()]
        
        for table in tables:
            connection.execute(text(f"DELETE FROM {table};"))
            print(f"Cleared table: {table}")
        
        connection.execute(text("PRAGMA foreign_keys = ON;"))
        connection.commit()
    
    print("✅ All tables cleared successfully!")


# For PostgreSQL migration (future use)
def get_async_engine():
    """
    Create async engine for PostgreSQL.
    To be used when migrating to PostgreSQL with async operations.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    
    postgres_url = settings.get_postgres_url()
    if postgres_url:
        # Convert to async URL
        async_url = postgres_url.replace("postgresql://", "postgresql+asyncpg://")
        return create_async_engine(async_url, echo=settings.DEBUG)
    
    raise ValueError("PostgreSQL credentials not configured")


# Optional: CLI commands for database management
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "create":
            print("Creating database tables...")
            create_db_and_tables()
        
        elif command == "drop":
            confirm = input("Are you sure you want to drop all tables? (yes/no): ")
            if confirm.lower() == "yes":
                drop_db()
            else:
                print("Operation cancelled")
        
        elif command == "clear":
            confirm = input("Are you sure you want to clear all data? (yes/no): ")
            if confirm.lower() == "yes":
                clear_all_tables()
            else:
                print("Operation cancelled")
        
        elif command == "rebuild":
            confirm = input("Rebuild database (drop and recreate)? (yes/no): ")
            if confirm.lower() == "yes":
                drop_db()
                create_db_and_tables()
            else:
                print("Operation cancelled")
        
        else:
            print(f"Unknown command: {command}")
            print("Available commands: create, drop, clear, rebuild")
    else:
        print("Usage: python -m app.core.database [create|drop|clear|rebuild]")