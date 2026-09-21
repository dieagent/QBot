"""Wave 2: support tickets, dispute flow, rate wizard, QR flyers, saved payouts."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from marco_bot import keyboards as kb
from marco_bot import services
from marco_bot.handlers import admin as admin_srv

NOW = datetime(2026, 9, 21, 14, 0, 0)


# ---------------------------------------------------------------------------
# Support reply prompt state machine
# ---------------------------------------------------------------------------


def test_support_reply_prompt_roundtrip() -> None:
    raw = admin_srv.new_support_reply(777, NOW)
    assert admin_srv.parse_support_reply(raw, NOW + timedelta(minutes=9)) == 777
    assert admin_srv.parse_support_reply(raw, NOW + timedelta(minutes=11)) is None


def test_support_reply_prompt_tolerates_junk() -> None:
    assert admin_srv.parse_support_reply(None, NOW) is None
    assert admin_srv.parse_support_reply("", NOW) is None
    assert admin_srv.parse_support_reply("nope", NOW) is None
    assert admin_srv.parse_support_reply(json.dumps({"user_id": "x", "until": "2999-01-01T00:00:00"}), NOW) is None
    assert admin_srv.support_reply_key(5) != admin_srv.support_reply_key(6)


# ---------------------------------------------------------------------------
# Rate wizard state machine
# ---------------------------------------------------------------------------


def test_ratewiz_lifecycle() -> None:
    raw = admin_srv.new_ratewiz("upi", NOW)
    wiz = admin_srv.parse_ratewiz(raw, NOW + timedelta(minutes=1))
    assert wiz["mode"] == "UPI"
    assert wiz["step"] == "min"
    assert wiz["values"] == {}
    # expiry
    assert admin_srv.parse_ratewiz(raw, NOW + timedelta(minutes=6)) is None
    # steps advance and wrap
    assert admin_srv.ratewiz_next_step("min") == "max"
    assert admin_srv.ratewiz_next_step("max") == "rate"
    assert admin_srv.ratewiz_next_step("rate") is None


def test_ratewiz_garbage_and_prompts() -> None:
    assert admin_srv.parse_ratewiz(None, NOW) is None
    assert admin_srv.parse_ratewiz("{}", NOW) is None
    assert set(admin_srv.RATEWIZ_PROMPTS) == set(admin_srv.RATE_WIZARD_STEPS)
    assert admin_srv.parse_ratewiz(json.dumps({"mode": "UPI", "step": "nonsense", "until": "2999-01-01T00:00:00"}), NOW) is None


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------


def test_receipt_actions_have_stars_and_dispute() -> None:
    rows = kb.receipt_actions(41).inline_keyboard
    prefix_pairs = [(row[0].text, row[0].callback_data) for row in rows]
    assert "⭐" in rows[0][0].text and rows[0][0].callback_data == "rate:41:1"
    assert rows[1][0].callback_data == "dispute:41"


def test_support_reply_keyboard_targets_user() -> None:
    markup = kb.support_reply(555)
    assert markup.inline_keyboard[0][0].callback_data == "support:555"


def test_withdraw_saved_choice_keyboard() -> None:
    codes = [b.callback_data for row in kb.withdraw_saved_choice().inline_keyboard for b in row]
    assert codes == ["withdraw:use_saved", "withdraw:new"]


def test_rate_wizard_modes_keyboard() -> None:
    markup = kb.rate_wizard_modes(["UPI", "CDM"])
    assert [row[0].callback_data for row in markup.inline_keyboard] == ["ratewiz:UPI", "ratewiz:CDM"]


# ---------------------------------------------------------------------------
# QR flyer
# ---------------------------------------------------------------------------


def test_referral_qr_png_produces_image() -> None:
    png = services.referral_qr_png("https://t.me/marco?start=ref_42")
    assert png is not None and png[:4] == b"\x89PNG"
    assert len(png) > 100


def test_referral_qr_png_never_crashes(monkeypatch) -> None:
    importsys = __import__("sys")
    monkeypatch.setitem(importsys.modules, "qrcode", None)  # simulate import failure
    assert services.referral_qr_png("https://t.me/x") is None
