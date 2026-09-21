"""Tests for SOL/TON/LTC auto-verifiers and the auto receipt prompt."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from marco_bot import chainverify as cv
from marco_bot.handlers import admin as admin_srv
from test_services import settings_for_test

SETTINGS = settings_for_test(solana_rpc_url="https://sol.rpc", toncenter_api_key="key123")
DEST = "depositaddr-PASTE"

SOL_SIG = "7" + "kP1X" * 20 + "Fkq"
TON_B64 = "A83fJdFsC2lM2cNo+qeMNDlzeEvgTwC+v0Apm1AheBM="
TON_B64URL = "A83fJdFsC2lM2cNo-qeMNDlzeEvgTwC-v0Apm1AheBM="
LTC_ID = "ab" * 32


def make_fetch(responder):
    async def fetch(url, params=None, headers=None, json_body=None):
        return responder(url, dict(params or {}), json_body)

    return fetch


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Support registry + canonical ids
# ---------------------------------------------------------------------------


def test_chain_family_new_networks() -> None:
    assert cv.chain_family("SOL") == "sol"
    assert cv.chain_family("TON") == "ton"
    assert cv.chain_family("LTC") == "ltc"


def test_support_status_new_natives() -> None:
    for token, chain in [("SOL", "SOL"), ("TON", "TON"), ("LTC", "LTC")]:
        supported, reason = cv.support_status(SETTINGS, token, chain, DEST)
        assert supported, reason
    supported, _ = cv.support_status(SETTINGS, "USDT", "SOL", DEST)
    assert not supported
    supported, _ = cv.support_status(SETTINGS, "SOL", "SOL", None)
    assert not supported


def test_canonical_tx_id_routes_by_family() -> None:
    assert cv.canonical_tx_id(SOL_SIG, "SOL") == SOL_SIG
    assert cv.canonical_tx_id(TON_B64, "TON") == TON_B64
    assert cv.canonical_tx_id("AB" * 32, "LTC") == "ab" * 32
    assert cv.canonical_tx_id("garbage", "SOL") is None
    assert cv.canonical_tx_id("garbage", "TON") is None


# ---------------------------------------------------------------------------
# SOL verifier
# ---------------------------------------------------------------------------


def _sol_responder(sig_status_entry, tx_meta_err=None, pre=(1500, 0), post=(1000, 5_000_000_000), keys=("PAYER", DEST), missing_sig=False):
    def respond(url, params, json_body):
        method = (json_body or {}).get("method")
        if method == "getSignatureStatuses":
            return {"result": {"value": [None if missing_sig else sig_status_entry]}}
        if method == "getTransaction":
            return {
                "result": {
                    "meta": {"err": tx_meta_err, "preBalances": list(pre), "postBalances": list(post)},
                    "transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys]}},
                }
            }
        raise AssertionError(f"unexpected RPC method {method}")

    return make_fetch(respond)


def test_sol_verifier_confirms_finalized_transfer() -> None:
    fetch = _sol_responder({"err": None, "confirmationStatus": "finalized"})
    result = run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch))
    assert result.status == cv.STATUS_VERIFIED
    assert result.amount == 5  # 5 SOL net delta
    assert "solscan" in (result.explorer_url or "")


def test_sol_verifier_pends_until_confirmed() -> None:
    fetch = _sol_responder({"err": None, "confirmationStatus": "processed"})
    result = run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch))
    assert result.status == cv.STATUS_PENDING
    # brand-new signature the node hasn't seen
    fetch = _sol_responder(None, missing_sig=True)
    result = run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch))
    assert result.status == cv.STATUS_PENDING


def test_sol_verifier_rejects_wrong_and_failed_transfers() -> None:
    fetch = _sol_responder({"err": {"InstructionError": [0, "Custom"]}, "confirmationStatus": "finalized"})
    assert run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch)).status == cv.STATUS_FAILED
    # address absent from tx
    fetch = _sol_responder({"err": None, "confirmationStatus": "confirmed"}, keys=("PAYER", "OTHER"))
    assert run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch)).status == cv.STATUS_FAILED
    # delta <= 0 (someone drew FROM the address)
    fetch = _sol_responder({"err": None, "confirmationStatus": "finalized"}, pre=(0, 10**10), post=(0, 0))
    assert run(cv.verify_payment(SETTINGS, "SOL", "SOL", DEST, 0, "sig", fetch=fetch)).status == cv.STATUS_FAILED


# ---------------------------------------------------------------------------
# TON verifier (toncenter v2)
# ---------------------------------------------------------------------------


def _ton_responder(rows, ok=True):
    def respond(url, params, json_body):
        assert params.get("address") == DEST
        assert params.get("api_key") == "key123"
        return {"ok": ok, "result": rows}

    return make_fetch(respond)


def test_ton_verifier_matches_urlsafe_hash_against_std_api_hash() -> None:
    rows = [
        {"transaction_id": {"hash": "NOTMATCH123"}, "in_msg": {"value": "100"}},
        {"transaction_id": {"hash": TON_B64}, "in_msg": {"value": "2500000000"}},
    ]
    result = run(cv.verify_payment(SETTINGS, "TON", "TON", DEST, 0, TON_B64URL, fetch=_ton_responder(rows)))
    assert result.status == cv.STATUS_VERIFIED
    assert result.amount == 2.5
    assert "tonviewer" in (result.explorer_url or "")


def test_ton_verifier_pending_until_indexed_and_fails_on_zero_value() -> None:
    result = run(cv.verify_payment(SETTINGS, "TON", "TON", DEST, 0, TON_B64, fetch=_ton_responder([])))
    assert result.status == cv.STATUS_PENDING
    rows = [{"transaction_id": {"hash": TON_B64}, "in_msg": {"value": "0"}}]
    result = run(cv.verify_payment(SETTINGS, "TON", "TON", DEST, 0, TON_B64, fetch=_ton_responder(rows)))
    assert result.status == cv.STATUS_FAILED


def test_ton_verifier_api_failure_is_pending_not_fatal() -> None:
    result = run(cv.verify_payment(SETTINGS, "TON", "TON", DEST, 0, TON_B64, fetch=_ton_responder([], ok=False)))
    assert result.status == cv.STATUS_PENDING


# ---------------------------------------------------------------------------
# LTC verifier (litecoinspace.org esplora)
# ---------------------------------------------------------------------------


def _ltc_responder(confirmed=True, pays=True, tip=2900100, block=2900090):
    def respond(url, params, json_body):
        if url.endswith("/blocks/tip/height"):
            return tip
        vout_item = {"scriptpubkey_address": DEST, "value": 400_000_000} if pays else {"scriptpubkey_address": "OTHER", "value": 1}
        return {"txid": LTC_ID, "status": {"confirmed": confirmed, "block_height": block}, "vout": [vout_item]}

    return make_fetch(respond)


def test_ltc_verifier_confirms_paid_output() -> None:
    result = run(cv.verify_payment(SETTINGS, "LTC", "LTC", DEST, 0, LTC_ID, fetch=_ltc_responder()))
    assert result.status == cv.STATUS_VERIFIED
    assert result.amount == 4  # 4 LTC
    assert result.confirmations == 11


def test_ltc_verifier_unconfirmed_and_unpaid() -> None:
    assert run(cv.verify_payment(SETTINGS, "LTC", "LTC", DEST, 0, LTC_ID, fetch=_ltc_responder(confirmed=False))).status == cv.STATUS_PENDING
    assert run(cv.verify_payment(SETTINGS, "LTC", "LTC", DEST, 0, LTC_ID, fetch=_ltc_responder(pays=False))).status == cv.STATUS_FAILED


# ---------------------------------------------------------------------------
# Auto receipt prompt state machine (admin)
# ---------------------------------------------------------------------------

NOW = datetime(2026, 9, 20, 13, 0, 0)


def test_pending_receipt_roundtrip_and_expiry() -> None:
    raw = admin_srv.new_pending_receipt(41, NOW)
    assert admin_srv.parse_pending_receipt(raw, NOW + timedelta(minutes=9)) == 41
    assert admin_srv.parse_pending_receipt(raw, NOW + timedelta(minutes=11)) is None


def test_parse_pending_receipt_tolerates_junk() -> None:
    assert admin_srv.parse_pending_receipt(None, NOW) is None
    assert admin_srv.parse_pending_receipt("", NOW) is None
    assert admin_srv.parse_pending_receipt("not json", NOW) is None
    assert admin_srv.parse_pending_receipt(json.dumps({"tx_id": 1}), NOW) is None
    assert admin_srv.parse_pending_receipt(json.dumps({"tx_id": "nope", "until": "2999-01-01T00:00:00"}), NOW) is None


def test_normalize_reference_rules() -> None:
    assert admin_srv.normalize_reference("  831204912345 ") == "831204912345"
    assert admin_srv.normalize_reference("") is None
    assert admin_srv.normalize_reference("   ") is None
    assert admin_srv.normalize_reference("x" * 65) is None
    assert admin_srv.normalize_reference("/receipt 1 x") is None


def test_skip_words_and_prompt_scope() -> None:
    for word in ["skip", "Skip", "SKIP", "later", "no", "cancel", "/skip"]:
        assert admin_srv.is_skip(word)
    assert not admin_srv.is_skip("831204912345")
    # receipts are asked only for payout-type deals, not on-chain credits
    assert "wallet_deposit" not in admin_srv.RECEIPT_PROMPT_TYPES
    assert "express_sell" in admin_srv.RECEIPT_PROMPT_TYPES
    assert "withdrawal" in admin_srv.RECEIPT_PROMPT_TYPES


def test_pending_receipt_key_is_per_admin() -> None:
    assert admin_srv.pending_receipt_key(11) == "pending_receipt:11"
    assert admin_srv.pending_receipt_key(11) != admin_srv.pending_receipt_key(22)
