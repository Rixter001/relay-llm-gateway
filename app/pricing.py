"""Per-model token prices and cost calculation.

Prices are USD per million tokens, taken from the vendors' public pricing pages
(Anthropic: 2026-10; Google Gemini: check https://ai.google.dev/pricing before relying on them).
Edit this table when prices change. Money is computed with Decimal, never float, so that sums
of many small costs don't drift.
"""

from dataclasses import dataclass
from decimal import Decimal

MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class Price:
    input_per_mtok: Decimal
    output_per_mtok: Decimal

    @property
    def blended(self) -> Decimal:
        """Single number used to rank providers by cost (input + output price)."""
        return self.input_per_mtok + self.output_per_mtok


PRICES: dict[str, Price] = {
    "claude-opus-5-5": Price(Decimal("4.00"), Decimal("20.00")),
    "claude-sonnet-5-5": Price(Decimal("2.00"), Decimal("10.00")),
    "claude-haiku-5-5": Price(Decimal("0.10"), Decimal("0.50")),
    "gemini-2.5-flash": Price(Decimal("0.30"), Decimal("2.50")),
    "gemini-2.5-pro": Price(Decimal("1.25"), Decimal("10.00")),
}

FREE = Price(Decimal(0), Decimal(0))

# A cloud model missing from the table is priced like the most expensive known model.
# Over-estimating is the safe direction: a budget cap can then never be silently bypassed
# by configuring a model we forgot to price.
UNKNOWN_CLOUD_PRICE = max(PRICES.values(), key=lambda p: p.blended)


def price_for(model: str, is_local: bool) -> Price:
    if is_local:
        # Self-hosted models have no per-token bill (the hardware cost is not tracked here).
        return FREE
    return PRICES.get(model, UNKNOWN_CLOUD_PRICE)


def cost_usd(model: str, is_local: bool, prompt_tokens: int, completion_tokens: int) -> Decimal:
    price = price_for(model, is_local)
    return (
        prompt_tokens * price.input_per_mtok + completion_tokens * price.output_per_mtok
    ) / MILLION
