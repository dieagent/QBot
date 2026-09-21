from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.enums import MessageEntityType
from aiogram.types import BufferedInputFile, CallbackQuery, Message, MessageEntity
from sqlalchemy import func, select

from .. import keyboards as kb
from .. import messages as msg
from .. import review
from ..config import Settings
from ..db import session_scope
from ..models import GlobalStats, PaymentMode, RateTier, Transaction, User, utcnow
from ..services import (
    add_safe_sell_stats,
    as_money,
    credit_amount_for,
    get_bot_state,
    parse_decimal,
    reset_today_if_needed,
    set_bot_state_keys,
)
from ..translations import lang_of

EXPORT_ROW_CAP = 5000

# After an admin approves a payout-type deal, they get a short-lived prompt
# asking for the UTR/reference right there (auto /receipt).
RECEIPT_PROMPT_MINUTES = 10
RECEIPT_PROMPT_TYPES = {"express_sell", "withdrawal"}
RECEIPT_SKIP_WORDS = {"skip", "no", "later", "cancel", "/skip", "/cancel"}


def pending_receipt_key(admin_id: int) -> str:
    return f"pending_receipt:{admin_id}"


def new_pending_receipt(tx_id: int, now: datetime) -> str:
    return json.dumps({"tx_id": tx_id, "until": (now + timedelta(minutes=RECEIPT_PROMPT_MINUTES)).isoformat()})


def parse_pending_receipt(raw: object, now: datetime) -> int | None:
    """The pending TX id when a receipt prompt is active; None otherwise."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    try:
        until = datetime.fromisoformat(str(data.get("until", "")))
    except (ValueError, TypeError, AttributeError):
        return None
    if now >= until:
        return None
    tx_id = data.get("tx_id")
    return tx_id if isinstance(tx_id, int) else None


def is_skip(text: str) -> bool:
    return (text or "").strip().lower() in RECEIPT_SKIP_WORDS


def normalize_reference(text: str) -> str | None:
    ref = (text or "").strip()
    if not ref or len(ref) > 64 or ref.startswith("/"):
        return None
    return ref


# ---------------------------------------------------------------------------
# Support-reply prompt + rate wizard state machines (10-minute admin windows)
# ---------------------------------------------------------------------------

SUPPORT_REPLY_MINUTES = 10


def support_reply_key(admin_id: int) -> str:
    return f"support_reply:{admin_id}"


def new_support_reply(user_id: int, now: datetime) -> str:
    return json.dumps({"user_id": user_id, "until": (now + timedelta(minutes=SUPPORT_REPLY_MINUTES)).isoformat()})


def parse_support_reply(raw: object, now: datetime) -> int | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    try:
        until = datetime.fromisoformat(str(data.get("until", "")))
    except (ValueError, TypeError, AttributeError):
        return None
    if now >= until:
        return None
    user_id = data.get("user_id")
    return user_id if isinstance(user_id, int) else None


RATEWIZ_MINUTES = 5
RATE_WIZARD_STEPS = ("min", "max", "rate")


def ratewiz_key(admin_id: int) -> str:
    return f"ratewiz:{admin_id}"


def new_ratewiz(mode: str, now: datetime) -> str:
    return json.dumps({"mode": mode.upper(), "step": "min", "values": {}, "until": (now + timedelta(minutes=RATEWIZ_MINUTES)).isoformat()})


def parse_ratewiz(raw: object, now: datetime) -> dict | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    try:
        until = datetime.fromisoformat(str(data.get("until", "")))
    except (ValueError, TypeError, AttributeError):
        return None
    if now >= until or data.get("step") not in RATE_WIZARD_STEPS or not isinstance(data.get("mode"), str):
        return None
    if not isinstance(data.get("values"), dict):
        data["values"] = {}
    return data


def ratewiz_next_step(step: str) -> str | None:
    idx = RATE_WIZARD_STEPS.index(step) + 1
    return RATE_WIZARD_STEPS[idx] if idx < len(RATE_WIZARD_STEPS) else None


RATEWIZ_PROMPTS = {
    "min": "Minimum $ of the tier? (plain number)",
    "max": "Maximum $ of the tier? (number, or + / 'none' for open-ended)",
    "rate": "INR rate for this tier? (₹ per $1)",
}


async def _save_rate_tier(session, payment_mode: str, min_usd: Decimal, max_usd: Decimal | None, rate: Decimal) -> None:
    """Shared upsert used by /setrate and the rate wizard."""
    result = await session.execute(
        select(RateTier).where(
            RateTier.payment_mode == payment_mode,
            RateTier.min_usd == min_usd,
            RateTier.max_usd == max_usd,
        )
    )
    tier = result.scalar_one_or_none()
    if not tier:
        tier = RateTier(payment_mode=payment_mode, min_usd=min_usd, max_usd=max_usd, rate_inr=rate)
        session.add(tier)
    else:
        tier.rate_inr = rate

router = Router()
_settings: Settings | None = None


def configure(settings: Settings) -> None:
    global _settings
    _settings = settings


def settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Admin router is not configured.")
    return _settings


def is_admin(user_id: int) -> bool:
    return user_id in settings().admin_ids


def _custom_emoji_ids(entities: list[MessageEntity] | None) -> list[str]:
    ids: list[str] = []
    for entity in entities or []:
        if entity.type == MessageEntityType.CUSTOM_EMOJI and entity.custom_emoji_id:
            ids.append(entity.custom_emoji_id)
    return ids


def extract_custom_emoji_ids(message: Message) -> list[str]:
    ids: list[str] = []
    ids.extend(_custom_emoji_ids(message.entities))
    ids.extend(_custom_emoji_ids(message.caption_entities))
    if message.reply_to_message:
        ids.extend(_custom_emoji_ids(message.reply_to_message.entities))
        ids.extend(_custom_emoji_ids(message.reply_to_message.caption_entities))
    unique_ids: list[str] = []
    for emoji_id in ids:
        if emoji_id not in unique_ids:
            unique_ids.append(emoji_id)
    return unique_ids


@router.message(Command("admin"))
async def admin_help(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await message.answer(
        """MARCO Admin 🔧

📊 Stats & Monitoring:
/pending - show pending review queue
/stats - show global stats
/recheck TX_ID - rerun on-chain verification
/receipt TX_ID PAYOUT_REF - attach payout reference (UPI UTR etc.) & send user a receipt
/export - download transactions CSV (latest 5000)
/emojiids - extract premium custom emoji IDs

⚙️ Payment & Rates:
/mode UPI on|off - toggle payment mode
/rates - show exchange tiers
/setrate UPI 10 600 94.0 - add/update a tier

📢 Broadcast:
/broadcast message text - send to all users

🚫 User Management:
/ban @username or /ban 123456 - ban a user
/unban @username or /unban 123456 - unban a user
/resetadcooldown @username or /resetadcooldown 123456 - remove user's ad cooldown

🔧 Bot Maintenance:
/maintenance on|off - enable/disable maintenance mode"""
    )


@router.message(Command(commands=["emojiids", "emojiiids"]))
async def emoji_ids(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    emoji_ids = extract_custom_emoji_ids(message)
    if not emoji_ids:
        await message.answer(
            "Send /emojiids as a reply to a message that contains premium emojis, or include the premium emojis in the same message."
        )
        return
    lines = ["Custom emoji IDs:"]
    for emoji_id in emoji_ids:
        lines.append(emoji_id)
    await message.answer("\n".join(lines))


@router.message(Command("testemoji"))
async def test_emoji(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    emoji_ids = extract_custom_emoji_ids(message)
    if not emoji_ids:
        await message.answer(
            "Usage: reply to a message containing premium emojis, or include them in this message."
        )
        return

    parts: list[str] = []
    for eid in emoji_ids:
        parts.append(f'<tg-emoji emoji-id="{eid}">🔹</tg-emoji>')

    preview = " ".join(parts)
    ids_line = "\n".join(emoji_ids)
    await message.answer(f"Custom emoji preview:\n{preview}\n\nIDs:\n{ids_line}", parse_mode=ParseMode.HTML)


@router.message(Command("pending"))
async def pending(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.status == "pending")
            .order_by(Transaction.created_at)
            .limit(20)
        )
        rows = result.scalars().all()
        if not rows:
            await message.answer("No pending transactions.")
            return
        lines = ["Pending transactions:"]
        for tx in rows:
            lines.append(f"TX {tx.tx_id} | {tx.type} | user {tx.user_id} | ${tx.amount_usd:.2f}")
        await message.answer("\n".join(lines))


@router.message(Command("recheck"))
async def recheck_verification(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /recheck TX_ID")
        return
    tx_id = int(parts[1])
    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx:
            await message.answer(f"TX {tx_id} not found.")
            return
        if tx.type not in review.VERIFIABLE_TYPES or not tx.chain_tx_hash:
            await message.answer(f"TX {tx_id} has no on-chain verification to rerun.")
            return
        if tx.status != "pending":
            await message.answer(f"TX {tx_id} is already {tx.status}.")
            return
        if tx.verify_status == "verified":
            await message.answer(f"TX {tx_id} is already verified — you can approve it from the review card.")
            return
        tx.verify_status = "verifying"
        tx.verify_detail = None
    await review.schedule_verification(settings(), message.bot, tx_id)
    await message.answer(f"🔎 Verification re-run started for TX {tx_id}.")


async def _deliver_payout_receipt(bot, tx_id: int, reference: str) -> tuple[bool, str]:
    """Attach the payout reference and DM the user their receipt + rating card.

    Returns (saved?, deliver-warning/"").
    """
    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx:
            return False, f"TX {tx_id} not found."
        if tx.status != "approved":
            return False, f"TX {tx_id} is {tx.status} — approve it first, then send the receipt."
        tx.payout_reference = reference
        user = await session.get(User, tx.user_id)
        delivered = False
        if user:
            try:
                await bot.send_message(
                    user.user_id,
                    msg.payout_receipt_render(tx, lang_of(user)),
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb.receipt_actions(tx.tx_id),
                )
                delivered = True
            except (TelegramBadRequest, TelegramForbiddenError):
                delivered = False
    if delivered:
        return True, ""
    return True, f"reference saved on TX {tx_id}, but the user could not be DM'd (bot blocked?)."


@router.message(Command("receipt"))
async def payout_receipt(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].strip():
        await message.answer("Usage: /receipt TX_ID PAYOUT_REFERENCE (e.g. /receipt 42 831204912345)")
        return
    tx_id = int(parts[1])
    ok, note = await _deliver_payout_receipt(message.bot, tx_id, parts[2].strip())
    if ok and not note:
        await message.answer(f"✅ Receipt for TX {tx_id} delivered (ref: {parts[2].strip()}).")
    elif ok:
        await message.answer(f"⚠️ {note.capitalize()}.")
    else:
        await message.answer(note)


@router.message(Command("export"))
async def export_transactions(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        result = await session.execute(
            select(Transaction).order_by(Transaction.created_at.desc()).limit(EXPORT_ROW_CAP)
        )
        rows = list(result.scalars().all())
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "tx_id", "user_id", "type", "status", "verify_status", "amount_usd", "amount_inr",
        "coin", "chain", "payment_mode", "deposit_address", "chain_tx_hash",
        "verified_amount", "payout_reference", "admin_id", "created_at", "resolved_at",
    ])
    for tx in rows:
        writer.writerow([
            tx.tx_id, tx.user_id, tx.type, tx.status, tx.verify_status or "",
            str(tx.amount_usd), str(tx.amount_inr), tx.coin or "", tx.chain or "",
            tx.payment_mode or "", tx.deposit_address or "", tx.chain_tx_hash or "",
            "" if tx.verified_amount is None else str(tx.verified_amount),
            tx.payout_reference or "", tx.admin_id or "",
            tx.created_at.isoformat(), tx.resolved_at.isoformat() if tx.resolved_at else "",
        ])
    payload = buffer.getvalue().encode("utf-8-sig")  # BOM so Excel renders UTF-8 correctly
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    await message.answer_document(
        BufferedInputFile(payload, filename=f"transactions_{stamp}.csv"),
        caption=f"📤 Latest {len(rows)} transactions (cap {EXPORT_ROW_CAP}).",
    )


@router.message(Command("stats"))
async def admin_stats(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        stats = await session.get(GlobalStats, 1)
        if not stats:
            stats = GlobalStats(id=1)
            session.add(stats)
            await session.flush()
        await reset_today_if_needed(session, stats, settings().timezone)
        await message.answer(
            msg.global_stats(stats.total_safe_sold_amount, stats.today_safe_sold_amount, stats.total_deals_completed),
            parse_mode=ParseMode.HTML,
        )


@router.message(Command("mode"))
async def mode_toggle(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or parts[2].lower() not in {"on", "off"}:
        await message.answer("Usage: /mode UPI on|off")
        return
    payment_mode = parts[1].upper()
    available = parts[2].lower() == "on"
    async with session_scope() as session:
        mode = await session.get(PaymentMode, payment_mode)
        if not mode:
            mode = PaymentMode(payment_mode=payment_mode, available=available)
            session.add(mode)
        mode.available = available
        flag = "🟢 Available" if available else "🔴 Unavailable"
        await message.answer(f"{payment_mode} is now {flag}.")


@router.message(Command("rates"))
async def rates(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        result = await session.execute(select(RateTier).order_by(RateTier.payment_mode, RateTier.min_usd))
        rows = result.scalars().all()
        if not rows:
            await message.answer("No rate tiers configured.")
            return
        lines = ["Rate tiers:"]
        for tier in rows:
            maximum = "+" if tier.max_usd is None else f"-${tier.max_usd:.0f}"
            lines.append(f"{tier.payment_mode}: ${tier.min_usd:.0f}{maximum} = {tier.rate_inr:.1f}₹")
        await message.answer("\n".join(lines))


@router.message(Command("setrate"))
async def set_rate(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 5:
        await message.answer("Usage: /setrate UPI 10 600 94.0 (use + for open-ended max)")
        return
    payment_mode = parts[1].upper()
    min_usd = parse_decimal(parts[2])
    max_usd = None if parts[3] == "+" else parse_decimal(parts[3])
    rate = parse_decimal(parts[4])
    if min_usd is None or rate is None or (parts[3] != "+" and max_usd is None):
        await message.answer("Invalid numeric rate tier.")
        return
    async with session_scope() as session:
        await _save_rate_tier(session, payment_mode, min_usd, max_usd, rate)
    await message.answer(f"Saved {payment_mode} tier at {rate:.1f}₹.")


@router.message(Command("rates"))
async def rate_wizard_start(message: Message) -> None:
    """Interactive rate editor — tap a payment mode, then answer 3 questions."""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with session_scope() as session:
        tiers = (
            await session.execute(select(RateTier).order_by(RateTier.payment_mode, RateTier.min_usd))
        ).scalars().all()
    lines = ["🪄 Rate Wizard — current tiers (tap a mode below to edit):"]
    for tier in tiers:
        span = f"${float(tier.min_usd):.0f}–{('+' if tier.max_usd is None else f'${float(tier.max_usd):.0f}')}"
        lines.append(f"• {tier.payment_mode}: {span} → {float(tier.rate_inr):.1f}₹")
    if len(lines) == 1:
        lines.append("(no tiers set yet — the wizard will create one)")
    await message.answer("\n".join(lines), reply_markup=kb.rate_wizard_modes(sorted({t.payment_mode for t in tiers}) or ["UPI", "IMPS", "CDM"]))


@router.callback_query(F.data.startswith("ratewiz:"))
async def rate_wizard_begin(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return
    mode = callback.data.split(":", 1)[1].upper()
    async with session_scope() as session:
        await set_bot_state_keys(session, {ratewiz_key(callback.from_user.id): new_ratewiz(mode, utcnow())})
    await callback.answer()
    await callback.message.answer(f"✏️ Editing {mode} — {RATEWIZ_PROMPTS['min']}\n(5-min window; type anything else or wait to cancel)")


@router.message(Command("broadcast"))
async def broadcast(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("Usage: /broadcast message text")
        return
    sent = 0
    async with session_scope() as session:
        result = await session.execute(select(User.user_id))
        user_ids = [row[0] for row in result.all()]
    for user_id in user_ids:
        try:
            await message.bot.send_message(
                user_id,
                text,
                parse_mode=ParseMode.HTML if "<tg-emoji" in text else None,
            )
            sent += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
    await message.answer(f"Broadcast sent to {sent} users.")


@router.message(Command("ban"))
async def ban_user(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /ban @username or /ban 123456")
        return
    
    user_identifier = parts[1].lstrip('@')
    async with session_scope() as session:
        # Try to find user by username or user_id
        user = None
        if user_identifier.isdigit():
            user = await session.get(User, int(user_identifier))
        else:
            result = await session.execute(select(User).where(User.username == user_identifier))
            user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(f"❌ User '{user_identifier}' not found.")
            return
        
        user.is_locked = True
        await message.answer(f"✅ Banned user {user.username or user.user_id} (ID: {user.user_id})")


@router.message(Command("unban"))
async def unban_user(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /unban @username or /unban 123456")
        return
    
    user_identifier = parts[1].lstrip('@')
    async with session_scope() as session:
        # Try to find user by username or user_id
        user = None
        if user_identifier.isdigit():
            user = await session.get(User, int(user_identifier))
        else:
            result = await session.execute(select(User).where(User.username == user_identifier))
            user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(f"❌ User '{user_identifier}' not found.")
            return
        
        user.is_locked = False
        await message.answer(f"✅ Unbanned user {user.username or user.user_id} (ID: {user.user_id})")


@router.message(Command("resetadcooldown"))
async def reset_ad_cooldown(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /resetadcooldown @username or /resetadcooldown 123456")
        return
    
    user_identifier = parts[1].lstrip('@')
    async with session_scope() as session:
        # Try to find user by username or user_id
        user = None
        if user_identifier.isdigit():
            user = await session.get(User, int(user_identifier))
        else:
            result = await session.execute(select(User).where(User.username == user_identifier))
            user = result.scalar_one_or_none()
        
        if not user:
            await message.answer(f"❌ User '{user_identifier}' not found.")
            return
        
        user.post_ad_cooldown_until = None
        await message.answer(f"✅ Removed ad cooldown for user {user.username or user.user_id} (ID: {user.user_id})")


@router.message(Command("maintenance"))
async def maintenance_mode(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or parts[1].lower() not in {"on", "off", "status"}:
        await message.answer(
            "Usage:\n/maintenance on [minutes] [optional note]\n/maintenance off\n/maintenance status\n(example: /maintenance on 30 bank server slow)"
        )
        return
    verb = parts[1].lower()
    async with session_scope() as session:
        state = await get_bot_state(session)
        if verb == "status":
            note = maintenance_block(state, utcnow())
            await message.answer(f"🔴 Maintenance ON: {note}" if note else "🟢 Maintenance OFF")
            return
        if verb == "off":
            await set_bot_state_keys(session, {"maintenance": None})
            await message.answer("🟢 MAINTENANCE MODE OFF — users can start deals again.")
            return

        until = None
        note = None
        tail = parts[2] if len(parts) > 2 else ""
        tail_parts = tail.split(maxsplit=1)
        if tail_parts and tail_parts[0].isdigit():
            until = (utcnow() + timedelta(minutes=int(tail_parts[0]))).isoformat()
            note = tail_parts[1] if len(tail_parts) > 1 else None
        elif tail:
            note = tail
        await set_bot_state_keys(session, {"maintenance": json.dumps({"on": True, "until": until, "note": note})})
        detail = f" until {datetime.fromisoformat(until):%H:%M UTC}" if until else " until you turn it off"
        await message.answer(f"🔴 MAINTENANCE MODE ON{detail} — new deals are paused and users get a polite hold message.")


def maintenance_block(state: dict, now: datetime) -> str | None:
    """The user-facing hold message while maintenance is active, else None."""
    raw = state.get("maintenance")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("on"):
        return None
    until_raw = data.get("until")
    if until_raw:
        try:
            until = datetime.fromisoformat(str(until_raw))
        except ValueError:
            until = None
        if until is not None and now >= until:
            return None  # auto-expired
    else:
        until = None
    note = str(data.get("note") or "").strip()
    when = f"\n⏱ Back around {until:%H:%M UTC}." if until else ""
    extra = f"\n📌 {note}" if note else ""
    return f"🔧 Quick maintenance break — we're not starting new deals right now." + when + extra + "\nPlease try again shortly 🙏"


@router.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data:
        return
    if not is_admin(callback.from_user.id):
        await callback.answer("Not authorized.", show_alert=True)
        return
    parts = callback.data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        await callback.answer("Invalid admin action.", show_alert=True)
        return
    action = parts[1]
    tx_id = int(parts[2])

    if action == "approve":
        await approve_transaction(callback, tx_id)
    elif action == "reject":
        # Don't reject yet — ask for a one-tap reason first.
        async with session_scope() as session:
            tx = await session.get(Transaction, tx_id)
            if not tx or tx.status != "pending":
                await callback.answer("Transaction is not pending.", show_alert=True)
                return
        try:
            await callback.message.edit_reply_markup(reply_markup=kb.admin_reject_reasons(tx_id))
            await callback.answer("Pick a rejection reason 👇")
        except TelegramBadRequest:
            await callback.answer("Could not swap the keyboard — react from a fresh /pending card.", show_alert=True)
    elif action == "reject_reason":
        code = parts[3] if len(parts) > 3 else "other"
        reason = kb.REJECT_REASONS.get(code)
        if not reason:
            await callback.answer("Unknown rejection reason.", show_alert=True)
            return
        await reject_transaction(callback, tx_id, reason=reason)
    elif action == "back":
        try:
            await callback.message.edit_reply_markup(reply_markup=kb.admin_review(tx_id))
            await callback.answer("Back.")
        except TelegramBadRequest:
            await callback.answer()
    else:
        await callback.answer("Unknown admin action.", show_alert=True)


async def approve_transaction(callback: CallbackQuery, tx_id: int) -> None:
    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx or tx.status != "pending":
            await callback.answer("Transaction is not pending.", show_alert=True)
            return
        user = await session.get(User, tx.user_id)
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return

        # Optional quorum: big deals must be tapped by TWO different admins.
        threshold = settings().dual_approval_usd
        if threshold and tx.amount_usd is not None and tx.amount_usd >= threshold:
            key = f"dual_approve:{tx.tx_id}"
            first = (await get_bot_state(session)).get(key)
            me = callback.from_user.id
            if first is None:
                await set_bot_state_keys(session, {key: me})
                await callback.answer(
                    f"Approved (1 of 2) — a second admin must also tap Approve for deals ≥ ${threshold:.0f}.",
                    show_alert=True,
                )
                return
            if first == me:
                await callback.answer("You already logged approval 1 of 2 — a *different* admin must confirm.", show_alert=True)
                return
            await set_bot_state_keys(session, {key: None})

        if tx.type == "withdrawal":
            if user.wallet_balance < tx.amount_usd:
                await callback.answer("Insufficient user wallet balance.", show_alert=True)
                return
            user.wallet_balance = as_money(user.wallet_balance - tx.amount_usd)
        elif tx.type in {"express_sell", "wallet_deposit"}:
            # Deposits on verifiable chains must be confirmed on-chain before
            # anything can be credited. None/"manual" = no verifier exists for
            # this chain (or a pre-upgrade legacy row), so review stays manual.
            verify_status = tx.verify_status or "manual"
            if verify_status == "verifying":
                await callback.answer("On-chain verification is still running — approve once it confirms.", show_alert=True)
                return
            if verify_status == "failed":
                await callback.answer(
                    f"On-chain verification FAILED: {tx.verify_detail or 'payment not found'}. Reject the TX or retry with /recheck {tx.tx_id}.",
                    show_alert=True,
                )
                return
            if verify_status == "unsubmitted":
                await callback.answer("No transaction hash submitted — on-chain verification is required before approval.", show_alert=True)
                return
            if tx.type == "wallet_deposit":
                # Exact-credit: stablecoin deposits credit the full on-chain
                # verified amount, so overpay is credited rather than lost.
                user.wallet_balance = as_money(user.wallet_balance + credit_amount_for(tx))
            await add_safe_sell_stats(session, user, tx.amount_usd, settings().timezone)

        tx.status = "approved"
        tx.admin_id = callback.from_user.id
        tx.resolved_at = utcnow()
        user.is_locked = False

        referral_bonus: tuple[User, Decimal] | None = None
        if (
            tx.type == "express_sell"
            and user.referred_by
            and settings().referral_bonus_usd > 0
        ):
            prior = await session.execute(
                select(func.count(Transaction.tx_id)).where(
                    Transaction.user_id == user.user_id,
                    Transaction.type == "express_sell",
                    Transaction.status == "approved",
                    Transaction.tx_id != tx.tx_id,
                )
            )
            if prior.scalar_one() == 0:
                referrer = await session.get(User, user.referred_by)
                if referrer:
                    bonus = as_money(settings().referral_bonus_usd)
                    referrer.wallet_balance = as_money(referrer.wallet_balance + bonus)
                    referral_bonus = (referrer, bonus)

        await notify_user_approved(callback, user, tx)
        if referral_bonus is not None:
            referrer, bonus = referral_bonus
            try:
                await callback.bot.send_message(
                    referrer.user_id,
                    f"🎁 Referral Bonus!\n\nA user you invited just completed their first SAFE SELL. ${bonus:.2f} has been added to your wallet balance.",
                    reply_markup=kb.persistent_menu(referrer),
                )
            except (TelegramBadRequest, TelegramForbiddenError):
                pass

        ask_receipt = tx.type in RECEIPT_PROMPT_TYPES and not tx.payout_reference
        if ask_receipt:
            await set_bot_state_keys(session, {pending_receipt_key(callback.from_user.id): new_pending_receipt(tx.tx_id, utcnow())})

        await callback.answer("Approved.")
        if callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(f"✅ TX {tx.tx_id} approved by {callback.from_user.id}.")
            except TelegramBadRequest:
                pass
            if ask_receipt:
                try:
                    await callback.message.answer(
                        f"🧾 Reply with the payout reference (UPI UTR etc.) for TX {tx.tx_id} — I'll send the user their receipt + rating card ⭐\n"
                        f"(window: {RECEIPT_PROMPT_MINUTES} min — reply 'skip' to dismiss, or use /receipt {tx.tx_id} <ref> anytime)"
                    )
                except TelegramBadRequest:
                    pass


async def reject_transaction(callback: CallbackQuery, tx_id: int, reason: str | None = None) -> None:
    async with session_scope() as session:
        tx = await session.get(Transaction, tx_id)
        if not tx or tx.status != "pending":
            await callback.answer("Transaction is not pending.", show_alert=True)
            return
        user = await session.get(User, tx.user_id)
        if not user:
            await callback.answer("User not found.", show_alert=True)
            return
        tx.status = "rejected"
        tx.admin_id = callback.from_user.id
        tx.resolved_at = utcnow()
        user.is_locked = False
        await notify_user_rejected(callback, user, tx, reason=reason)
        await callback.answer("Rejected.")
        if callback.message:
            suffix = f"\nReason: {reason}" if reason else ""
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
                await callback.message.answer(f"❌ TX {tx.tx_id} rejected by @{callback.from_user.username or callback.from_user.id}.{suffix}")
            except TelegramBadRequest:
                pass


async def notify_user_approved(callback: CallbackQuery, user: User, tx: Transaction) -> None:
    if tx.type == "withdrawal":
        text = "✅ Withdrawal Approved!\n\nYour payout request has been marked completed."
    elif tx.type == "wallet_deposit":
        credited = credit_amount_for(tx)
        extra = ""
        if credited > tx.amount_usd:
            extra = f"\n(You sent ${credited:.2f} on-chain — the full extra amount was credited 🙌)"
        text = f"✅ Payment Verified!\n\n${credited:.2f} has been added to your wallet balance.{extra}"
    else:
        text = "✅ Payment Verified!\n\nYour transaction has been approved. SAFE & GUARANTEED INR payout is marked completed."
    try:
        await callback.bot.send_message(user.user_id, text, reply_markup=kb.persistent_menu(user))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


async def notify_user_rejected(callback: CallbackQuery, user: User, tx: Transaction, reason: str | None = None) -> None:
    text = "❌ Payment Rejected!\n\nPlease retry or contact support."
    if tx.type == "withdrawal":
        text = "❌ Withdrawal Rejected!\n\nPlease retry or contact support."
    if reason:
        text = text.replace("Please retry or contact support.", f"Reason: {reason}\nPlease fix it and retry, or contact support.")
    try:
        await callback.bot.send_message(user.user_id, text, reply_markup=kb.persistent_menu(user))
    except (TelegramBadRequest, TelegramForbiddenError):
        pass


# Keep this handler LAST: it replies to free-text only when a receipt prompt
# is live, and must never swallow the command handlers above.
@router.message(F.text)
async def admin_receipt_reply(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return

    made_changes = None
    async with session_scope() as session:
        state = await get_bot_state(session)
        now = utcnow()

        # 1) Receipt prompt (auto receipt after approve)
        key = pending_receipt_key(message.from_user.id)
        parsed = parse_pending_receipt(state.get(key), now)
        if parsed is not None:
            if is_skip(text):
                await set_bot_state_keys(session, {key: ""})
                await message.answer("👍 Skipped — attach later with /receipt TX_ID <ref> if needed.")
                return
            reference = normalize_reference(text)
            if not reference:
                await message.answer("That doesn't look like a reference — send the plain UPI UTR / reference text (up to 64 chars), or 'skip'.")
                return
            await set_bot_state_keys(session, {key: ""})
            made_changes = ("receipt", parsed, reference)

        # 2) Support reply prompt
        elif parse_support_reply(state.get(support_reply_key(message.from_user.id)), now) is not None:
            target = parse_support_reply(state.get(support_reply_key(message.from_user.id)), now)
            await set_bot_state_keys(session, {support_reply_key(message.from_user.id): ""})
            made_changes = ("support", target, text)

        # 3) Rate wizard steps
        else:
            wiz = parse_ratewiz(state.get(ratewiz_key(message.from_user.id)), now)
            if wiz is not None:
                made_changes = ("ratewiz", wiz, text)

    if made_changes is None:
        return
    kind, a, b = made_changes

    if kind == "receipt":
        ok, note = await _deliver_payout_receipt(message.bot, a, b)
        if ok and not note:
            await message.answer(f"✅ Receipt for TX {a} delivered (ref: {b}) — rating card sent along ⭐")
        elif ok:
            await message.answer(f"⚠️ {note.capitalize()}.")
        else:
            await message.answer(f"⚠️ {note}")
        return

    if kind == "support":
        if b.lower() == "cancel":
            await message.answer("👍 Reply cancelled.")
            return
        try:
            await message.bot.send_message(a, f"💬 <b>Support reply:</b>\n\n{b}", parse_mode=ParseMode.HTML)
            await message.answer(f"✅ Delivered to {a}.")
        except (TelegramBadRequest, TelegramForbiddenError):
            await message.answer(f"⚠️ Couldn't reach user {a} (bot blocked?).")
        return

    # kind == "ratewiz": a=dict(wizard), b=text
    wiz, step, mode, values = a, a["step"], a["mode"], a["values"]
    if b.lower() == "cancel":
        async with session_scope() as session:
            await set_bot_state_keys(session, {ratewiz_key(message.from_user.id): ""})
        await message.answer("👍 Rate wizard cancelled — nothing changed.")
        return
    nxt: str | None = None
    if step == "min":
        min_usd = parse_decimal(b)
        if not min_usd or min_usd <= 0:
            await message.answer("❌ Send a positive number for the minimum. (Type 'cancel' to stop.)")
            return
        values["min"] = float(min_usd)
        nxt = ratewiz_next_step(step)
    elif step == "max":
        max_usd = parse_decimal(b) if b != "+" else None
        if b != "+" and (max_usd is None or max_usd <= Decimal(str(values.get("min", 0)))):
            await message.answer("❌ Send a max > min, or + / 'none' for no cap. ('cancel' to stop.)")
            return
        values["max"] = float(max_usd) if max_usd is not None else None
        nxt = ratewiz_next_step(step)
    else:  # step == "rate" — last step, save
        rate = parse_decimal(b)
        if not rate or rate <= 0:
            await message.answer("❌ Send a positive INR rate. ('cancel' to stop.)")
            return
        async with session_scope() as session:
            await _save_rate_tier(
                session, mode,
                Decimal(str(values["min"])),
                Decimal(str(values["max"])) if values.get("max") is not None else None,
                rate,
            )
            await set_bot_state_keys(session, {ratewiz_key(message.from_user.id): ""})
        span = f"${values['min']:.0f}" + ("–+" if values.get("max") is None else f"–${values['max']:.0f}")
        await message.answer(f"✅ {mode}: {span} → {rate:.1f}₹ saved!")
        return

    if nxt:
        payload = {"mode": mode, "step": nxt, "values": values, "until": (utcnow() + timedelta(minutes=RATEWIZ_MINUTES)).isoformat()}
        async with session_scope() as session:
            await set_bot_state_keys(session, {ratewiz_key(message.from_user.id): json.dumps(payload)})
        await message.answer(RATEWIZ_PROMPTS[nxt])


# ---------------------------------------------------------------------------
# Promo codes
# ---------------------------------------------------------------------------


@router.message(Command("promo"))
async def promo_add(message: Message) -> None:
    """/promo CODE AMOUNT [CAP] [DAYS] — e.g. /promo DIWALI 2 100 30"""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    from ..services import new_promo, normalize_promo_code, promo_key

    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Usage: /promo CODE AMOUNT_USD [CLAIM_CAP] [EXPIRES_DAYS]\nExample: /promo DIWALI 2 100 30")
        return
    code = normalize_promo_code(parts[1])
    amount = parse_decimal(parts[2])
    cap = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
    days = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else None
    if not code or not amount or amount <= 0 or (len(parts) > 4 and days is None):
        await message.answer("Invalid promo — code must be 3–24 letters/digits, amount a positive USD number.")
        return
    async with session_scope() as session:
        await set_bot_state_keys(session, {promo_key(code): new_promo(float(amount), cap, days, utcnow())})
    bits = [f"✅ Promo <b>{code}</b> = ${float(amount):.2f}"]
    if cap:
        bits.append(f"{cap} claims max")
    if days:
        bits.append(f"expires in {days}d")
    await message.answer(" | ".join(bits), parse_mode=ParseMode.HTML)


@router.message(Command("promos"))
async def promo_list(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    from ..services import list_promos

    async with session_scope() as session:
        promos = list_promos(await get_bot_state(session))
    if not promos:
        await message.answer("No promo codes yet — create one with /promo.")
        return
    lines = ["🎟 Promo Codes:"]
    for code, data in promos:
        bits = [f"{data.get('used', 0)}/{data['cap']} used" if data.get("cap") else f"{data.get('used', 0)} used"]
        if data.get("expires"):
            bits.append(f"exp {data['expires'][:10]}")
        lines.append(f"• {code}: ${float(data.get('amount', 0)):.2f} — {' | '.join(bits)}")
    await message.answer("\n".join(lines))


@router.message(Command("delpromo"))
async def promo_delete(message: Message) -> None:
    if not message.from_user or not is_admin(message.from_user.id):
        return
    from ..services import normalize_promo_code, promo_key

    parts = (message.text or "").split()
    code = normalize_promo_code(parts[1]) if len(parts) > 1 else None
    if not code:
        await message.answer("Usage: /delpromo CODE")
        return
    async with session_scope() as session:
        await set_bot_state_keys(session, {promo_key(code): ""})
    await message.answer(f"🗑 Promo {code} deleted.")


# ---------------------------------------------------------------------------
# Admin notes on users
# ---------------------------------------------------------------------------


@router.message(Command("note"))
async def admin_note(message: Message) -> None:
    """/note USER_ID [text] — view (no text), set, or clear ('-')."""
    if not message.from_user or not is_admin(message.from_user.id):
        return
    from ..services import get_admin_note, note_key

    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: /note USER_ID text   (or /note USER_ID to view, /note USER_ID - to clear)")
        return
    uid = int(parts[1])
    async with session_scope() as session:
        state = await get_bot_state(session)
        if len(parts) == 2:
            current = get_admin_note(state, uid)
            await message.answer(f"📝 Note for {uid}: {current or '(none)'}")
            return
        if parts[2].strip() == "-":
            await set_bot_state_keys(session, {note_key(uid): ""})
            await message.answer(f"🗑 Note for {uid} cleared.")
            return
        await set_bot_state_keys(session, {note_key(uid): parts[2].strip()[:500]})
    await message.answer(f"✅ Note saved — it will now show on {uid}'s review cards.")
