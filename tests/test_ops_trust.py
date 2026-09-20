"""Tests for ops/trust pack: GitHub CI presence, boot self-check, aging
pending alerts, post-deal rating, and My Stats polish (badge progress,
cooldown line, platform rating line)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from marco_bot import bootcheck, keyboards as kb, messages as msg, review
from marco_bot.models import Transaction
from marco_bot.services import (
    badge_progress_line,
    bot_state_timestamp,
    next_badge,
    parse_bot_state,
    platform_rating_line,
    serialize_bot_state,
    throttled,
)
from test_services import settings_for_test


# ---------------------------------------------------------------------------
# CI workflow present and wired to pytest
# ---------------------------------------------------------------------------


def test_ci_workflow_exists_and_runs_pytest() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    assert workflow.exists(), "GitHub Actions workflow missing"
    content = workflow.read_text()
    assert "pytest" in content
    assert "requirements.txt" in content


# ---------------------------------------------------------------------------
# Boot self-check
# ---------------------------------------------------------------------------


def test_missing_deposit_addresses_covers_all_ui_combos() -> None:
    settings = settings_for_test(deposit_addresses={})
    missing = bootcheck.missing_deposit_addresses(settings)
    assert len(missing) == len(bootcheck.DEPOSIT_COMBOS)
    assert "USDT-BEP20" in missing and "BTC-BTC" in missing and "ETH-ERC20" in missing


def test_configured_address_removes_combo_from_missing_list() -> None:
    settings = settings_for_test(deposit_addresses={"USDT": {"BEP20": "TConfigurationOK"}})
    missing = bootcheck.missing_deposit_addresses(settings)
    assert "USDT-BEP20" not in missing
    assert len(missing) == len(bootcheck.DEPOSIT_COMBOS) - 1


def test_boot_alert_text_lists_warnings() -> None:
    text = bootcheck.boot_alert_text(["No deposit address configured for BTC-BTC", "CRON_SECRET not set"])
    assert "boot self-check" in text
    assert "BTC-BTC" in text
    assert "CRON_SECRET" in text


# ---------------------------------------------------------------------------
# bot_state JSON bag + throttling
# ---------------------------------------------------------------------------


def test_bot_state_json_roundtrip() -> None:
    assert parse_bot_state(None) == {}
    assert parse_bot_state("not-json") == {}
    assert parse_bot_state('["a", "list"]') == {}
    assert parse_bot_state(serialize_bot_state({"a": 1, "b": "x"})) == {"a": 1, "b": "x"}


def test_bot_state_timestamp_parsing() -> None:
    stamp = bot_state_timestamp({"k": "2026-09-20T13:00:00"}, "k")
    assert stamp == datetime(2026, 9, 20, 13, 0, 0)
    assert bot_state_timestamp({"k": "garbage"}, "k") is None
    assert bot_state_timestamp({"other": 1}, "k") is None


def test_throttled_respects_interval_and_clock_skew() -> None:
    now = datetime(2026, 9, 20, 13, 0, 0)
    recent = {"k": (now - timedelta(seconds=10)).isoformat()}
    old = {"k": (now - timedelta(seconds=999)).isoformat()}
    future = {"k": (now + timedelta(hours=1)).isoformat()}
    assert throttled(recent, "k", 60, now=now) is True
    assert throttled(old, "k", 60, now=now) is False
    assert throttled(future, "k", 60, now=now) is False
    assert throttled({}, "k", 60, now=now) is False


# ---------------------------------------------------------------------------
# Aging pending alerts
# ---------------------------------------------------------------------------


def test_aging_alert_text_lists_old_deals_and_footer() -> None:
    now = datetime(2026, 9, 20, 13, 0, 0)
    stuck = [
        Transaction(tx_id=12, user_id=7, type="express_sell", amount_usd=Decimal("100"), amount_inr=Decimal("9400"), status="pending", created_at=now - timedelta(minutes=62)),
        Transaction(tx_id=13, user_id=8, type="wallet_deposit", amount_usd=Decimal("55.5"), amount_inr=Decimal("0"), status="pending", created_at=now - timedelta(minutes=47)),
    ]
    text = review.aging_alert_text(stuck, 2, 45, now=now)
    assert "2 deals pending" in text
    assert "TX 12" in text and "62 min old" in text
    assert "TX 13" in text and "47 min old" in text
    assert "/pending" in text


def test_aging_alert_text_truncates_long_queues() -> None:
    now = datetime(2026, 9, 20, 13, 0, 0)
    tx = Transaction(tx_id=1, user_id=7, type="express_sell", amount_usd=Decimal("10"), amount_inr=Decimal("0"), status="pending", created_at=now - timedelta(minutes=60))
    # 7 pending, only AGING_ALERT_SAMPLE (5) are shown → "and 2 more"
    text = review.aging_alert_text([tx], 7, 45, now=now)
    assert "7 deals pending" in text
    assert "and 2 more" in text


def test_aging_alert_thresholds_sane() -> None:
    assert review.PENDING_AGE_MINUTES >= 30
    assert review.AGING_ALERT_INTERVAL_SECONDS >= 15 * 60


def test_admin_chat_destinations_review_chat_plus_ids() -> None:
    settings = settings_for_test(admin_ids=[1, 2], admin_review_chat_id="-1001234")
    assert review.admin_chat_destinations(settings) == ["-1001234", 1, 2]
    settings = settings_for_test(admin_ids=[1], admin_review_chat_id=None)
    assert review.admin_chat_destinations(settings) == [1]


# ---------------------------------------------------------------------------
# Post-deal rating
# ---------------------------------------------------------------------------


def test_rating_buttons_callback_data() -> None:
    markup = kb.rating_buttons(41)
    callbacks = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    assert callbacks == [f"rate:41:{n}" for n in range(1, 6)]
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert labels[0].count("⭐") == 1 and labels[-1].count("⭐") == 5


def test_platform_rating_line_hidden_until_enough_ratings() -> None:
    assert platform_rating_line(Decimal("5.00"), 2) is None
    line = platform_rating_line(Decimal("4.87"), 120)
    assert line is not None
    assert "4.87/5" in line and "120 users" in line


# ---------------------------------------------------------------------------
# My Stats polish: badge progress, cooldown, rating lines
# ---------------------------------------------------------------------------


def test_next_badge_progression() -> None:
    assert next_badge(0) == (Decimal("250"), "🥉 BRONZE")
    assert next_badge("250") == (Decimal("1000"), "🥈 SILVER")
    assert next_badge("1000") == (Decimal("5000"), "🥇 GOLD")
    assert next_badge("5000") is None
    assert next_badge("999999") is None


def test_badge_progress_line() -> None:
    # 380 already holds BRONZE, so the goalpost is SILVER at 1000
    line = badge_progress_line(Decimal("380.00"))
    assert "SILVER" in line and "$620.00" in line
    # below first tier the goalpost is BRONZE
    line = badge_progress_line(Decimal("10"))
    assert "BRONZE" in line and "$240.00" in line
    assert "Top badge" in badge_progress_line(Decimal("5000"))


def test_my_stats_render_includes_extras() -> None:
    text = msg.my_stats_render(
        "alice", "01 Jan, 2026", 3, 7, Decimal("1200.50"),
        badge="🥈 SILVER", referrals=2,
        extras=["🏅 🥇 GOLD badge — $3799.50 more volume to unlock", "⭐ Bot rated 4.9/5 by 12 users"],
    )
    assert "🥈 SILVER" in text
    assert "$3799.50" in text
    assert "4.9/5" in text
    assert "Referrals: 2" in text


def test_my_stats_render_hindi_keeps_extras() -> None:
    text = msg.my_stats_render(
        "alice", "01 Jan, 2026", 0, 0, Decimal("0"),
        extras=["🏅 🥉 BRONZE badge — $250.00 more volume to unlock"],
        lang="hi",
    )
    assert "🥉 BRONZE" in text  # extras survive the Hindi template's {extras} placeholder


def test_my_stats_render_without_extras_unchanged() -> None:
    text = msg.my_stats_render("alice", "01 Jan, 2026", 0, 0, Decimal("0"))
    assert "Statistics" in text and "Referrals: 0" in text
