"""Admin review cards and the background on-chain verification task.

A deposit (SAFE SELL / wallet top-up) only becomes creditable when:

1. the user submits a real transaction hash, and
2. `run_verification_task` confirms it on-chain (chainverify), and
3. an admin clicks Approve (guard in handlers/admin.py).

Chains without an automatic verifier fall back to verify_status="manual"
and keep the old screenshot-based flow.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from . import keyboards as kb
from .config import Settings
from .db import session_scope
from .models import Transaction, User

VERIFIABLE_TYPES = {"express_sell", "wallet_deposit"}

MAX_ATTEMPTS = 18          # ~6 minutes total with the interval below
ATTEMPT_INTERVAL_SECONDS = 20

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
    return "\nOn-Chain Verify: ⚠️ MANUAL (no verifier for this chain — screenshot only)"


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


async def run_verification_task(settings: Settings, bot: Bot, tx_id: int) -> None:
    """Poll chain APIs until the deposit tx verifies, fails, or times out."""
    from . import chainverify  # local import avoids a module cycle

    try:
        for attempt in range(MAX_ATTEMPTS):
            async with session_scope() as session:
                tx = await session.get(Transaction, tx_id)
                if not tx or tx.status != "pending" or tx.verify_status != "verifying":
                    return
                token = tx.coin or ""
                chain = tx.chain or ""
                address = tx.deposit_address or ""
                expected = Decimal(str(tx.amount_usd))
                tx_hash = tx.chain_tx_hash or ""

            result = await chainverify.verify_payment(settings, token, chain, address, expected, tx_hash)

            if result.status == chainverify.STATUS_PENDING and attempt < MAX_ATTEMPTS - 1:
                await asyncio.sleep(ATTEMPT_INTERVAL_SECONDS)
                continue

            final_status: str
            detail: str
            if result.status == chainverify.STATUS_VERIFIED:
                final_status = "verified"
                detail = result.detail
            elif result.status == chainverify.STATUS_PENDING:
                final_status = "failed"
                detail = f"Not confirmed on-chain within {MAX_ATTEMPTS * ATTEMPT_INTERVAL_SECONDS // 60} minutes. Recheck with /recheck {tx_id} once it confirms."
            else:
                final_status = "failed"
                detail = result.detail or "verification failed"

            user: User | None = None
            async with session_scope() as session:
                tx = await session.get(Transaction, tx_id)
                if not tx or tx.status != "pending" or tx.verify_status != "verifying":
                    return  # admin resolved it while we were verifying
                tx.verify_status = final_status
                tx.verify_detail = detail
                if result.amount is not None:
                    tx.verified_amount = result.amount
                user = await session.get(User, tx.user_id)

            if user is None:
                return

            if final_status == "verified":
                await _notify_user(
                    bot,
                    user.user_id,
                    "✅ Payment confirmed on-chain!\n\n"
                    f"{detail}\n\n"
                    "Your transaction is waiting for admin approval. "
                    "This usually takes a few minutes ⚡",
                )
            else:
                await _notify_user(
                    bot,
                    user.user_id,
                    "⚠️ We could not confirm your payment on-chain.\n\n"
                    "Our team will review it shortly. If this takes long, please contact support.",
                )
            await notify_admin_review(bot, settings, user, tx)
            return
    except Exception:
        logger.exception("Verification task crashed for TX %s", tx_id)
