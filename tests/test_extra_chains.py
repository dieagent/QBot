"""Tests for SOL/TON/LTC deposit support: keyboards, explorer links,
loose hash validation for manual review, boot-check coverage."""
from __future__ import annotations

from marco_bot import bootcheck, chainverify, keyboards as kb, messages as msg
from test_services import settings_for_test


# ---------------------------------------------------------------------------
# Keyboards offer the new tokens with native-only chains
# ---------------------------------------------------------------------------


def test_token_select_offers_sol_ton_ltc() -> None:
    markup = kb.token_select("express")
    buttons = {btn.text: btn.callback_data for row in markup.inline_keyboard for btn in row}
    for token, expected in {"BTC": "express:token:BTC", "ETH": "express:token:ETH", "USDT": "express:token:USDT",
                            "SOL": "express:token:SOL", "TON": "express:token:TON", "LTC": "express:token:LTC"}.items():
        assert buttons[token] == expected
    # and the wallet flow uses the same catalog
    wallet = kb.token_select("wallet")
    wallet_buttons = {btn.callback_data for row in wallet.inline_keyboard for btn in row}
    assert "wallet:token:SOL" in wallet_buttons and "wallet:token:LTC" in wallet_buttons


def test_express_chains_native_only_for_new_tokens() -> None:
    for token, chain in [("SOL", "SOL"), ("TON", "TON"), ("LTC", "LTC")]:
        markup = kb.express_chains(token, "express")
        chains = [btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data.startswith("express:chain:")]
        assert chains == [f"express:chain:{chain}"]


# ---------------------------------------------------------------------------
# Explorer links (My Transactions + admin card)
# ---------------------------------------------------------------------------


def test_explorer_urls_for_new_networks() -> None:
    assert chainverify.explorer_url("SOL", "sig123") == "https://solscan.io/tx/sig123"
    assert chainverify.explorer_url("TON", "hash9") == "https://tonviewer.com/transaction/hash9"
    assert chainverify.explorer_url("LTC", "ab" * 32) == "https://blockchair.com/litecoin/transaction/" + "ab" * 32


# ---------------------------------------------------------------------------
# Loose tx-id validation for manual-review networks
# ---------------------------------------------------------------------------


SOL_SIG = "7" + "kP1X" * 20 + "Fkq"  # 83 chars base58-ish
LTC_ID = "ab" * 32


def test_plausible_tx_id_accepts_solana_signatures() -> None:
    assert chainverify.plausible_tx_id(SOL_SIG, "SOL") == SOL_SIG


def test_plausible_tx_id_accepts_ton_hash() -> None:
    assert chainverify.plausible_tx_id("A83fJdFsC2lM2cNo+qeMNDlzeEvgTwC+v0Apm1AheBM=", "TON") == "A83fJdFsC2lM2cNo+qeMNDlzeEvgTwC+v0Apm1AheBM="


def test_plausible_tx_id_accepts_ltc_hex() -> None:
    assert chainverify.plausible_tx_id(LTC_ID.upper(), "LTC") == LTC_ID


def test_plausible_tx_id_rejects_garbage() -> None:
    assert chainverify.plausible_tx_id("", "SOL") is None
    assert chainverify.plausible_tx_id("hello world", "TON") is None
    assert chainverify.plausible_tx_id("nothex", "LTC") is None
    assert chainverify.plausible_tx_id("   ", "SOL") is None
    assert chainverify.plausible_tx_id("x" * 500, "SOL") is None


def test_plausible_tx_id_unchanged_for_supported_shapes() -> None:
    evm_hash = "0x" + "ab" * 32
    assert chainverify.plausible_tx_id(evm_hash, "BEP20") == evm_hash
    # EVM shape on an LTC label falls back to the plain hex normalizer
    assert chainverify.plausible_tx_id("ab" * 32, "LTC") == "ab" * 32


# ---------------------------------------------------------------------------
# Boot self-check covers the new deposit routes
# ---------------------------------------------------------------------------


def test_bootcheck_combos_include_new_tokens() -> None:
    combos = set(bootcheck.DEPOSIT_COMBOS)
    assert ("SOL", "SOL") in combos
    assert ("TON", "TON") in combos
    assert ("LTC", "LTC") in combos
    assert len(bootcheck.DEPOSIT_COMBOS) == len(combos)  # no duplicates


def test_missing_addresses_reports_new_combos_until_configured() -> None:
    settings = settings_for_test(deposit_addresses={})
    missing = bootcheck.missing_deposit_addresses(settings)
    assert "SOL-SOL" in missing and "TON-TON" in missing and "LTC-LTC" in missing
    configured = settings_for_test(
        deposit_addresses={"SOL": {"SOL": "soladdr"}, "TON": {"TON": "tonaddr"}, "LTC": {"LTC": "ltcaddr"}}
    )
    still_missing = bootcheck.missing_deposit_addresses(configured)
    assert "SOL-SOL" not in still_missing
    assert "TON-TON" not in still_missing
    assert "LTC-LTC" not in still_missing


# ---------------------------------------------------------------------------
# Manual-review prompt text exists and instructs both paths
# ---------------------------------------------------------------------------


def test_manual_prompt_offers_hash_and_screenshot_options() -> None:
    assert "hash" in msg.MANUAL_HASH_PROMPT.lower()
    assert "screenshot" in msg.MANUAL_HASH_PROMPT.lower()
    assert "approve" in msg.MANUAL_HASH_SUBMITTED.lower()


# ---------------------------------------------------------------------------
# Admin card surfaces the manual hash + explorer URL
# ---------------------------------------------------------------------------


def _manual_tx(**over):
    from decimal import Decimal

    from marco_bot.models import Transaction

    base = dict(
        tx_id=5, user_id=1, type="wallet_deposit", coin="SOL", chain="SOL",
        amount_usd=Decimal("40"), amount_inr=Decimal("0"),
        status="pending", verify_status="manual", chain_tx_hash=None,
    )
    base.update(over)
    return Transaction(**base)


def test_verification_block_manual_shows_hash_and_explorer() -> None:
    from marco_bot import review

    block = review.verification_block(_manual_tx(chain_tx_hash="sigXYZ"))
    assert "MANUAL" in block
    assert "sigXYZ" in block
    assert "solscan.io/tx/sigXYZ" in block


def test_verification_block_manual_without_hash_keeps_screenshot_hint() -> None:
    from marco_bot import review

    block = review.verification_block(_manual_tx())
    assert "screenshot only" in block
