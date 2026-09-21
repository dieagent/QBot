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
import html
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Update
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from . import bootcheck, review
from .config import Settings, load_settings
from .db import configure_database, init_db, session_scope
from .handlers import admin, user
from .models import RateTier, Transaction, User
from .services import get_bot_state, set_bot_state_keys, throttled

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_settings: Settings | None = None
_dispatcher: Dispatcher | None = None
_initialized = False
_last_sweep_at = 0.0
SWEEP_MIN_INTERVAL_SECONDS = 10.0

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
    await bootcheck.run_boot_check(settings)
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
        # verifications on incoming traffic — throttled to an interval and run
        # CONCURRENTLY with the update so users never wait on the sweep.
        global _last_sweep_at
        sweep_task: asyncio.Task | None = None
        now = asyncio.get_running_loop().time()
        if now - _last_sweep_at >= SWEEP_MIN_INTERVAL_SECONDS:
            _last_sweep_at = now
            sweep_task = asyncio.create_task(_bounded_sweep(settings, bot))

        dispatcher = _get_dispatcher()
        update = Update.model_validate(update_data)
        await dispatcher.feed_update(bot, update)

        if sweep_task is not None:
            await sweep_task
    finally:
        await bot.session.close()
    return True


async def _bounded_sweep(settings: Settings, bot: Bot) -> None:
    try:
        async with asyncio.timeout(20):
            await review.sweep_pending(settings, bot)
    except Exception:
        logger.warning("pending sweep failed", exc_info=True)


# ---------------------------------------------------------------------------
# Ops visibility: daily summary (Vercel cron) + throttled error alerts
# ---------------------------------------------------------------------------

ALERT_MIN_INTERVAL_SECONDS = 300.0
_last_alert_at = 0.0


def _admin_destinations(settings: Settings) -> list[int | str]:
    return review.admin_chat_destinations(settings)


async def daily_summary(authorization: str | None) -> dict:
    """Build and send the last-24h ops summary. Guards with CRON_SECRET."""
    settings = await ensure_initialized()
    if not settings.cron_secret:
        logger.warning("daily_summary called but CRON_SECRET is not configured")
        return {"ok": False, "error": "CRON_SECRET not configured"}
    if authorization != f"Bearer {settings.cron_secret}":
        return {"ok": False, "error": "unauthorized"}

    cutoff = datetime.utcnow() - timedelta(hours=24)
    async with session_scope() as session:
        by_type = (
            await session.execute(
                select(
                    Transaction.type,
                    Transaction.status,
                    func.count(Transaction.tx_id),
                    func.coalesce(func.sum(Transaction.amount_usd), 0),
                )
                .where(Transaction.created_at >= cutoff)
                .group_by(Transaction.type, Transaction.status)
            )
        ).all()
        per_chain = (
            await session.execute(
                select(
                    Transaction.coin,
                    Transaction.chain,
                    func.count(Transaction.tx_id),
                    func.coalesce(func.sum(Transaction.amount_usd), 0),
                )
                .where(
                    Transaction.created_at >= cutoff,
                    Transaction.type == "wallet_deposit",
                    Transaction.status == "approved",
                )
                .group_by(Transaction.coin, Transaction.chain)
            )
        ).all()
        pending_count = (
            await session.execute(
                select(func.count(Transaction.tx_id)).where(Transaction.status == "pending")
            )
        ).scalar_one()
        new_users = (
            await session.execute(
                select(func.count(User.user_id)).where(User.first_seen_at >= cutoff)
            )
        ).scalar_one()
        total_users = (await session.execute(select(func.count(User.user_id)))).scalar_one()
        invited_total = (
            await session.execute(select(func.count(User.user_id)).where(User.referred_by.isnot(None)))
        ).scalar_one()
        invited_24h = (
            await session.execute(
                select(func.count(User.user_id)).where(
                    User.referred_by.isnot(None), User.first_seen_at >= cutoff
                )
            )
        ).scalar_one()
        converted = (
            await session.execute(
                select(func.count(func.distinct(Transaction.user_id)))
                .where(Transaction.user_id.in_(select(User.user_id).where(User.referred_by.isnot(None))))
            )
        ).scalar_one()

    labels = {
        "express_sell": "SAFE SELL",
        "wallet_deposit": "Wallet deposit",
        "withdrawal": "Withdrawal",
    }
    lines = ["📊 Daily Summary — last 24h", ""]
    if by_type:
        for tx_type, status, count, volume in sorted(by_type):
            label = labels.get(tx_type, tx_type)
            icon = {"approved": "✅", "pending": "⏳", "rejected": "❌", "cancelled": "🚫"}.get(status, "•")
            lines.append(f"{icon} {label} ({status}): {count} — ${float(volume):,.2f}")
    else:
        lines.append("No transactions in the last 24h.")
    if per_chain:
        lines.append("")
        lines.append("Approved wallet deposits per network:")
        for coin, chain, count, volume in sorted(per_chain):
            lines.append(f"🪙 {coin or '-'} on {chain or '-'}: {count} — ${float(volume):,.2f}")
    lines.extend(
        [
            "",
            f"⏳ Pending right now: {pending_count}",
            f"👥 Users: {total_users} total, {new_users} new in 24h",
            referral_digest_line(invited_total, invited_24h, converted),
        ]
    )
    text = "\n".join(lines)
    bot = Bot(token=settings.bot_token)
    delivered = 0
    try:
        for chat_id in _admin_destinations(settings):
            try:
                await bot.send_message(chat_id, text)
                delivered += 1
            except (TelegramBadRequest, TelegramForbiddenError):
                continue

        # --- Channel marketing drip (guarded by watermarks in bot_state) ---
        posted = await _channel_marketing_pass(settings, bot)
    finally:
        await bot.session.close()
    return {"ok": True, "delivered": delivered, "pending": pending_count, "new_users": new_users, "channel_posts": posted}


def referral_digest_line(invited_total: int, invited_24h: int, converted: int) -> str:
    rate = (converted / invited_total * 100) if invited_total else 0.0
    return f"🎁 Referrals: {invited_total} invited ({invited_24h} in 24h) · {converted} converted ({rate:.0f}%)"


TRUST_FEED_INTERVAL_SECONDS = 3 * 60 * 60  # "deals just now" post, max every 3h
RATES_POST_INTERVAL_SECONDS = 23 * 60 * 60  # rates broadcast, roughly daily


def trust_feed_text(count: int, volume: float, avg_rating: float | None) -> str | None:
    if count <= 0:
        return None
    lines = [
        "✅ TRUSTED ESCROW — activity in the last 3 hours",
        "",
        f"🤝 {count} deal{'s' if count != 1 else ''} completed",
        f"💵 ${volume:,.2f} safe-sold",
    ]
    if avg_rating is not None:
        lines.append(f"⭐ {avg_rating:.1f}/5 average rating")
    lines.append("")
    lines.append("Sell crypto for INR in ~60 seconds — tap SAFE SELL in the bot. 🚀")
    return "\n".join(lines)


def rates_broadcast_text(tiers: list[tuple[str, Any, Any, Any]]) -> str | None:
    """A compact channel post listing the best rate per payment mode."""
    if not tiers:
        return None
    icons = {"UPI": "💳", "IMPS": "🏦", "CDM": "🏧", "GBP": "💷"}
    per_mode: dict[str, list[float]] = {}
    for row in tiers:
        mode = str(row[0]).upper()
        try:
            per_mode.setdefault(mode, []).append(float(row[3]))
        except (TypeError, ValueError):
            continue
    if not per_mode:
        return None
    lines = ["📈 Today's MARCO Rates — sell crypto for INR", ""]
    for mode in sorted(per_mode):
        rates = per_mode[mode]
        spread = f"{min(rates):.2f}" if min(rates) == max(rates) else f"{min(rates):.2f}–{max(rates):.2f}"
        lines.append(f"{icons.get(mode, '💸')} {mode}: {spread} ₹/$")
    lines.append("")
    lines.append("Open the bot → SAFE SELL. Verified payouts, receipts & ratings. ✅")
    return "\n".join(lines)


async def _channel_marketing_pass(settings, bot: Bot) -> int:
    """Trust feed (3h) + daily rates broadcast to the ads channel.

    Watermarks live in bot_state, so this pass can run on any cron cadence
    and will only post when due. Any channel hiccup is swallowed — ops must
    never fail because marketing did.
    """
    if not settings.ads_channel_id:
        return 0
    posted = 0
    now = datetime.utcnow()
    try:
        async with session_scope() as session:
            state = await get_bot_state(session)

            if not throttled(state, "feed_last_at", TRUST_FEED_INTERVAL_SECONDS, now=now):
                since = now - timedelta(seconds=TRUST_FEED_INTERVAL_SECONDS)
                count, volume, avg_rating = (
                    await session.execute(
                        select(
                            func.count(Transaction.tx_id),
                            func.coalesce(func.sum(Transaction.amount_usd), 0),
                            func.avg(Transaction.rating),
                        ).where(
                            Transaction.status == "approved",
                            Transaction.type.in_(["express_sell", "withdrawal"]),
                            Transaction.resolved_at >= since,
                        )
                    )
                ).one()
                text = trust_feed_text(int(count), float(volume or 0), float(avg_rating) if avg_rating is not None else None)
                if text:
                    await bot.send_message(settings.ads_channel_id, text)
                    posted += 1
                state = await set_bot_state_keys(session, {"feed_last_at": now.isoformat()})

            if not throttled(state, "rates_posted_at", RATES_POST_INTERVAL_SECONDS, now=now):
                tiers = (
                    await session.execute(
                        select(RateTier.payment_mode, RateTier.min_usd, RateTier.max_usd, RateTier.rate_inr)
                    )
                ).all()
                text = rates_broadcast_text(tiers)
                if text:
                    await bot.send_message(settings.ads_channel_id, text)
                    posted += 1
                await set_bot_state_keys(session, {"rates_posted_at": now.isoformat()})
    except (TelegramBadRequest, TelegramForbiddenError, SQLAlchemyError, OSError) as exc:
        logger.warning("channel marketing pass skipped: %r", exc)
    return posted


async def alert_exception(exc: BaseException) -> None:
    """Throttled webhook error alert, telegraphed to admins (≤1 per 5 min)."""
    global _last_alert_at
    now = time.monotonic()
    if now - _last_alert_at < ALERT_MIN_INTERVAL_SECONDS:
        return
    _last_alert_at = now
    logger.warning("alerting admins about webhook error: %r", exc)
    try:
        settings = _settings or load_settings()
        detail = html.escape(repr(exc)[:800])
        bot = Bot(token=settings.bot_token)
        try:
            for chat_id in _admin_destinations(settings):
                await bot.send_message(
                    chat_id,
                    f"🚨 Webhook error (further alerts throttled 5 min):\n<code>{detail}</code>",
                    parse_mode="HTML",
                )
        finally:
            await bot.session.close()
    except Exception:
        logger.exception("failed to alert admins about %r", exc)
