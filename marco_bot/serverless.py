"""Serverless (webhook) runtime — used by api/webhook.py on Vercel.

Long-polling cannot run on Vercel, so this module replaces
`python -m marco_bot.main` for serverless deployments:

- once per container: configure the DB (NullPool engine, safe across
  sequential event loops), run init_db, register the Telegram webhook;
- per request: validate the webhook secret, sweep pending deposit
  verifications (bounded), then feed the update to the dispatcher.

A real Postgres DATABASE_URL is mandatory here: SQLite lives on the
ephemeral function filesystem and ledger data would be lost, so startup
fails loudly instead of silently using it.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Update

from . import review
from .config import Settings, load_settings
from .db import configure_database, init_db
from .handlers import admin, user

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_settings: Settings | None = None
_dispatcher: Dispatcher | None = None
_initialized = False

DATABASE_URL_ERROR = (
    "DATABASE_URL is missing, is still a Railway-style reference "
    "('${{Postgres.DATABASE_URL}}'), or points at SQLite. Serverless instances "
    "have an ephemeral filesystem, so the ledger requires a real Postgres "
    "URL (postgresql://user:pass@host:port/db) in the Vercel env vars. "
    "Set it, then redeploy."
)


def _usable_database_url(settings: Settings) -> bool:
    url = (settings.database_url or "").strip()
    if "${" in url:
        return False
    # SQLite is refused here on purpose: it lives on the ephemeral function
    # filesystem and balances/ad history would vanish between instances.
    return url.startswith(("postgresql://", "postgres://", "postgresql+asyncpg://"))


async def ensure_initialized() -> Settings:
    """Cold-start initialization, executed once per function container."""
    global _settings, _initialized
    if _settings is None:
        _settings = load_settings()
    settings = _settings

    if not _usable_database_url(settings):
        raise RuntimeError(DATABASE_URL_ERROR)

    if _initialized:
        return settings

    # A rare double cold-start can race here; it resolves itself on the next
    # request (Telegram retries failed webhook deliveries).
    configure_database(settings.database_url, null_pool=True)
    await init_db(settings)
    admin.configure(settings)
    user.configure(settings)
    _get_dispatcher()
    await _ensure_webhook(settings)
    _initialized = True
    return settings


def _get_dispatcher() -> Dispatcher:
    """The one dispatcher per container.

    aiogram routers attach to exactly one dispatcher; re-including them per
    request raised "Router is already attached" and broke the bot. Build it
    once and reuse it for every update.
    """
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = Dispatcher()
        _dispatcher.include_router(admin.router)
        _dispatcher.include_router(user.router)
    return _dispatcher


async def _ensure_webhook(settings: Settings) -> None:
    url = settings.resolved_webhook_url()
    if not url:
        logger.warning("WEBHOOK_URL/VERCEL_URL not set — webhook not registered")
        return
    bot = Bot(token=settings.bot_token)
    try:
        info = await bot.get_webhook_info()
        if info.url != url:
            await bot.set_webhook(
                url,
                secret_token=settings.webhook_secret or None,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            logger.info("Webhook registered at %s", url)
    finally:
        await bot.session.close()


async def status() -> dict:
    """GET handler payload — also forces cold-start init (webhook registration)."""
    settings = await ensure_initialized()
    return {"ok": True, "mode": "webhook", "bot": "marco-p2p"}


async def handle_update(update_data: dict, secret_header: str | None) -> bool:
    """Process one Telegram webhook update. Returns False on secret mismatch."""
    settings = await ensure_initialized()
    if settings.webhook_secret and secret_header != settings.webhook_secret:
        return False

    bot = Bot(token=settings.bot_token)
    try:
        # Serverless has no background tasks: retry pending deposit
        # verifications on incoming traffic, within a hard time budget.
        try:
            async with asyncio.timeout(20):
                await review.sweep_pending(settings, bot)
        except Exception:
            logger.warning("pending sweep failed", exc_info=True)

        dispatcher = _get_dispatcher()
        update = Update.model_validate(update_data)
        await dispatcher.feed_update(bot, update)
    finally:
        await bot.session.close()
    return True
