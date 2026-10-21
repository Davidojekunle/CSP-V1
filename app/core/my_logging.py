# app/core/my_logging.py
"""Application-wide logging configuration (stdout, so container platforms collect it)."""
import logging
import sys

from app.core.config import settings


def setup_logging():
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.LOG_LEVEL.upper())
    # SQL echo is controlled by DEBUG via the engine; keep the rest of SQLAlchemy quiet
    logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO if settings.DEBUG else logging.WARNING)
