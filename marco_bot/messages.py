from __future__ import annotations

from decimal import Decimal

from aiogram.types import MessageEntity

from .constants import (
    ADS_CHANNEL_USERNAME,
    BOT_USERNAME,
    ESCROW_BOT_USERNAME,
    ESCROW_CHAT_USERNAME,
    IN_AD_ESCROW_USERNAME,
    UPDATES_USERNAME,
)

INFO_CARD = f"""What can this bot do? ⚡

⚡ Instant Crypto Sell
💎 Trusted & Safe MARCO Platform
🤑 SAFE Guaranteed INR Payouts
📢 Post P2P Ads On {ADS_CHANNEL_USERNAME}

Escrow : {ESCROW_BOT_USERNAME}
Chat : {ESCROW_CHAT_USERNAME}
Updates : {UPDATES_USERNAME}"""

WELCOME = """<tg-emoji emoji-id="5408892168301466942">🔥</tg-emoji> Welcome To MARCO P2P Bot <tg-emoji emoji-id="5409315600537250312">🤖</tg-emoji>, where you can Sell & Buy Crypto Easily <tg-emoji emoji-id="5229121484584139947">⚡️</tg-emoji>

What is your objective?"""

GROUP_GATE = """❌ Access Denied 🔒

To post ads, you must be a member of both our groups:
1️⃣ Join Group 1
2️⃣ Join Group 2

After joining, click POST AD again ⚡"""


def captcha_caption(first_name: str) -> str:
    return f"""Welcome! {first_name} 👋

To Join MARCO P2P 🔥, Solve this Captcha to get accepted! ⚡"""


def captcha_accepted(first_name: str) -> str:
    return f"""{first_name} You are accepted!!! ✅
Welcome To MARCO P2P 🔥

Use /start to sell your crypto right away! ⚡"""


def premium_emoji(emoji_id: str, fallback: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def custom_emoji_entities(parts: list[str | tuple[str, str]]) -> tuple[str, list[MessageEntity]]:
    text_parts: list[str] = []
    entities: list[MessageEntity] = []
    offset = 0
    for part in parts:
        if isinstance(part, tuple):
            emoji_text, emoji_id = part
            text_parts.append(emoji_text)
            length = _utf16_len(emoji_text)
            entities.append(
                MessageEntity(type="custom_emoji", offset=offset, length=length, custom_emoji_id=emoji_id)
            )
            offset += length
        else:
            text_parts.append(part)
            offset += _utf16_len(part)
    return "".join(text_parts), entities


def welcome_render() -> tuple[str, list[MessageEntity]]:
    return custom_emoji_entities(
        [
            ("🔥", "5408892168301466942"),
            " Welcome To MARCO P2P Bot ",
            ("🤖", "5409315600537250312"),
            ", where you can Sell & Buy Crypto Easily ",
            ("⚡️", "5229121484584139947"),
            "\n\nWhat is your objective?",
        ]
    )


def my_stats_render(username: str, member_since: str, ads: int, sells: int, volume: Decimal) -> tuple[str, list[MessageEntity]]:
    return custom_emoji_entities(
        [
            ("📊", "5913702317667913862"),
            f" @{username} Statistics\n\n",
            ("▪️", "5936130851635990622"),
            f" Member Since: {member_since}\n",
            ("▪️", "5936130851635990622"),
            f" P2P Ads Posted: {ads}\n",
            ("▪️", "5936130851635990622"),
            f" Safe Sells Completed: {sells}\n",
            ("▪️", "5936130851635990622"),
            f" Total Safe Sell Volume: ${volume:.2f}\n\n",
            "Use ",
            BOT_USERNAME,
            " for SAFE-SELL ",
            ("⚡️", "5409099658171537510"),
        ]
    )


def global_stats_render(total: Decimal, today: Decimal, deals: int) -> tuple[str, list[MessageEntity]]:
    return custom_emoji_entities(
        [
            ("📊", "5913702317667913862"),
            f" Global Stats Of {BOT_USERNAME}\n\n",
            ("💰", "5987880246865565644"),
            f" Total SAFE-SOLD Amount:\n${total:,.2f}\n\n",
            ("📅", "5217604963571621845"),
            f" Today's SAFE-SOLD Amount:\n${today:,.2f}\n\n",
            ("🔥", "5408892168301466942"),
            f" Total SAFE-SOLD Deals Completed:\n{deals}\n\n",
            ("💎", "5877485980901971030"),
            f" Always use {BOT_USERNAME} to get safest INR₹ in exchange!\n",
            ("⚡️", "5409099658171537510"),
            " This Data shows how much crypto users have SOLD US!",
        ]
    )


OBJECTIVE = f"{premium_emoji('5951665890079544884', '✅')} What would you like to do?"
COIN_SELECT = f"{premium_emoji('5778311685638984859', '🌐')} Choose Your Coin:"


def chain_select(coin: str) -> str:
    coin_emoji = {
        'USDT': premium_emoji('5242551409232069476', '🤑'),
        'BTC': premium_emoji('5242625806655570503', '🤑'),
        'ETH': premium_emoji('5246838478083211008', '🤑'),
        'SOL': premium_emoji('5240212838194104761', '🤑'),
        'USDC': premium_emoji('5240086656349913841', '🤑'),
    }
    extra_emoji = coin_emoji.get(coin, premium_emoji('5242551409232069476', '🤑'))
    return f"{premium_emoji('5411246291416013236', '🔗')} Select Chain for {extra_emoji} {coin}:"


FUNDS_SOURCE = "<tg-emoji emoji-id='5348503265967355284'>💰</tg-emoji> Choose payment source:"


def rate_input(category: str, minimum: float, maximum: float) -> str:
    return f"""<tg-emoji emoji-id='5927169041595634481'>💳</tg-emoji> Set exchange rate:
Category: {category}
Enter a number between {minimum:.1f} and {maximum:.1f}:"""


AMOUNT_INPUT = "▽ Enter amount / quantity ⚡\n(e.g 10-100-1000)"
PAYMENT_METHOD = "<tg-emoji emoji-id='5967389567781703494'>💼</tg-emoji> Pick a payment method:"


def ad_text(data: dict, username: str, preview: bool = True) -> str:
    side = data.get("side", "sell")
    if side == "sell":
        side_line = "<tg-emoji emoji-id='5040034664614462519'>❗</tg-emoji> #Selling"
    else:
        side_line = "<tg-emoji emoji-id='5852871561983299073'>🛒</tg-emoji> #Buying"
    header = "🔎 ADVERTISEMENT PREVIEW\n\n" if preview else ""
    return f"""{header}{side_line}

<tg-emoji emoji-id='5832251986635920010'>💎</tg-emoji> Crypto: {data.get("coin")}
<tg-emoji emoji-id='5992430854909989581'>💰</tg-emoji> Quantity: {data.get("amount")}$
<tg-emoji emoji-id='5987917196469213507'>🔗</tg-emoji> Chain: {data.get("chain")}
<tg-emoji emoji-id='5926783847453692661'>🏦</tg-emoji> Funds Source: {data.get("funds_source")}
<tg-emoji emoji-id='5974217466270716579'>📈</tg-emoji> Rate: {data.get("rate")}
<tg-emoji emoji-id='5967548335542767952'>💳</tg-emoji> Payment Method: {data.get("payment_method")}

<tg-emoji emoji-id='5886412370347036129'>👤</tg-emoji> DM: @{username}
<tg-emoji emoji-id='6034962180875490251'>⚖️</tg-emoji> Escrow: {IN_AD_ESCROW_USERNAME}"""


def ad_published(ref_code: str) -> str:
    return f"""🚀 Ad Published Successfully! 🔥

Your ad is now live in the channel post.
Ref: {ref_code}

Use {BOT_USERNAME} for SAFE-SELL ⚡"""


SAFE_SELL_LANDING = f"""Welcome to MARCO P2P Bot 💬

💵 SAFE SELL — A trusted platform to Sell Crypto 🔥 Instantly and receive SAFE & GUARANTEED 🔒 INR ₹ directly.

Choose an option below to get started 👇"""

SAFE_SELL_BANNER = """✔ Instant Payments ⚡
✔ Verified & Guaranteed Funds
✔ Supported Modes – UPI | IMPS | CDM
✔ No Time-passers | No Scams
✔ Direct SAFE-SELL to us & relax

Fund Purity & Safety — Guaranteed by MARCO 🔥
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

Select Your Crypto {premium_emoji('5242625806655570503', '🤑')} Token 👇"""


def express_chain_select(token: str) -> str:
    token_emojis = {
        "USDT": "5242551409232069476",
        "BTC": "5242625806655570503",
        "ETH": "5246838478083211008",
        "SOL": "5240212838194104761",
        "USDC": "5240086656349913841",
    }
    emoji_id = token_emojis.get(token, "5242551409232069476")
    return f"{premium_emoji('5411246291416013236', '🔗')} Select Chain for {premium_emoji(emoji_id, '🤑')} {token}:"


def deposit_instructions(token: str, chain: str, address: str) -> str:
    return f"""{premium_emoji('5242551409232069476', '🤑')} Token: {token}
🔗 Network: {chain}

Pay on the address below 👇:
{address}

⚠️ Note: Send exact amount or more. Any extra will be added to your wallet balance.

After payment, ➡️ click 'CHECK PAYMENT' below to send proof 👁"""


SCREENSHOT_PROMPT = "Please send a screenshot of your payment for verification 📸."


SCREENSHOT_SUBMITTED = """✅ Screenshot Submitted!

Please wait for admin verification ⚡"""

LOCKED_ACTION = "⚠ This action is disabled pending transaction verification 🔒."

LOCKED_STATS = """⚠ Verification Pending 🔒.
Account is currently locked."""


def wallet(balance: Decimal) -> str:
    return f"""🧾 Your Wallet Balance

💰 Available: ${balance:.2f} USD

You can deposit funds to use later or withdraw your funds at any time"""


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
    return f"""<tg-emoji emoji-id='5913702317667913862'>📊</tg-emoji> Loading Global Statistics...{bar} {percentage}% {status}"""


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
