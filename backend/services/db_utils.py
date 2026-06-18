"""
Shared database utilities — connection URL conversion, session factory creation.

All modules that need a PostgreSQL async connection should use these helpers
rather than inlining the regex conversion or creating ad-hoc engines.
"""

import os
import re
import structlog

logger = structlog.get_logger()

_ASYNC_ENGINE = None
_ASYNC_SESSION_FACTORY = None


def ensure_asyncpg_url(db_url: str | None = None) -> str:
    """Convert a sync PostgreSQL URL to asyncpg format if needed.

    postgresql://user:pass@host/db → postgresql+asyncpg://user:pass@host/db
    postgres://user:pass@host/db    → postgresql+asyncpg://user:pass@host/db
    Already-asyncpg URLs are returned unchanged (no double-conversion).
    """
    url = db_url or os.getenv("DATABASE_URL", "")
    if not url:
        raise ValueError("DATABASE_URL is not configured")
    if "asyncpg" in url:
        return url  # already async-compatible
    return re.sub(r'^postgres(ql)?://', 'postgresql+asyncpg://', url)


def get_async_session_factory():
    """Return a shared async session factory (singleton engine + sessionmaker).

    Callers should NOT dispose the engine — it is managed at process lifetime.
    """
    global _ASYNC_ENGINE, _ASYNC_SESSION_FACTORY
    if _ASYNC_SESSION_FACTORY is None:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker

        db_url = ensure_asyncpg_url()
        _ASYNC_ENGINE = create_async_engine(db_url, echo=False)
        _ASYNC_SESSION_FACTORY = sessionmaker(
            _ASYNC_ENGINE, class_=AsyncSession, expire_on_commit=False,
        )
        logger.info("db_engine_created", url=db_url.split("@")[-1])  # log host part only
    return _ASYNC_SESSION_FACTORY


async def dispose_engine():
    """Explicitly dispose the shared engine (for graceful shutdown)."""
    global _ASYNC_ENGINE, _ASYNC_SESSION_FACTORY
    if _ASYNC_ENGINE is not None:
        await _ASYNC_ENGINE.dispose()
        _ASYNC_ENGINE = None
        _ASYNC_SESSION_FACTORY = None
        logger.info("db_engine_disposed")
