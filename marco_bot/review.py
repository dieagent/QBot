"""Admin review cards and on-chain verification orchestration.

A deposit (SAFE SELL / wallet top-up) only becomes creditable when:

1. the user submits a real transaction hash, and
2. verification confirms it on-chain (chainverify), and
3. an admin clicks Approve (guard in handlers/admin.py).

Two runtimes are supported:

- **Long polling** (local / Railway): a background asyncio task polls for
  up to ~6 minutes (`schedule_verification` spawns `run_verification_task`).
- **Serverless webhooks** (Vercel): background tasks die with the request,
  so verification happens via short inline attempts at submit time, a
  per-transaction "check status" button, `/recheck`, and `sweep_pending`
  which retries a few pending deposits on each incoming webhook update.

Chains without an automatic verifier fall back to verify_status="manual"
and keep the old screenshot-based flow.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from sqlalchemy import func, select

from . import keyboards as kb
from . import messages as msg
from .config import Settings
from .db import session_scope
from .models import Transaction, User, utcnow
from .services import get_bot_state, set_bot_state_keys, throttled
from .translations import lang_of

VERIFIABLE_TYPES = {"express_sell", "wallet_deposit"}

MAX_ATTEMPTS = 18          # ~6 minutes total with the interval below
ATTEMPT_INTERVAL_SECONDS = 20

# Serverless (webhook) behaviour: attempts done inline at submit time.
SERVERLESS_INLINE_ATTEMPTS = 2
SERVERLESS_INLINE_INTERVAL = 2.5
# Sweep budget per incoming webhook update.
SWEEP_MAX_TXS = 3
SWEEP_PER_TX_TIMEOUT = 6.0

logger = logging.getLogger(__name__)


def verification_block(tx: Transaction) -> str:
    """Short status block shown on the admin card."""
    status = tx.verify_status
    if tx.type == "withdrawal":
        return ""
    if status == "verifying":
        return f"\nOn-Chain Verify: ⏳ checking...\nHash: {tx.chain_tx_hash or '-'}"
    if status == "verified":
        amount = f"{tx.verified_amount}" if tx.verified_amount is not None else "?"
        return (
            "\nOn-Chain Verify: ✅ VERIFIED"
            f"\nReceived: {amount} {tx.coin or ''}"
            f"\nHash: {tx.chain_tx_hash or '-'}"
            + (f"\n{tx.verify_detail}" if tx.verify_detail else "")
        )
    if status == "failed":
        return (
            "\nOn-Chain Verify: ❌ FAILED"
            + (f"\nReason: {tx.verify_detail}" if tx.verify_detail else "")
            + f"\nHash: {tx.chain_tx_hash or '-'}"
        )
    block = "\nOn-Chain Verify: ⚠️ MANUAL"
    if tx.chain_tx_hash:
        block += f"\nHash: {tx.chain_tx_hash}"
        from . import chainverify

        url = chainverify.explorer_url(tx.chain or "", tx.chain_tx_hash)
        if url:
            block += f"\nExplorer: {url}"
    else:
        block += " (no verifier for this chain — screenshot only)"
    return block


def admin_review_text(user: User, tx: Transaction) -> str:
    username = f"@{user.username}" if user.username else str(user.user_id)
    if tx.type == "withdrawal":
        return f"""🧾 Pending Withdrawal

TX: {tx.tx_id}
User: {username}
Telegram ID: {user.user_id}
Amount: ${tx.amount_usd:.2f}
Destination:
{tx.withdrawal_destination}"""
    return (
        f"""🧾 Pending Verification

TX: {tx.tx_id}
Type: {tx.type}
User: {username}
Telegram ID: {user.user_id}
Token: {tx.coin}
Chain: {tx.chain}
Amount USD: ${tx.amount_usd:.2f}
Expected INR: ₹{tx.amount_inr:.2f}
Payment Mode: {tx.payment_mode}
Deposit Address:
{tx.deposit_address}"""
        + verification_block(tx)
    )


async def notify_admin_review(bot: Bot, settings: Settings, user: User, tx: Transaction) -> None:
    caption = admin_review_text(user, tx)
    destinations: list[int | str] = []
    if settings.admin_review_chat_id:
        destinations.append(settings.admin_review_chat_id)
    destinations.extend(settings.admin_ids)
    for chat_id in destinations:
        try:
            if tx.proof_file_id:
                await bot.send_photo(chat_id, tx.proof_file_id, caption=caption, reply_markup=kb.admin_review(tx.tx_id))
            else:
                await bot.send_message(chat_id, caption, reply_markup=kb.admin_review(tx.tx_id))
        except (TelegramBadRequest, TelegramForbiddenError):
            continue


async def _notify_user(bot: Bot, user_id: int, text: str) -> None:
    try:
        await bot.send_message(user_id, text)
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


PENDING_AGE_MINUTES = 45          # a deal older than this counts as "stuck"
AGING_ALERT_INTERVAL_SECONDS = 30 * 60  # re-alert at most every 30 min while stuck
_AGING_STATE_KEY = "last_aging_alert_at"
AGING_ALERT_SAMPLE = 5


def admin_chat_destinations(settings: Settings) -> list[int | str]:
    """Every chat that should receive ops notifications (alerts, summaries)."""
    destinations: list[int | str] = []
    if settings.admin_review_chat_id:
        destinations.append(settings.admin_review_chat_id)
    destinations.extend(settings.admin_ids)
    return destinations


def aging_alert_text(stuck: list[Transaction], total: int, age_minutes: int, *, now=None) -> str:
    now = now or utcnow()
    plural = "s" if total != 1 else ""
    lines = [f"⏰ {total} deal{plural} pending ≥{age_minutes} min — users are waiting!", ""]
    for tx in stuck[:AGING_ALERT_SAMPLE]:
        age = max(0, int((now - tx.created_at).total_seconds() // 60)) if tx.created_at else age_minutes
        label = tx.type.replace("_", " ")
        lines.append(f"⏳ TX {tx.tx_id} · {label} · ${tx.amount_usd:.2f} · user {tx.user_id} · {age} min old")
    if total > AGING_ALERT_SAMPLE:
        lines.append(f"... and {total - AGING_ALERT_SAMPLE} more")
    lines.append("")
    lines.append("Work the queue with /pending 📋")
    return "\n".join(lines)


async def maybe_send_aging_alert(settings: Settings, bot: Bot) -> bool:
    """Ping admins when deals sit pending too long. Throttled in bot_state."""
    cutoff = utcnow() - timedelta(minutes=PENDING_AGE_MINUTES)
    async with session_scope() as session:
        total = (
            await session.execute(
                select(func.count(Transaction.tx_id)).where(
                    Transaction.status == "pending", Transaction.created_at < cutoff
                )
            )
        ).scalar_one()
        if not total:
            return False
        state = await get_bot_state(session)
        if throttled(state, _AGING_STATE_KEY, AGING_ALERT_INTERVAL_SECONDS):
            return False
        rows = (
            await session.execute(
                select(Transaction)
                .where(Transaction.status == "pending", Transaction.created_at < cutoff)
                .order_by(Transaction.created_at)
                .limit(AGING_ALERT_SAMPLE)
            )
        ).scalars().all()
        await set_bot_state_keys(session, {_AGING_STATE_KEY: utcnow().isoformat()})

    text = aging_alert_text(rows, total, PENDING_AGE_MINUTES)
    for chat_id in admin_chat_destinations(settings):
        try:
            await bot.send_message(chat_id, text)
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
    return True


# ---------------------------------------------------------------------------
# Core one-attempt verification
# ---------------------------------------------------------------------------


async def verify_tx_attempt(settings: Settings, bot: Bot, tx_id: int) -> str:
    """Run a single on-chain verification attempt for one transaction.

    Returns the resulting verify_status: "verified", "failed" or "pending"
    (still confirming — row left in "verifying"). Rows that disappeared or
    were already resolved return "resolved". Notifications are sent when a
    final state is reached.
    """
    from . import chainverify  # local import avoids a module cycle

    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx or tx.status != "pending" or tx.verify_status != "verifying":
            return "resolved"
        token = tx.coin or ""
        chain = tx.chain or ""
        address = tx.deposit_address or ""
        expected = Decimal(str(tx.amount_usd))
        tx_hash = tx.chain_tx_hash or ""

    result = await chainverify.verify_payment(settings, token, chain, address, expected, tx_hash)

    if result.status == chainverify.STATUS_PENDING:
        return "pending"

    final_status = "verified" if result.status == chainverify.STATUS_VERIFIED else "failed"
    detail = result.detail or ("verification failed" if final_status == "failed" else "")

    user: User | None = None
    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx or tx.status != "pending" or tx.verify_status != "verifying":
            return "resolved"  # admin resolved it while we were verifying
        tx.verify_status = final_status
        tx.verify_detail = detail
        if result.amount is not None:
            tx.verified_amount = result.amount
        user = await session.get(User, tx.user_id)

    if user is None:
        return final_status

    if final_status == "verified":
        await _notify_user(
            bot,
            user.user_id,
            msg.verified_user_text(detail, lang_of(user)),
        )
    else:
        await _notify_user(
            bot,
            user.user_id,
            msg.failed_user_text(lang_of(user)),
        )
    await notify_admin_review(bot, settings, user, tx)
    return final_status


# ---------------------------------------------------------------------------
# Long-polling runtime: background polling task
# ---------------------------------------------------------------------------

async def run_verification_task(settings: Settings, bot: Bot, tx_id: int) -> None:
    """Poll chain APIs until the deposit tx verifies, fails, or times out."""
    try:
        for attempt in range(MAX_ATTEMPTS):
            outcome = await verify_tx_attempt(settings, bot, tx_id)
            if outcome != "pending":
                return
            await asyncio.sleep(ATTEMPT_INTERVAL_SECONDS)

        # Give up waiting: mark failed with an actionable note.
        user: User | None = None
        async with session_scope() as session:
            tx = await session.get(Transaction, tx_id)
            if not tx or tx.status != "pending" or tx.verify_status != "verifying":
                return
            tx.verify_status = "failed"
            tx.verify_detail = f"Not confirmed on-chain within {MAX_ATTEMPTS * ATTEMPT_INTERVAL_SECONDS // 60} minutes. Recheck with /recheck {tx_id} once it confirms."
            user = await session.get(User, tx.user_id)
        if user is not None:
            await _notify_user(
                bot,
                user.user_id,
                msg.failed_user_text(lang_of(user)),
            )
            await notify_admin_review(bot, settings, user, tx)
    except Exception:
        logger.exception("Verification task crashed for TX %s", tx_id)


async def _verify_inline(settings: Settings, bot: Bot, tx_id: int) -> str:
    """Bounded verification usable inside a single serverless request."""
    outcome = "pending"
    for attempt in range(SERVERLESS_INLINE_ATTEMPTS):
        outcome = await verify_tx_attempt(settings, bot, tx_id)
        if outcome != "pending":
            return outcome
        if attempt < SERVERLESS_INLINE_ATTEMPTS - 1:
            await asyncio.sleep(SERVERLESS_INLINE_INTERVAL)
    return outcome


async def schedule_verification(settings: Settings, bot: Bot, tx_id: int) -> str | None:
    """Dispatch verification appropriate for the runtime.

    Polling mode: spawns the background task (returns None immediately).
    Webhook mode: runs bounded inline attempts and returns the outcome so
    the caller can tell the user what happened right away.
    """
    if not settings.webhook_mode:
        asyncio.create_task(run_verification_task(settings, bot, tx_id))
        return None
    return await _verify_inline(settings, bot, tx_id)


# ---------------------------------------------------------------------------
# Serverless sweep: retry a few pending deposits per incoming webhook update
# ---------------------------------------------------------------------------

async def sweep_pending(settings: Settings, bot: Bot, max_txs: int = SWEEP_MAX_TXS) -> int:
    """Run one bounded verification attempt for each still-pending deposit.

    Called on incoming webhook updates so deposits keep getting re-checked
    even though serverless functions cannot host background tasks.
    Returns how many transactions were checked.
    """
    from sqlalchemy import select

    async with session_scope() as session:
        rows = await session.execute(
            select(Transaction.tx_id)
            .where(Transaction.status == "pending", Transaction.verify_status == "verifying")
            .order_by(Transaction.created_at)
            .limit(max_txs)
        )
        tx_ids = [row[0] for row in rows.all()]

    checked = 0
    for tx_id in tx_ids:
        try:
            async with asyncio.timeout(SWEEP_PER_TX_TIMEOUT):
                await verify_tx_attempt(settings, bot, tx_id)
                checked += 1
        except Exception:  # sweep must never break update handling
            logger.warning("Sweep check timed out/failed for TX %s", tx_id)

    # Aging-queue escalation rides along with the sweep cadence (throttled
    # in bot_state) so both serverless webhooks and polling loops ping admins.
    try:
        await maybe_send_aging_alert(settings, bot)
    except Exception:
        logger.warning("aging-queue alert failed", exc_info=True)
    return checked
