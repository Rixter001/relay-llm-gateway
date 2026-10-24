"""Database tables (SQLAlchemy 2 declarative mapping).

The usage log deliberately has NO column for prompt or completion text: the safest way to
guarantee content is never logged is to have nowhere to put it.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UsageLog(Base):
    __tablename__ = "usage_log"

    # BIGINT in Postgres; SQLite (used in tests) only auto-increments INTEGER primary keys.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    team: Mapped[str] = mapped_column(String(100), index=True)
    # HTTP status returned to the caller: 200, 402 (budget), 429 (rate limit), 502 (providers)...
    status_code: Mapped[int] = mapped_column(Integer)
    policy: Mapped[str | None] = mapped_column(String(20))
    # Provider and model that produced the answer (empty when no provider succeeded).
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    # End-to-end time spent in Relay (masking + provider call(s) + unmasking).
    latency_ms: Mapped[int] = mapped_column(Integer)
    fallback_used: Mapped[bool] = mapped_column(default=False)
    masked_entities: Mapped[int] = mapped_column(Integer, default=0)
    # Short machine-generated reason ("ollama: timeout"), never request content.
    error: Mapped[str | None] = mapped_column(String(300))
