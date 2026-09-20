"""Tests for the trust/growth/ops feature pack:
referrals, badges, exact-credit, step tracker, tx list rendering,
Hindi fallbacks, and the admin reject-reason keyboard.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from marco_bot import keyboards as kb
from marco_bot import messages as msg
from marco_bot.messages import my_tx_render, steps_header
from marco_bot.models import Transaction, User
from marco_bot.services import BADGE_TIERS, badge_for, credit_amount_for, parse_referral_payload, referral_link
from marco_bot.translations import HI, lang_of, tr


def make_tx(**fields) -> Transaction:
    base = dict(
        tx_id=7,
        user_id=111,
        type="wallet_deposit",
        coin="USDT",
        chain="BEP20",
        amount_usd=Decimal("100.00"),
        amount_inr=Decimal("9000.00"),
        verified_amount=None,
        verify_status="verified",
        status="pending",
        chain_tx_hash=None,
        payout_reference=None,
    )
    base.update(fields)
    return Transaction(**base)


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------


def test_parse_referral_payload_extracts_referrer() -> None:
    assert parse_referral_payload("/start ref_42", 999) == 42


def test_parse_referral_payload_rejects_self_referral() -> None:
    assert parse_referral_payload("/start ref_42", 42) is None


@pytest.mark.parametrize("text", [None, "", "/start", "/start garbage", "/start ref_abc", "/start ref_"])
def test_parse_referral_payload_rejects_missing_or_malformed(text) -> None:
    assert parse_referral_payload(text, 999) is None


def test_referral_link_format() -> None:
    assert referral_link("@my_bot", 42) == "https://t.me/my_bot?start=ref_42"
    assert referral_link("my_bot", 42) == "https://t.me/my_bot?start=ref_42"


# ---------------------------------------------------------------------------
# Badges
# ---------------------------------------------------------------------------


def test_badges_tiers_are_descending_thresholds() -> None:
    assert badge_for(Decimal("0")) is None
    assert badge_for(Decimal("249.99")) is None
    assert badge_for(Decimal("250")) == "🥉 BRONZE"
    assert badge_for(Decimal("999.99")) == "🥉 BRONZE"
    assert badge_for(Decimal("1000")) == "🥈 SILVER"
    assert badge_for(Decimal("4999")) == "🥈 SILVER"
    assert badge_for(Decimal("5000")) == "🥇 GOLD"
    assert badge_for(Decimal("250000")) == "🥇 GOLD"


def test_badge_thresholds_monotonic() -> None:
    thresholds = [t for t, _ in BADGE_TIERS]
    assert thresholds == sorted(thresholds, reverse=True)


# ---------------------------------------------------------------------------
# Exact crediting
# ---------------------------------------------------------------------------


def test_credit_amount_credits_full_overpay_for_stablecoin_deposit() -> None:
    tx = make_tx(verified_amount=Decimal("120.50"))
    assert credit_amount_for(tx) == Decimal("120.50")


def test_credit_amount_falls_back_to_entered_amount_when_not_verified() -> None:
    tx = make_tx(verified_amount=None)
    assert credit_amount_for(tx) == Decimal("100.00")


def test_credit_amount_ignores_verified_for_non_stablecoin() -> None:
    tx = make_tx(coin="BTC", verified_amount=Decimal("0.005"))
    assert credit_amount_for(tx) == Decimal("100.00")


def test_credit_amount_ignores_verified_for_express_sell() -> None:
    tx = make_tx(type="express_sell", coin="USDT", verified_amount=Decimal("120.50"))
    assert credit_amount_for(tx) == Decimal("100.00")


# ---------------------------------------------------------------------------
# Step tracker
# ---------------------------------------------------------------------------


def test_steps_header_sell_flow_has_six_steps() -> None:
    header = steps_header(0)
    assert "Step 1/6" in header
    assert "▶" in header
    assert "✅" not in header


def test_steps_header_marks_completed_steps() -> None:
    header = steps_header(3)
    assert "Step 4/6" in header
    # steps before the current one are marked done
    assert header.count("✅") == 3


def test_steps_header_wallet_flow_has_five_steps() -> None:
    header = steps_header(4, wallet_flow=True)
    assert "Step 5/5" in header
    assert header.count("✅") == 4


def test_steps_header_final_step_marks_all_prior_done() -> None:
    header = steps_header(5)
    assert "Step 6/6" in header
    assert header.count("✅") == 5


# ---------------------------------------------------------------------------
# My Transactions rendering
# ---------------------------------------------------------------------------


def test_my_tx_render_empty_state() -> None:
    text = my_tx_render([], 0, 0)
    assert "No transactions yet" in text


def test_my_tx_render_shows_status_and_verify_icons() -> None:
    tx = make_tx(tx_id=3, status="pending", verify_status="verified", coin="USDT", chain="BEP20")
    text = my_tx_render([tx], 0, 1)
    assert "TX 3" in text
    assert "wallet deposit" in text
    assert "$100.00" in text
    assert "USDT/BEP20" in text
    assert "on-chain" in text


def test_my_tx_render_links_hash_to_explorer() -> None:
    tx = make_tx(chain_tx_hash="0xdeadbeef", chain="BEP20")
    text = my_tx_render([tx], 0, 1)
    assert "bscscan.com/tx/0xdeadbeef" in text

    no_chain = make_tx(chain_tx_hash="0xdeadbeef", chain=None)
    assert "href" not in my_tx_render([no_chain], 0, 1)


def test_my_tx_render_shows_payout_reference_when_approved() -> None:
    tx = make_tx(status="approved", payout_reference="831204912345")
    text = my_tx_render([tx], 0, 1)
    assert "payout ref" in text
    assert "831204912345" in text
    # payout ref hidden for non-approved transactions
    pending = make_tx(status="pending", payout_reference="831204912345")
    assert "payout ref" not in my_tx_render([pending], 0, 1)


def test_my_tx_render_hindi_title() -> None:
    text = my_tx_render([], 0, 0, lang="hi")
    assert "Transactions" in text  # Hindi title present (contains the word Transaction)


def test_my_tx_render_pagination_window() -> None:
    text = my_tx_render([make_tx()], 12, 40)
    assert "13-13 of 40" in text


# ---------------------------------------------------------------------------
# Hindi translations & fallback
# ---------------------------------------------------------------------------


def test_tr_returns_hindi_when_available() -> None:
    hindi = tr("TX_HASH_PROMPT", "hi", "ENGLISH-DEFAULT")
    assert hindi != "ENGLISH-DEFAULT"
    assert hindi == HI["TX_HASH_PROMPT"]


def test_tr_falls_back_to_default_for_missing_key() -> None:
    assert tr("DOES_NOT_EXIST", "hi", "fallback text") == "fallback text"


def test_tr_falls_back_to_default_for_english() -> None:
    assert tr("TX_HASH_PROMPT", None, "fallback text") == "fallback text"
    assert tr("TX_HASH_PROMPT", "en", "fallback text") == "fallback text"


def test_tr_falls_back_for_unknown_language_codes() -> None:
    assert tr("TX_HASH_PROMPT", "gu", "fallback text") == "fallback text"


def test_lang_of_defaults_to_english() -> None:
    assert lang_of(User(user_id=1)) == "en"
    assert lang_of(User(user_id=1, lang="en")) == "en"


def test_lang_of_reflects_hindi_choice() -> None:
    assert lang_of(User(user_id=1, lang="hi")) == "hi"


# ---------------------------------------------------------------------------
# Admin reject reason keyboard
# ---------------------------------------------------------------------------


def test_admin_reject_reasons_keyboard_callback_data() -> None:
    markup = kb.admin_reject_reasons(9)
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    for code in kb.REJECT_REASONS:
        assert f"admin:reject_reason:9:{code}" in callbacks
    # back button restores the approve/reject card
    assert "admin:back:9" in callbacks
    # every reason row is individually labelled with the human-readable reason
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    for reason in kb.REJECT_REASONS.values():
        assert any(reason in label for label in labels)


def test_admin_review_keyboard_still_uses_reject_picker_entry() -> None:
    markup = kb.admin_review(9)
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert "admin:approve:9" in callbacks
    assert "admin:reject:9" in callbacks
