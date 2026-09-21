"""Wave 3: promo codes, admin notes, loyalty levels, referral digest."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from marco_bot import services as svc
from marco_bot.serverless import referral_digest_line

NOW = datetime(2026, 9, 21, 15, 0, 0)


# ---------------------------------------------------------------------------
# Loyalty levels
# ---------------------------------------------------------------------------


def test_loyalty_level_ladder() -> None:
    assert svc.loyalty_level(0)[0] == 0                    # 🌱 Rookie
    assert svc.loyalty_level(150)[1] == "Bronze"
    assert svc.loyalty_level(600)[1] == "Silver"
    assert svc.loyalty_level(3000)[1] == "Gold"
    assert svc.loyalty_level(15000)[1] == "Diamond"
    assert svc.loyalty_level(999_999)[1] == "Legend"


def test_loyalty_referrals_boost_level() -> None:
    # 4 referrals = +200 effective volume -> Bronze while zero volume
    assert svc.loyalty_level(0, referrals=4)[1] == "Bronze"
    line = svc.loyalty_line(0, referrals=4)
    assert "Trader Level 1" in line and "Bronze" in line


def test_loyalty_line_max_level() -> None:
    assert "max level" in svc.loyalty_line(60_000)


# ---------------------------------------------------------------------------
# Promo codes
# ---------------------------------------------------------------------------


def test_new_promo_and_normalization() -> None:
    promo = json.loads(svc.new_promo(2.5, 10, 30, NOW))
    assert promo["amount"] == 2.5 and promo["cap"] == 10 and promo["used"] == 0
    assert promo["expires"].startswith("2026-10-21")
    assert svc.normalize_promo_code("  diwali24 ") == "DIWALI24"
    assert svc.normalize_promo_code("ab") is None  # too short


def test_redeem_promo_flow() -> None:
    state: dict = {svc.promo_key("DIWALI"): svc.new_promo(2.0, 2, None, NOW)}
    amount, reason = svc.redeem_promo(state, "DIWALI", user_id=11, now=NOW)
    assert amount == 2.0 and reason == ""
    # double-claim blocked for same user
    amount, reason = svc.redeem_promo(state, "diwali", user_id=11, now=NOW)
    assert amount is None and "already" in reason
    # second user ok
    amount, reason = svc.redeem_promo(state, "DIWALI", user_id=12, now=NOW)
    assert amount == 2.0
    # third user exceeds cap
    amount, reason = svc.redeem_promo(state, "DIWALI", user_id=13, now=NOW)
    assert amount is None and "fully claimed" in reason


def test_redeem_promo_expired_and_missing() -> None:
    state = {svc.promo_key("OLD"): svc.new_promo(1.0, None, 1, NOW - timedelta(days=2))}
    amount, reason = svc.redeem_promo(state, "OLD", 1, NOW)
    assert amount is None and "expired" in reason
    amount, reason = svc.redeem_promo({}, "GG", 1, NOW)
    assert amount is None and "exist" in reason


def test_list_promos_ignores_other_state() -> None:
    state = {
        svc.promo_key("A"): svc.new_promo(1.0, None, None, NOW),
        svc.promo_key("B"): svc.new_promo(2.0, 5, 7, NOW),
        "maintenance": "garbage",
        "feed_last_at": "iso",
    }
    codes = [c for c, _ in svc.list_promos(state)]
    assert codes == ["A", "B"]


# ---------------------------------------------------------------------------
# Admin notes
# ---------------------------------------------------------------------------


def test_admin_note_roundtrip() -> None:
    state = {svc.note_key(42): " asked for extra KYC "}
    assert svc.get_admin_note(state, 42) == "asked for extra KYC"
    assert svc.get_admin_note(state, 43) is None
    assert svc.get_admin_note({svc.note_key(42): "   "}, 42) is None


# ---------------------------------------------------------------------------
# Referral digest copy
# ---------------------------------------------------------------------------


def test_referral_digest_line() -> None:
    line = referral_digest_line(50, 4, 20)
    assert "50 invited" in line and "(4 in 24h)" in line and "20 converted (40%)" in line
    assert "0%" in referral_digest_line(0, 0, 0)
