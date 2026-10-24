"""Async database access (SQLAlchemy 2 + asyncpg) and the usage logger."""

import logging

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.models import UsageLog

logger = logging.getLogger(__name__)


def create_engine(database_url: str) -> AsyncEngine:
    # pool_pre_ping checks a pooled connection before using it, so a Postgres restart does not
    # make the next request fail with a dead connection.
    return create_async_engine(database_url, pool_pre_ping=True)


class UsageLogger:
    def __init__(self, engine: AsyncEngine) -> None:
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def log(self, entry: UsageLog) -> None:
        """Insert one usage row. A logging failure never fails the user's request."""
        try:
            async with self.sessions() as session, session.begin():
                session.add(entry)
        except Exception:
            # Only the team and status are logged here, never the entry's content fields.
            logger.exception(
                "could not write usage log (team=%s, status=%s)", entry.team, entry.status_code
            )
