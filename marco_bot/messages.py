from __future__ import annotations

from decimal import Decimal

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

WELCOME = """🔥 Welcome To MARCO P2P Bot 🤖, where you can Sell & Buy Crypto Easily ⚡️

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
    return fallback


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


FUNDS_SOURCE = "💰 Choose payment source:"


def rate_input(category: str, minimum: float, maximum: float) -> str:
    return f"""💳 Set exchange rate:
Category: {category}
Enter a number between {minimum:.1f} and {maximum:.1f}:"""


AMOUNT_INPUT = "▽ Enter amount / quantity ⚡\n(e.g 10-100-1000)"
PAYMENT_METHOD = "💼 Pick a payment method:"


def ad_text(data: dict, username: str, preview: bool = True) -> str:
    side = data.get("side", "sell")
    if side == "sell":
        side_line = "❗ #Selling"
    else:
        side_line = "🛒 #Buying"
    header = "🔎 ADVERTISEMENT PREVIEW\n\n" if preview else ""
    return f"""{header}{side_line}

💎 Crypto: {data.get("coin")}
💰 Quantity: {data.get("amount")}$
🔗 Chain: {data.get("chain")}
🏦 Funds Source: {data.get("funds_source")}
📈 Rate: {data.get("rate")}
💳 Payment Method: {data.get("payment_method")}

👤 DM: @{username}
⚖️ Escrow: {IN_AD_ESCROW_USERNAME}"""


def ad_published(ref_code: str) -> str:
    return f"""🚀 Ad Published Successfully! 🔥

Your ad is now live in the channel post.
Ref: {ref_code}

Use {BOT_USERNAME} for SAFE-SELL ⚡"""


SAFE_SELL_LANDING = f"""Welcome to MARCO P2P Bot {premium_emoji('5994297722574737553', '💬')}

{premium_emoji('5197434882321567830', '💵')} SAFE SELL — A trusted platform to Sell Crypto {premium_emoji('4911320645146510335', '🔥')} Instantly and receive SAFE & GUARANTEED {premium_emoji('5832546462478635761', '🔒')} INR ₹ directly.

Choose an option below to get started {premium_emoji('6105102145030199285', '👇')}"""

SAFE_SELL_BANNER = """✔ Instant Payments ⚡
✔ Verified & Guaranteed Funds
✔ Supported Modes – UPI | IMPS | CDM
✔ No Time-passers | No Scams
✔ Direct SAFE-SELL to us & relax

Fund Purity & Safety — Guaranteed by MARCO 🔥
Each penny you receive is 100% authentic & Guaranteed!"""

PAYMENT_MODE_SELECT = f"Sell your crypto in multiple methods {premium_emoji('6339166816006312740', '👇')}⚡"


def exchange_rates(payment_mode: str, tiers: list[tuple[Decimal, Decimal | None, Decimal]]) -> str:
    lines = []
    for min_usd, max_usd, rate in tiers:
        if max_usd is None:
            band = f"${min_usd:.0f}+"
        else:
            band = f"${min_usd:.0f}-${max_usd:.0f}"
        lines.append(f"{premium_emoji('5935795874251674052', '⚡️')} {band} : {rate:.1f}₹")
    tier_text = "\n".join(lines)
    return f"""{premium_emoji('5960714428394507968', '👁')} Important - You may get funds in multiple {premium_emoji('5897958754267174109', '💰')} shots, if the order is bigger than 25K₹ {premium_emoji('6019295596173596341', '👁')} (100% Safe {premium_emoji('5769403330761593044', '👛')})

EXCHANGE RATES FOR {payment_mode} {premium_emoji('6339166816006312740', '👇')}

{tier_text}

Enter Amount in $ you want to sell :"""


def inr_preview(amount_inr: Decimal) -> str:
    return f"""You will receive approx: ₹{amount_inr:.2f} {premium_emoji('5197434882321567830', '💵')}

Select Your Crypto {premium_emoji('5242625806655570503', '🤑')} Token {premium_emoji('6339166816006312740', '👇')}"""


def express_chain_select(token: str) -> str:
    token_emojis = {
        "USDT": "5242551409232069476",
        "BTC": "5242625806655570503",
        "ETH": "5246838478083211008",
        "SOL": "5240212838194104761",
        "USDC": "5240086656349913841",
    }
    emoji_id = token_emojis.get(token, "5242551409232069476")
    return f"{premium_emoji('5411246291416013236', '🔗')} Select Network Chain for {premium_emoji(emoji_id, '🤑')} {token}:"


def deposit_instructions(token: str, chain: str, address: str) -> str:
    return f"""{premium_emoji('5242551409232069476', '🤑')} Token: {token}
{premium_emoji('5877465816030515018', '🔗')} Network: {chain}

Pay on the address below {premium_emoji('6339166816006312740', '👇')}:
{address}

{premium_emoji('5447644880824181073', '⚠️')} Note: Send exact amount or more. Any extra will be added to your wallet balance.

After payment, {premium_emoji('5877468380125990242', '➡️')} click 'CHECK PAYMENT' below to send proof {premium_emoji('6019295596173596341', '👁')}"""


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
    return f"""📊 @{username} Statistics

▪️ Member Since: {member_since}
▪️ P2P Ads Posted: {ads}
▪️ Safe Sells Completed: {sells}
▪️ Total Safe Sell Volume: ${volume:.2f}

Use {BOT_USERNAME} for SAFE-SELL ⚡️"""


def loading_animation(percentage: int) -> str:
    """Generate animated loading bar for global stats"""
    filled = percentage // 10
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    status = "✅ Statistics Loaded" if percentage == 100 else ""
    return f"""📊 Loading Global Statistics...{bar} {percentage}% {status}"""


def global_stats(total: Decimal, today: Decimal, deals: int) -> str:
    return f"""📊 Global Stats Of {BOT_USERNAME}

💰 Total SAFE-SOLD Amount:
${total:,.2f}

📅 Today's SAFE-SOLD Amount:
${today:,.2f}

🔥 Total SAFE-SOLD Deals Completed:
{deals}

💎 Always use {BOT_USERNAME} to get safest INR₹ in exchange!
⚡️ This Data shows how much crypto users have SOLD US!"""


WITHDRAW_AMOUNT = "💵 Enter withdrawal amount in USD ⚡:"
WITHDRAW_DESTINATION = "📤 Send your withdrawal destination (UPI ID / bank details / crypto address):"
WALLET_ADD_AMOUNT = "💰 Enter Amount in $ you want to add ⚡ :"


def withdraw_queued(tx_id: int) -> str:
    return f"""✅ Withdrawal request submitted! 💸

Please wait for admin payout ⚡.
Ref: TX-{tx_id}"""
