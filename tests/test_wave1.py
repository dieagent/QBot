"""Wave 1: USDC, live price hints/estimates, priority lane, dual approval,
channel marketing copy, and real maintenance mode."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from marco_bot import chainverify as cv, messages as msg, prices
from marco_bot import keyboards as kb
from marco_bot import serverless
from marco_bot.bootcheck import DEPOSIT_COMBOS
from marco_bot.config import _decimal_env, _optional_decimal_env
from marco_bot.handlers import admin as admin_srv
from marco_bot.review import admin_review_text, priority_banner
from test_services import settings_for_test

SETTINGS = settings_for_test()


def run(coro):
    return asyncio.run(coro)


def make_fetch(responder):
    async def fetch(url, params=None, headers=None, json_body=None):
        return responder(url, dict(params or {}), json_body)

    return fetch


# ---------------------------------------------------------------------------
# prices.py
# ---------------------------------------------------------------------------


def test_usd_price_fetch_and_cache() -> None:
    prices.clear_cache()
    calls = []

    async def fetch(url, params=None, headers=None, json_body=None):
        calls.append(url)
        return {"bitcoin": {"usd": 102345}}

    assert run(prices.usd_price("BTC", fetch)) == Decimal("102345")
    assert run(prices.usd_price("BTC", fetch)) == Decimal("102345")
    assert len(calls) == 1  # cached within TTL


def test_usd_price_failure_and_unknown_coin() -> None:
    prices.clear_cache()

    async def broken(url, params=None, headers=None, json_body=None):
        raise RuntimeError("offline")

    assert run(prices.usd_price("BTC", broken)) is None
    assert run(prices.usd_price("USDT", broken)) is None  # not a volatile coin


def test_hints_format_and_stable_skip() -> None:
    prices.clear_cache()

    async def fetch(url, params=None, headers=None, json_body=None):
        return {"bitcoin": {"usd": 50000}}

    assert run(prices.crypto_hint("BTC", Decimal("250"), fetch)) == "≈ 0.005000 BTC (~$250.00)"
    assert run(prices.crypto_hint("USDT", Decimal("250"), fetch)) is None
    assert run(prices.usd_hint("BTC", Decimal("2"), fetch)) == "~$100,000.00"


def test_verified_volatile_gets_live_estimate() -> None:
    prices.clear_cache()

    def respond(url, params, json_body):
        if "coingecko" in url:
            return {"litecoin": {"usd": 100}}
        if url.endswith("/blocks/tip/height"):
            return 2900100
        return {"txid": "x" * 64, "status": {"confirmed": True, "block_height": 2900090},
                "vout": [{"scriptpubkey_address": "deposit", "value": 100_000_000}]}

    result = run(cv.verify_payment(SETTINGS, "LTC", "LTC", "deposit", 0, "x" * 64, fetch=make_fetch(respond)))
    assert result.status == cv.STATUS_VERIFIED
    assert "~$100.00 at current price" in result.detail


# ---------------------------------------------------------------------------
# USDC on EVM rails
# ---------------------------------------------------------------------------


def test_usdc_offered_everywhere_expected() -> None:
    texts = [b.text for row in kb.token_select().inline_keyboard for b in row]
    assert "USDC" in texts
    chains = [b.text for row in kb.express_chains("USDC").inline_keyboard for b in row]
    assert {"ERC20", "BEP20", "MATIC", "BASE"} <= set(chains)
    assert ("USDC", "ERC20") in DEPOSIT_COMBOS and ("USDC", "BASE") in DEPOSIT_COMBOS


def test_usdc_auto_verifies_as_stablecoin() -> None:
    supported, reason = cv.support_status(SETTINGS, "USDC", "ERC20", "0xabc")
    assert supported, reason
    supported, _ = cv.support_status(SETTINGS, "USDC", "TRC20", "Txxx")
    assert not supported  # USDC has no TRC20 registry entry


# ---------------------------------------------------------------------------
# Deposit screen hint + priority banner
# ---------------------------------------------------------------------------


def test_deposit_instructions_appends_hint() -> None:
    base = msg.deposit_instructions("BTC", "BTC", "bc1xxx")
    hinted = msg.deposit_instructions("BTC", "BTC", "bc1xxx", crypto_hint="≈ 0.005000 BTC (~$250.00)")
    assert hinted.startswith(base)
    assert "0.005000 BTC" in hinted


def test_priority_banner_threshold() -> None:
    settings = settings_for_test(priority_usd=Decimal("1000"))
    big = SimpleNamespace(amount_usd=Decimal("1500"))
    small = SimpleNamespace(amount_usd=Decimal("999"))
    assert priority_banner(settings, big).startswith("🔥🔥 PRIORITY DEAL")
    assert priority_banner(settings, small) == ""
    stars = settings_for_test(priority_usd=Decimal("50"))
    assert priority_banner(stars, small)  # 999 >= 50 => banner


def test_admin_review_text_prefixes_priority() -> None:
    settings = settings_for_test(priority_usd=Decimal("1000"))
    user = SimpleNamespace(username="syed", user_id=7)
    tx = SimpleNamespace(
        tx_id=88, type="express_sell", user_id=7, coin="BTC", chain="BTC",
        amount_usd=Decimal("1200"), amount_inr=Decimal("112800"), payment_mode="UPI",
        deposit_address="bc1xxx", proof_file_id=None, verify_status=None,
        verify_detail=None, tx_hash=None, verify_expected=None, chain_tx_hash=None,
        verify_confirmations=None,
    )
    assert admin_review_text(user, tx, settings).startswith("🔥🔥 PRIORITY DEAL — $1200.00")
    assert "Pending Verification" in admin_review_text(user, tx, settings)


# ---------------------------------------------------------------------------
# Maintenance mode state machine
# ---------------------------------------------------------------------------


def test_maintenance_block_states() -> None:
    now = datetime(2026, 9, 21, 12, 0, 0)
    assert admin_srv.maintenance_block({}, now) is None
    assert admin_srv.maintenance_block({"maintenance": "junk"}, now) is None
    off = json.dumps({"on": False})
    assert admin_srv.maintenance_block({"maintenance": off}, now) is None
    future = (now + timedelta(minutes=30)).isoformat()
    on = json.dumps({"on": True, "until": future, "note": "bank slow"})
    text = admin_srv.maintenance_block({"maintenance": on}, now)
    assert "maintenance" in text and "bank slow" in text
    past = (now - timedelta(minutes=1)).isoformat()
    assert admin_srv.maintenance_block({"maintenance": json.dumps({"on": True, "until": past})}, now) is None


# ---------------------------------------------------------------------------
# Channel marketing copy
# ---------------------------------------------------------------------------


def test_trust_feed_text_rules() -> None:
    assert serverless.trust_feed_text(0, 0, None) is None
    one = serverless.trust_feed_text(1, 214.0, 4.9)
    assert "1 deal" in one and "$214.00" in one and "4.9/5" in one
    many = serverless.trust_feed_text(7, 1532.5, None)
    assert "7 deals" in many and "⭐" not in many  # no rating line when unknown


def test_rates_broadcast_text_rules() -> None:
    assert serverless.rates_broadcast_text([]) is None
    tiers = [("UPI", 10, 600, Decimal("96.5")), ("UPI", 601, None, Decimal("97.0")), ("CDM", 10, None, Decimal("95"))]
    text = serverless.rates_broadcast_text(tiers)
    assert "UPI: 96.50–97.00 ₹/$" in text
    assert "CDM: 95.00 ₹/$" in text


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------


def test_priority_and_dual_approval_env(monkeypatch) -> None:
    monkeypatch.setenv("PRIORITY_USD", "2500")
    monkeypatch.setenv("DUAL_APPROVAL_USD", "5000")
    assert _decimal_env("PRIORITY_USD", Decimal("1000")) == Decimal("2500")
    assert _optional_decimal_env("DUAL_APPROVAL_USD") == Decimal("5000")
    monkeypatch.setenv("DUAL_APPROVAL_USD", "nonsense")
    assert _optional_decimal_env("DUAL_APPROVAL_USD") is None
    monkeypatch.setenv("PRIORITY_USD", "-5")
    assert _decimal_env("PRIORITY_USD", Decimal("1000")) == Decimal("1000")
    defaults = settings_for_test()
    assert defaults.priority_usd == Decimal("1000")
    assert defaults.dual_approval_usd is None
