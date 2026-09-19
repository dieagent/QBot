from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from marco_bot import chainverify, review
from marco_bot.config import load_settings
from marco_bot.db import configure_database, init_db, session_scope
from marco_bot.models import Transaction, User


class EnvGuard:
    def __init__(self, **updates):
        self.updates = updates
        self.saved: dict[str, str | None] = {}

    def __enter__(self):
        for key, value in self.updates.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def run(coro):
    return asyncio.run(coro)


def test_webhook_mode_off_without_env():
    with EnvGuard(WEBHOOK_URL=None, VERCEL_URL=None, BOT_TOKEN="123:abc"):
        settings = load_settings()
        assert not settings.webhook_mode
        assert settings.resolved_webhook_url() is None


def test_webhook_mode_via_explicit_url():
    with EnvGuard(WEBHOOK_URL="https://qbot.vercel.app/api/webhook", BOT_TOKEN="123:abc"):
        settings = load_settings()
        assert settings.webhook_mode
        assert settings.resolved_webhook_url() == "https://qbot.vercel.app/api/webhook"


def test_webhook_url_derived_from_vercel_env():
    with EnvGuard(WEBHOOK_URL=None, VERCEL_URL="qbot-team.vercel.app", BOT_TOKEN="123:abc"):
        settings = load_settings()
        assert settings.webhook_mode
        assert settings.resolved_webhook_url() == "https://qbot-team.vercel.app/api/webhook"


def test_postgres_url_sslmode_rewritten():
    with EnvGuard(
        DATABASE_URL="postgres://u:p@host:5432/db?sslmode=require",
        BOT_TOKEN="123:abc",
    ):
        settings = load_settings()
        assert settings.database_url.startswith("postgresql+asyncpg://")
        assert "ssl=require" in settings.database_url
        assert "sslmode" not in settings.database_url


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[str, object]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(("msg", chat_id))

    async def send_photo(self, chat_id, photo, **kwargs):
        self.sent.append(("photo", chat_id))


def _settings(db_url: str, webhook_url: str | None):
    with EnvGuard(
        BOT_TOKEN="123:abc",
        ADMIN_IDS="111",
        DATABASE_URL=db_url,
        WEBHOOK_URL=webhook_url,
        VERCEL_URL=None,
    ):
        return load_settings()


def test_schedule_verification_inline_in_webhook_mode(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/bot.sqlite3"
    settings = _settings(db_url, "https://qbot.vercel.app/api/webhook")
    monkeypatch.setenv("WEBHOOK_URL", "https://qbot.vercel.app/api/webhook")

    async def scenario():
        configure_database(settings.database_url)
        await init_db(settings)
        async with session_scope() as session:
            session.add(User(user_id=42, username="bob"))
            tx = Transaction(
                user_id=42,
                type="express_sell",
                coin="USDT",
                chain="TRC20",
                amount_usd=Decimal("100"),
                amount_inr=Decimal("9400"),
                deposit_address="TX471pFdCnad1X5Xx5dRV4DzcpbcpVQo6W",
                chain_tx_hash="ab" * 32,
                verify_status="verifying",
                status="pending",
            )
            session.add(tx)
            await session.flush()
            tx_id = tx.tx_id

        async def fake_verify(*args, **kwargs):
            return chainverify.VerificationResult(status="verified", detail="100 USDT received on TRC20", amount=Decimal("100"))

        monkeypatch.setattr(chainverify, "verify_payment", fake_verify)
        bot = FakeBot()
        outcome = await review.schedule_verification(settings, bot, tx_id)
        async with session_scope() as session:
            tx = await session.get(Transaction, tx_id)
            assert tx.verify_status == "verified"
        return outcome, bot

    outcome, bot = run(scenario())
    assert outcome == "verified"           # webhook mode returns the result
    assert ("msg", 42) in bot.sent         # user notified
    assert ("msg", 111) in bot.sent        # admin notified


def test_sweep_pending_checks_verifying_txs(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/bot.sqlite3"
    settings = _settings(db_url, None)
    monkeypatch.delenv("WEBHOOK_URL", raising=False)

    async def scenario():
        configure_database(settings.database_url)
        await init_db(settings)
        async with session_scope() as session:
            session.add(User(user_id=42, username="bob"))
            session.add(
                Transaction(
                    user_id=42,
                    type="wallet_deposit",
                    coin="USDT",
                    chain="BEP20",
                    amount_usd=Decimal("50"),
                    deposit_address="0x4ea801303C12Bf628E6c9dd661962eF7b36C9301",
                    chain_tx_hash="0x" + "cd" * 32,
                    verify_status="verifying",
                    status="pending",
                )
            )

        calls = []

        async def fake_verify(*args, **kwargs):
            calls.append(args)
            return chainverify.VerificationResult(status="pending", detail="still confirming")

        monkeypatch.setattr(chainverify, "verify_payment", fake_verify)
        checked = await review.sweep_pending(settings, FakeBot())
        return checked, calls

    checked, calls = run(scenario())
    assert checked == 1
    assert len(calls) == 1
