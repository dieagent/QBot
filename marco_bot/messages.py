from __future__ import annotations

from html import escape
from decimal import Decimal

from .constants import (
    ADS_CHANNEL_USERNAME,
    BOT_USERNAME,
    ESCROW_BOT_USERNAME,
    ESCROW_CHAT_USERNAME,
    IN_AD_ESCROW_USERNAME,
    UPDATES_USERNAME,
)
from .chainverify import explorer_url
from .translations import HI, tr

INFO_CARD = f"""What can this bot do? ⚡

⚡ Instant Crypto Sell
💎 Trusted & Safe MARCO Platform
🤑 SAFE Guaranteed INR Payouts
📢 Post P2P Ads On {ADS_CHANNEL_USERNAME}

Escrow : {ESCROW_BOT_USERNAME}
Chat : {ESCROW_CHAT_USERNAME}
Updates : {UPDATES_USERNAME}"""

WELCOME = """🔥 Welcome To SFOE P2P Bot 🤖, where you can Sell & Buy Crypto Easily ⚡️

What is your objective?"""

GROUP_GATE = """❌ Access Denied 🔒

To post ads, you must be a member of both our groups:
1️⃣ Join Group 1
2️⃣ Join Group 2

After joining, click POST AD again ⚡"""


def captcha_caption(first_name: str) -> str:
    return f"""Welcome! {first_name} 👋

To Join SFOE P2P 🔥, Solve this Captcha to get accepted! ⚡"""


def captcha_accepted(first_name: str) -> str:
    return f"""{first_name} You are accepted!!! ✅
Welcome To SFOE P2P 🔥

Use /start to sell your crypto right away! ⚡"""


def premium_emoji(emoji_id: str, fallback: str) -> str:
    return fallback


def welcome_render(lang: str | None = None) -> str:
    return tr("WELCOME", lang, WELCOME)


def my_stats_render(
    username: str,
    member_since: str,
    ads: int,
    sells: int,
    volume: Decimal,
    badge: str = "",
    referrals: int = 0,
    extras: list[str] | None = None,
    lang: str | None = None,
) -> str:
    extras_block = ""
    if extras:
        extras_block = "\n".join(extras) + "\n\n"
    default = f"""📊 @{username} Statistics {badge}

▪️ Member Since: {member_since}
▪️ P2P Ads Posted: {ads}
▪️ Safe Sells Completed: {sells}
▪️ Total Safe Sell Volume: ${volume:.2f}
▪️ Referrals: {referrals}

{extras_block}Use {BOT_USERNAME} for SAFE-SELL ⚡️"""
    hi = HI.get("MY_STATS", "")
    text = tr("MY_STATS", lang, default)
    if lang == "hi" and hi:
        text = hi.replace("{username}", str(username)).replace("{badge}", badge).replace(
            "{member_since}", member_since
        ).replace("{ads}", str(ads)).replace("{sells}", str(sells)).replace(
            "{volume}", f"{volume:.2f}"
        ).replace("{referrals}", str(referrals)).replace("{extras}", extras_block).replace("{bot_username}", BOT_USERNAME)
    return text


# ---------------------------------------------------------------------------
# Flow progress tracker (SAFE SELL / wallet top-up)
# ---------------------------------------------------------------------------

SELL_STEPS = ["💳 Mode", "💰 Amount", "🪙 Token", "🌐 Network", "💸 Pay", "🔎 Verify"]
WALLET_STEPS = ["💰 Amount", "🪙 Token", "🌐 Network", "💸 Pay", "🔎 Verify"]


def steps_header(current: int, wallet_flow: bool = False, lang: str | None = None) -> str:
    steps = WALLET_STEPS if wallet_flow else SELL_STEPS
    parts = [f"{label} ✅" if i < current else (f"▶ {label}" if i == current else label) for i, label in enumerate(steps)]
    title = "Step" if lang != "hi" else "Step"
    return f"┌ {title} {current + 1}/{len(steps)}\n└ " + " → ".join(parts)


# ---------------------------------------------------------------------------
# My transactions
# ---------------------------------------------------------------------------

TX_STATUS_ICON = {
    "pending": "⏳",
    "approved": "✅",
    "rejected": "❌",
    "cancelled": "🚫",
}
VERIFY_ICON = {"verified": "✅ on-chain", "verifying": "⚙️ verifying", "failed": "❌ on-chain", "manual": "👁 manual"}


def my_tx_render(rows: list, offset: int, total: int, lang: str | None = None) -> str:
    title = "📄 Your Transactions" if lang != "hi" else "📄 आपके Transactions"
    if not rows:
        empty = "No transactions yet. Start with SAFE SELL ⚡" if lang != "hi" else "अभी कोई transaction नहीं — SAFE SELL से शुरू करें ⚡"
        return f"{title}\n\n{empty}"
    lines = [f"{title} ({offset + 1}-{offset + len(rows)} of {total})", ""]
    for tx in rows:
        icon = TX_STATUS_ICON.get(tx.status, "⏳")
        verify = VERIFY_ICON.get(tx.verify_status or "", "")
        coin_part = f" {tx.coin}/{tx.chain}" if tx.coin else ""
        line = f"{icon} TX {tx.tx_id} · {tx.type.replace('_', ' ')} · ${tx.amount_usd:.2f}{coin_part}"
        if verify and tx.status in {"pending", "approved"}:
            line += f" · {verify}"
        if tx.chain_tx_hash and tx.chain:
            url = explorer_url(tx.chain, tx.chain_tx_hash)
            if url:
                line += f"\n    <a href=\"{url}\">🔗 hash</a>"
        if tx.payout_reference and tx.status == "approved":
            line += f"\n    💸 payout ref: <code>{tx.payout_reference}</code>"
        lines.append(line)
    return "\n".join(lines)


def payout_receipt_render(tx, lang: str | None = None) -> str:
    default = f"""💸 Payout Sent! ✅

TX: {tx.tx_id}
Amount: ${tx.amount_usd:.2f}
Payout Reference: <code>{tx.payout_reference}</code>

Check this reference in your bank/UPI app. Any issue, contact support 🙏"""
    text = tr("RECEIPT_USER", lang, default)
    if lang == "hi":
        text = text.replace("{tx_id}", str(tx.tx_id)).replace("{amount}", f"{tx.amount_usd:.2f}").replace("{reference}", str(tx.payout_reference))
    return text


def global_stats_render(total: Decimal, today: Decimal, deals: int) -> str:
    return f"""📊 Global Stats Of {BOT_USERNAME}

💰 Total SAFE-SOLD Amount:
${total:,.2f}

📅 Today's SAFE-SOLD Amount:
${today:,.2f}

🔥 Total SAFE-SOLD Deals Completed:
{deals}

💎 Always use {BOT_USERNAME} to get safest INR₹ in exchange!
⚡️ This Data shows how much crypto users have SOLD US!"""


OBJECTIVE = f"{premium_emoji('5951665890079544884', '✅')} What would you like to do?"
COIN_SELECT = f"{premium_emoji('5778311685638984859', '🌐')} Choose Your Coin:"


def chain_select(coin: str) -> str:
    coin_emoji = {
        'USDT': '🤑',
        'BTC': '🤑',
        'ETH': '🤑',
        'SOL': '🤑',
        'USDC': '🤑',
    }
    extra_emoji = coin_emoji.get(coin, '🤑')
    return f"🔗 Select Chain for {extra_emoji} {coin}:"


FUNDS_SOURCE = "💰 Choose payment source:"


def rate_input(category: str, minimum: float, maximum: float) -> str:
    return f"""💳 Set exchange rate:
Category: {category}
Enter a number between {minimum:.1f} and {maximum:.1f}:"""


AMOUNT_INPUT = "▽ Enter amount / quantity ⚡\n(e.g 10-100-1000)"
PAYMENT_METHOD = "💼 Pick a payment method:"


def ad_text(data: dict, username: str, preview: bool = True, badge: str = "") -> str:
    side = data.get("side", "sell")
    if side == "sell":
        side_line = "❗ #Selling"
    else:
        side_line = "🛒 #Buying"
    header = "🔎 ADVERTISEMENT PREVIEW\n\n" if preview else ""
    badge_part = f" {badge}" if badge else ""
    return f"""{header}{side_line}

💎 Crypto: {data.get("coin")}
💰 Quantity: {data.get("amount")}$
🔗 Chain: {data.get("chain")}
🏦 Funds Source: {data.get("funds_source")}
📈 Rate: {data.get("rate")}
💳 Payment Method: {data.get("payment_method")}

👤 DM: @{username}{badge_part}
⚖️ Escrow: {IN_AD_ESCROW_USERNAME}"""


def ad_published(ref_code: str) -> str:
    return f"""🚀 Ad Published Successfully! 🔥

Your ad is now live in the channel post.
Ref: {ref_code}

Use {BOT_USERNAME} for SAFE-SELL ⚡"""


SAFE_SELL_LANDING = f"""Welcome to SFOE P2P Bot 💬

💵 SAFE SELL — A trusted platform to Sell Crypto 🔥 Instantly and receive SAFE & GUARANTEED 🔒 INR ₹ directly.

Choose an option below to get started 👇"""

SAFE_SELL_BANNER = """✔ Instant Payments ⚡
✔ Verified & Guaranteed Funds
✔ Supported Modes – UPI | IMPS | CDM
✔ No Time-passers | No Scams
✔ Direct SAFE-SELL to us & relax

Fund Purity & Safety — Guaranteed by SFOE 🔥
Each penny you receive is 100% authentic & Guaranteed!"""

PAYMENT_MODE_SELECT = "Sell your crypto in multiple methods 👇⚡"


def exchange_rates(payment_mode: str, tiers: list[tuple[Decimal, Decimal | None, Decimal]]) -> str:
    lines = []
    for min_usd, max_usd, rate in tiers:
        if max_usd is None:
            band = f"${min_usd:.0f}+"
        else:
            band = f"${min_usd:.0f}-${max_usd:.0f}"
        lines.append(f"⚡️ {band} : {rate:.1f}₹")
    tier_text = "\n".join(lines)
    return f"""👁 Important - You may get funds in multiple 💰 shots, if the order is bigger than 25K₹ 👁 (100% Safe 👛)

    EXCHANGE RATES FOR {payment_mode} 👇

{tier_text}

Enter Amount in $ you want to sell :"""


def inr_preview(amount_inr: Decimal) -> str:
    return f"""You will receive approx: ₹{amount_inr:.2f} 💵

Select Your Crypto 🤑 Token 👇"""


def express_chain_select(token: str) -> str:
    return f"🔗 Select Chain for 🤑 {token}:"


def deposit_instructions(token: str, chain: str, address: str, lang: str | None = None) -> str:
    default = f"""🤑 Token: {escape(token)}
🔗 Network: {escape(chain)}

Pay on the address below 👇:
<code>{escape(address)}</code>

⚠️ Note: Send exact amount or more. Any extra will be added to your wallet balance.

After payment, ➡️ click 'CHECK PAYMENT' below to send proof 👁"""
    text = tr("DEPOSIT_INSTRUCTIONS", lang, default)
    if lang == "hi":
        text = text.replace("{token}", escape(token)).replace("{chain}", escape(chain)).replace("{address}", escape(address))
    return text


def safe_sell_landing(lang: str | None = None) -> str:
    return tr("SAFE_SELL_LANDING", lang, SAFE_SELL_LANDING)


def tx_hash_prompt(lang: str | None = None) -> str:
    return tr("TX_HASH_PROMPT", lang, TX_HASH_PROMPT)


def verifying_payment(lang: str | None = None) -> str:
    return tr("VERIFYING_PAYMENT", lang, VERIFYING_PAYMENT)


def verified_user_text(detail: str, lang: str | None = None) -> str:
    default = (
        "✅ Payment confirmed on-chain!\n\n"
        f"{detail}\n\n"
        "Your transaction is waiting for admin approval. "
        "This usually takes a few minutes ⚡"
    )
    text = tr("VERIFIED_USER", lang, default)
    if lang == "hi":
        text = text.replace("{detail}", detail)
    return text


def failed_user_text(lang: str | None = None) -> str:
    default = (
        "⚠️ We could not confirm your payment on-chain.\n\n"
        "Our team will review it shortly. If this takes long, please contact support."
    )
    return tr("FAILED_USER", lang, default)


def cancelled_user_text(tx_id: int, lang: str | None = None) -> str:
    default = (
        f"🚫 Your request (TX {tx_id}) has been cancelled.\n\n"
        "Account unlocked — you can start a new request anytime ✅"
    )
    text = tr("CANCELLED_USER", lang, default)
    if lang == "hi":
        text = text.replace("{tx_id}", str(tx_id))
    return text


SCREENSHOT_PROMPT = "Please send a screenshot of your payment for verification 📸."

TX_HASH_PROMPT = """🔎 Verify Your Payment On-Chain

Paste the transaction hash / TxID of your payment below 👇
(66 characters starting with 0x on BSC/ETH networks, or a 64-character TxID on TRON/Bitcoin)

You can also attach a payment screenshot as extra proof 📸

Your payment is verified directly on the blockchain before approval — sending a wrong or fake hash will fail verification."""

TX_HASH_INVALID = """❌ That doesn't look like a valid transaction hash.

Please paste the full transaction hash / TxID (64 hex characters, with 0x prefix on BSC/ETH networks)."""

SCREENSHOT_SAVED = """📸 Screenshot saved as extra proof.

Now paste the transaction hash / TxID so we can verify your payment on-chain 👇"""


SCREENSHOT_SUBMITTED = """✅ Screenshot Submitted!

Please wait for admin verification ⚡"""

VERIFYING_PAYMENT = """🔎 Payment Submitted!

We are verifying your transaction on the blockchain. This can take a few minutes while the network confirms it ⏳

You will get a message as soon as it is confirmed ✅"""

LOCKED_ACTION = "⚠ This action is disabled pending transaction verification 🔒."

LOCKED_STATS = """⚠ Verification Pending 🔒.
Account is currently locked."""


def wallet(balance: Decimal, lang: str | None = None) -> str:
    default = f"""🧾 Your Wallet Balance

💰 Available: ${balance:.2f} USD

You can deposit funds to use later or withdraw your funds at any time"""
    text = tr("WALLET_CARD", lang, default)
    if lang == "hi":
        text = text.replace("{balance}", f"{balance:.2f}")
    return text


def my_stats(username: str, member_since: str, ads: int, sells: int, volume: Decimal) -> str:
    return f"""<tg-emoji emoji-id='5913702317667913862'>📊</tg-emoji> @{username} Statistics

▪️ Member Since: {member_since}
▪️ P2P Ads Posted: {ads}
▪️ Safe Sells Completed: {sells}
▪️ Total Safe Sell Volume: ${volume:.2f}

Use {BOT_USERNAME} for SAFE-SELL <tg-emoji emoji-id='5409099658171537510'>⚡️</tg-emoji>"""


def loading_animation(percentage: int) -> str:
    """Generate animated loading bar for global stats"""
    filled = percentage // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    status = "✅ Statistics Loaded" if percentage == 100 else ""
    return f"""📊 Loading Global Statistics...{bar} {percentage}% {status}"""


def global_stats(total: Decimal, today: Decimal, deals: int) -> str:
    return f"""<tg-emoji emoji-id='5913702317667913862'>📊</tg-emoji> Global Stats Of {BOT_USERNAME}

<tg-emoji emoji-id='5987880246865565644'>💰</tg-emoji> Total SAFE-SOLD Amount:
${total:,.2f}

<tg-emoji emoji-id='5217604963571621845'>📅</tg-emoji> Today's SAFE-SOLD Amount:
${today:,.2f}

<tg-emoji emoji-id='5408892168301466942'>🔥</tg-emoji> Total SAFE-SOLD Deals Completed:
{deals}

<tg-emoji emoji-id='5877485980901971030'>💎</tg-emoji> Always use {BOT_USERNAME} to get safest INR₹ in exchange!
<tg-emoji emoji-id='5409099658171537510'>⚡️</tg-emoji> This Data shows how much crypto users have SOLD US!"""


WITHDRAW_AMOUNT = "💵 Enter withdrawal amount in USD ⚡:"
WITHDRAW_DESTINATION = "📤 Send your withdrawal destination (UPI ID / bank details / crypto address):"
WALLET_ADD_AMOUNT = "💰 Enter Amount in $ you want to add ⚡ :"


def withdraw_queued(tx_id: int) -> str:
    return f"""✅ Withdrawal request submitted! 💸

Please wait for admin payout ⚡.
Ref: TX-{tx_id}"""
