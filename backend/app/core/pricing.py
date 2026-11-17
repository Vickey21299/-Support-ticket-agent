"""Token prices for the cost-per-100-tickets figure (USD per 1M tokens).

Public list prices at the time of writing; check the provider's pricing page before quoting them.
Override with LLM_PRICE_IN_PER_M / LLM_PRICE_OUT_PER_M in .env.
"""
from typing import Optional

# model prefix -> (input, output) USD per 1M tokens
LIST_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-3.5-flash-lite": (0.30, 2.50),     # ai.google.dev/gemini-api/docs/pricing, standard tier, checked 2026-11-18
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
}
EUR_PER_USD = 0.92   # rough conversion for the README; check the current rate


def price_for(model: Optional[str], price_in: Optional[float] = None,
              price_out: Optional[float] = None) -> Optional[tuple[float, float]]:
    if price_in is not None and price_out is not None:
        return price_in, price_out
    if not model:
        return None
    for prefix in sorted(LIST_PRICES, key=len, reverse=True):     # longest prefix wins
        if model.startswith(prefix):
            return LIST_PRICES[prefix]
    return None


def cost_usd(tokens_in: int, tokens_out: int, prices: Optional[tuple[float, float]]) -> Optional[float]:
    if not prices:
        return None
    return tokens_in / 1e6 * prices[0] + tokens_out / 1e6 * prices[1]


def cost_per_100(tokens_in: int, tokens_out: int, n_tickets: int,
                 prices: Optional[tuple[float, float]]) -> Optional[dict]:
    """Scale measured tokens of n tickets to 100 tickets; returns the numbers used, for the README."""
    if not n_tickets or not prices:
        return None
    k = 100 / n_tickets
    usd = cost_usd(int(tokens_in * k), int(tokens_out * k), prices)
    return {
        "tickets_measured": n_tickets,
        "tokens_in_per_100": int(tokens_in * k),
        "tokens_out_per_100": int(tokens_out * k),
        "usd_per_1m_in": prices[0],
        "usd_per_1m_out": prices[1],
        "usd_per_100": round(usd, 4),
        "eur_per_100": round(usd * EUR_PER_USD, 4),
    }
