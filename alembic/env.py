"""Alembic migration environment (async, because the app uses the asyncpg driver)."""

import asyncio
from logging.config import fileConfig

from sqlalchemy import text
from sqlalchemy.engine import Connection

from alembic import context
from app.config import get_settings
from app.db import create_engine
from app.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


# Arbitrary constant identifying "the Relay migration lock".
MIGRATION_LOCK_ID = 727_274


def run_migrations(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        # In Kubernetes every pod runs migrations at startup (initContainer). This session-level
        # advisory lock makes concurrent pods take turns: the first one migrates, the others
        # wait, then find the schema already at "head" and do nothing.
        connection.execute(text(f"SELECT pg_advisory_lock({MIGRATION_LOCK_ID})"))
        # Executing the statement opened a transaction; commit it so that Alembic opens (and
        # commits) its own. The lock is held by the session, so it survives this commit and is
        # released when the connection closes.
        connection.commit()
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(run_async_migrations())
