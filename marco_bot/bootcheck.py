"""Boot-time self-check (runs on every serverless cold start).

Validates the live config and sends the admins a Telegram warning when
something would break users (bad token, missing deposit addresses, no admin
chat configured, unprotected endpoints). Healthy boots stay quiet — log line
only, so scaling up/down never spams the review chat. Alerts are throttled in
the DB (bot_state in global_stats) so crash-looping deployments also stay quiet.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from . import constants as c
from .config import Settings
from .db import session_scope
from .models import utcnow
from .review import admin_chat_destinations
from .services import deposit_address, get_bot_state, set_bot_state_keys, throttled

logger = logging.getLogger(__name__)

BOOT_ALERT_INTERVAL_SECONDS = 6 * 60 * 60  # at most one boot warning every 6h
_BOOT_STATE_KEY = "last_boot_alert_at"

# Every (token, chain) the deposit UI offers — mirrors keyboards.express_chains.
DEPOSIT_COMBOS: list[tuple[str, str]] = [
    *[("USDT", chain) for chain in c.EXPRESS_USDT_CHAINS],
    *[("BTC", chain) for chain in c.BTC_CHAINS],
    *[("ETH", chain) for chain in ["BEP20", "ERC20", "MATIC", "TRC20"]],
]


def is_configured_address(raw: str) -> bool:
    # services.deposit_address falls back to a CONFIGURE_... placeholder
    # when no real address exists for a combo.
    return not raw.startswith("CONFIGURE_")


def missing_deposit_addresses(settings: Settings) -> list[str]:
    return [f"{token}-{chain}" for token, chain in DEPOSIT_COMBOS if not is_configured_address(deposit_address(settings, token, chain))]


def boot_alert_text(warnings: list[str]) -> str:
    lines = ["⚠️ MARCO boot self-check — fix these:", ""]
    lines.extend(f"• {warning}" for warning in warnings)
    lines.append("")
    lines.append("The bot is running, but users may hit broken flows until this is fixed.")
    return "\n".join(lines)


async def collect_warnings(settings: Settings, bot: Bot) -> list[str]:
    warnings: list[str] = []
    try:
        await bot.get_me()
    except Exception as exc:  # token invalid or Telegram unreachable
        warnings.append(f"Bot token / Telegram API: {exc}")
    for combo in missing_deposit_addresses(settings):
        warnings.append(f"No deposit address configured for {combo}")
    has_review_chat = bool(settings.admin_review_chat_id)
    has_admins = bool(settings.admin_ids)
    if not has_review_chat and not has_admins:
        warnings.append("No admin review chat and no admin IDs — approvals would go nowhere")
    if not settings.webhook_secret:
        warnings.append("WEBHOOK_SECRET not set — webhook endpoint accepts anything")
    if not settings.cron_secret:
        warnings.append("CRON_SECRET not set — daily admin summary is disabled")
    return warnings


async def run_boot_check(settings: Settings) -> None:
    """Run the checks and DM the admins on problems. Never raises into boot."""
    bot: Bot | None = None
    try:
        bot = Bot(token=settings.bot_token)
        warnings = await collect_warnings(settings, bot)
        if not warnings:
            logger.info("boot self-check: all good")
            return
        logger.warning("boot self-check warnings: %s", "; ".join(warnings))
        async with session_scope() as session:
            state = await get_bot_state(session)
            if throttled(state, _BOOT_STATE_KEY, BOOT_ALERT_INTERVAL_SECONDS):
                logger.info("boot alert throttled (sent within 6h)")
                return
            await set_bot_state_keys(session, {_BOOT_STATE_KEY: utcnow().isoformat()})
        for chat_id in admin_chat_destinations(settings):
            try:
                await bot.send_message(chat_id, boot_alert_text(warnings))
            except (TelegramBadRequest, TelegramForbiddenError):
                continue
    except Exception:
        logger.exception("boot self-check crashed (ignored, boot continues)")
    finally:
        if bot is not None:
            try:
                await bot.session.close()
            except Exception:
                pass
