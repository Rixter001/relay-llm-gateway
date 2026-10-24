"""Per-team rate limit and monthly budget, enforced with Redis.

Why Redis: Relay runs as several replicas. A counter kept in each process's memory would let
a team send N x the limit (one limit per replica). Redis gives every replica the same counter,
and INCR/INCRBY are atomic, so two simultaneous requests can never both read "59" and both pass.

Failure mode: if Redis is unreachable we refuse the request (503), "fail closed". A gateway
that silently stops enforcing budgets when its datastore blips is a cost and compliance risk.
"""

import logging
import time
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.auth import Team

# Spend is stored as an integer number of micro-dollars: Redis INCRBY is atomic on integers,
# and integers do not accumulate floating-point rounding errors.
MICRO = Decimal(1_000_000)

logger = logging.getLogger(__name__)


def budget_key(team: str, now: datetime) -> str:
    return f"relay:budget:{team}:{now:%Y-%m}"


class Limiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def check_rate_limit(self, team: Team) -> None:
        """Fixed one-minute window: at most N requests per team per calendar minute.

        Simpler than a sliding window, at the price of allowing a burst of up to 2N requests
        around a minute boundary. Good enough to stop a runaway script.
        """
        now = int(time.time())
        window = now // 60
        key = f"relay:rate:{team.name}:{window}"
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                pipe.expire(key, 120)  # old windows clean themselves up
                count, _ = await pipe.execute()
        except RedisError as exc:
            raise HTTPException(503, "rate limiter unavailable") from exc
        if count > team.rate_limit_per_minute:
            retry_after = 60 - now % 60
            raise HTTPException(
                429,
                f"rate limit of {team.rate_limit_per_minute} requests/minute exceeded",
                headers={"Retry-After": str(retry_after)},
            )

    async def check_budget(self, team: Team) -> None:
        """Refuse the request if the team already spent its monthly budget.

        This is checked BEFORE the call (the cost of the call is unknown until the provider
        answers), so a team can overshoot by the cost of the requests already in flight.
        """
        if team.monthly_budget_usd is None:
            return
        spent = await self.spent_usd(team)
        if spent >= Decimal(str(team.monthly_budget_usd)):
            raise HTTPException(
                402, f"monthly budget of ${team.monthly_budget_usd:.2f} reached for {team.name}"
            )

    async def spent_usd(self, team: Team) -> Decimal:
        try:
            raw = await self.redis.get(budget_key(team.name, datetime.now(UTC)))
        except RedisError as exc:
            raise HTTPException(503, "budget store unavailable") from exc
        return Decimal(int(raw or 0)) / MICRO

    async def record_spend(self, team: Team, cost_usd: Decimal) -> None:
        """Add the cost of a successful call to the team's monthly total."""
        micro_usd = int((cost_usd * MICRO).to_integral_value(rounding="ROUND_CEILING"))
        if micro_usd <= 0:
            return
        key = budget_key(team.name, datetime.now(UTC))
        try:
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.incrby(key, micro_usd)
                pipe.expire(key, 60 * 60 * 24 * 40)  # keep a month's total ~40 days
                await pipe.execute()
        except RedisError:
            # The provider already answered (and billed us), so failing the request now would
            # not save money. Log loudly instead; the Postgres usage log still has the cost.
            logger.exception("could not record spend of %s USD for team %s", cost_usd, team.name)
