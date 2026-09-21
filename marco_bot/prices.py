"""Live indicative USD prices for volatile deposit coins (free public API).

Used for two things:
- A \"send ~= X COIN\" hint on the deposit address screen (users no longer
  have to convert mentally when selling volatile coins).
- A live USD estimate stamped onto every auto-verification result, so the
  admin instantly sees whether the on-chain amount matches the deal.

Prices come from CoinGecko's free `/simple/price` endpoint and are cached
for two minutes, so even a busy queue costs almost no API calls. Any fetch
failure simply yields ``None`` and both features quietly degrade — nothing
ever blocks on a price.
"""
from __future__ import annotations

import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

FETCH_TIMEOUT = 8
CACHE_TTL_SECONDS = 120
COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"

# Deposit coins whose value is *not* USD-pegged. BNB is included because
# ETH-family deposits land on BSC where the native coin is BNB.
COIN_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "BNB": "binancecoin",
    "SOL": "solana",
    "TON": "the-open-network",
    "LTC": "litecoin",
}
VOLATILE_COINS = frozenset(COIN_IDS)

_price_cache: dict[str, tuple[float, Decimal]] = {}


def volatile(coin: str) -> bool:
    return (coin or "").strip().upper() in VOLATILE_COINS


async def usd_price(coin: str, fetch: Callable[..., Any] | None = None) -> Decimal | None:
    """Indicative USD price of a volatile coin (two-minute cache)."""
    label = (coin or "").strip().upper()
    gecko_id = COIN_IDS.get(label)
    if not gecko_id:
        return None
    cached = _price_cache.get(label)
    now = time.monotonic()
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    if fetch is None:

        async def fetch(url, params=None, headers=None, json_body=None):
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=dict(params or {}), timeout=FETCH_TIMEOUT) as response:
                    response.raise_for_status()
                    return await response.json(content_type=None)

    try:
        payload = await fetch(
            COINGECKO_SIMPLE_PRICE,
            {"ids": gecko_id, "vs_currencies": "usd"},
            None,
            None,
        )
    except Exception:  # noqa: BLE001 — price hints must never break flows
        return None
    try:
        price = Decimal(str(payload[gecko_id]["usd"]))
    except (KeyError, TypeError, InvalidOperation):
        return None
    if price <= 0:
        return None
    _price_cache[label] = (now, price)
    return price


async def usd_hint(coin: str, amount: Decimal | None, fetch: Callable[..., Any] | None = None) -> str | None:
    """e.g. '~$499.21' for a crypto amount, or None when no price is known."""
    if amount is None or amount <= 0:
        return None
    price = await usd_price(coin, fetch)
    if price is None:
        return None
    return f"~${(amount * price):,.2f}"


async def crypto_hint(token: str, usd_amount: Decimal | None, fetch: Callable[..., Any] | None = None) -> str | None:
    """e.g. '≈ 0.0048 BTC (≈ $500.00)' — the deposit-screen helper.

    Note: an ETH deposit on BSC is actually paid in BNB, so the hint swaps
    the coin label to keep users from sending literal ETH to a BSC address.
    """
    if usd_amount is None or usd_amount <= 0:
        return None
    coin = token.upper()
    if coin not in VOLATILE_COINS:
        return None
    price = await usd_price(coin, fetch)
    if price is None:
        return None
    qty = usd_amount / price
    return f"≈ {qty:.6f} {coin} (~${usd_amount:,.2f})"


def clear_cache() -> None:
    _price_cache.clear()
