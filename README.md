# SFOE P2P Bot

Telegram bot rebuild for the SFOE P2P flow: P2P ad posting, captcha/group gate, SAFE SELL Express, wallet deposits/withdrawals, per-user stats, global stats, cooldowns, and admin approval.

## What Is Included

- aiogram v3 polling bot
- SQLite by default, with SQLAlchemy async models
- Persistent DB-backed user sessions so flows survive restarts
- SFOE-branded `/start` cards with generated banner image
- Persistent reply keyboard:
  - `POST AD`
  - `SAFE SELL [EXPRESS]`
  - `WALLET💰`
  - `📊 My Stats`
  - `📈 Global Stats`
- POST AD group gate, captcha, ad builder, preview, publish, public channel/group posting, and 3-hour cooldown
- SAFE SELL Express amount/rate calculation, token/network selection, deposit address display, **on-chain payment verification**, and admin review
- Wallet add funds, withdraw queue, account lock while pending, and admin approval/rejection
- Admin commands for pending queue, stats, payment-mode availability, rates, broadcasts, and verification re-runs

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`:

- `BOT_TOKEN`: BotFather token
- `ADMIN_IDS`: comma-separated numeric Telegram user IDs
- `ADMIN_REVIEW_CHAT_ID`: admin group/channel for payment proof review
- `ADS_CHANNEL_ID`: public ads channel, such as `@SFOE_P2P`
- `ADS_GROUP_ID`: public ads group numeric ID
- `REQUIRED_GROUP_1_ID` / `REQUIRED_GROUP_2_ID`: groups users must join before posting ads
- `DEPOSIT_ADDRESSES_JSON`: token/network deposit address map

The bot must be admin in any channel/group where it checks membership, posts ads, or sends admin-review messages.

## Run

```bash
python -m marco_bot.main
```

By default the bot creates `marco_bot.sqlite3` in the working directory.

## Deploy On Railway

1. Push this folder to a GitHub repository.
2. Create a new Railway project from the GitHub repo.
3. Add a Railway Postgres database.
4. Set the environment variables from `.env.railway.example` in Railway, using your real private values.
5. Keep Railway's `DATABASE_URL` variable from Postgres; the app converts it to the async SQLAlchemy driver automatically.
6. Deploy. `railway.json` starts the bot with `python -m marco_bot.main`.

This is a polling Telegram bot, so it does not need an HTTP port.

See `RAILWAY_DEPLOY.md` for the full GitHub/Railway checklist.

## Deploy On Vercel (webhook mode)

Long polling cannot run on Vercel, so the bot ships a webhook runtime:
`api/webhook.py` serves `https://<your-app>.vercel.app/api/webhook`.

1. Import the GitHub repo into Vercel (Python is detected automatically).
2. Set the environment variables from `.env.example`, with production values:
   - `DATABASE_URL` — **must be a real Postgres URL**
     (`postgresql://user:pass@host:5432/db?sslmode=require`). A Railway-style
     `${{Postgres.DATABASE_URL}}` reference does not resolve on Vercel and the
     function will refuse to boot (SQLite would silently lose ledger data).
     Reuse your Railway Postgres "public" connection string or any hosted
     Postgres (Neon, Supabase, Vercel Postgres).
   - `WEBHOOK_URL` — `https://<your-production-domain>.vercel.app/api/webhook`
     (set it explicitly so redeploys never break the Telegram webhook).
   - `WEBHOOK_SECRET` — any random string; the function rejects webhook
     requests that do not carry it.
   - `CRON_SECRET` — any random string; Vercel Cron attaches it as a
     `Bearer` token when hitting `/api/cron` (daily admin summary at
     09:00 IST, Hobby plan = 1 run/day — see `crons` in `vercel.json`).
   - `REFERRAL_BONUS_USD` *(optional, default 0)* — wallet bonus paid to a
     referrer when their referred user completes a first approved SAFE SELL.
     Leave `0` to track referrals without paying bonuses.
   - The rest is the same as the Railway deployment.
3. Deploy, then open `https://<your-app>.vercel.app/api/webhook` once — the
   first request performs cold-start init and registers the webhook with
   Telegram. It shows `{ "ok": true, "mode": "webhook" }` when healthy.

Serverless limitations are handled by design:

- Function max duration is configured to 60s (`vercel.json`); Hobby plans
  default to 10s otherwise.
- Background tasks freeze after each request, so deposit verification runs
  as: bounded inline attempts on submit + **CHECK STATUS** button +
  `/recheck TX_ID` + a small sweep of pending deposits on every incoming
  update. Worst case, verification completes on the user's/admin's next tap.
- The engine uses `NullPool` so one container survives sequential requests.
- Long polling (`main.py`) stays as the entrypoint for Railway/local runs;
  it is unused on Vercel.
- A daily ops summary (volumes, pending queue, new users) is posted to the
  admin review chat by Vercel Cron (`/api/cron`, `CRON_SECRET`-protected).
- Unhandled webhook errors alert the admin chat in Telegram, throttled to at
  most one alert per 5 minutes, so retry storms cannot spam it.

## Deposit Address Format

Example:

```env
DEPOSIT_ADDRESSES_JSON={"USDT":{"BEP20":"0x...","TRC20":"T..."},"BTC":{"BTC":"bc1..."},"ETH":{"ERC20":"0x..."}}
```

If an address is missing, users will see a visible `CONFIGURE_TOKEN_CHAIN_ADDRESS` placeholder so misconfiguration is obvious.

## Admin Commands

```text
/admin
/pending
/stats
/mode UPI on
/mode CDM off
/rates
/setrate UPI 10 600 94.0
/setrate UPI 5001 + 97.0
/broadcast message text
/receipt 42 831204912345
/export
/emojiids
```

- `/receipt TX_ID PAYOUT_REFERENCE` attaches a payout reference (e.g. the UPI
  UTR) to an approved transaction and DMs the user a payout receipt card.
- `/export` uploads a UTF-8 CSV (latest 5000 transactions) with hashes,
  verified amounts and payout references for accounting.
- **Reject reasons:** the admin review card's **Reject ❌** button now opens
  one-tap reasons (wrong network / wrong amount / hash not found / other);
  the chosen reason is included in the user notification.

Use `/emojiids` (or `/emojiiids`) as a reply to a message that contains premium/custom emojis, or include premium emojis in the same command message, to print the Telegram custom emoji IDs needed for custom emoji rendering.

The bot runtime now uses the updated premium emoji IDs from the latest deployment branch.

## User-Facing Feature Pack

- **Step tracker** — SAFE SELL and wallet deposit flows show a
  `Step N/M` checklist header on every screen.
- **📄 My Transactions** — users list their own deals with live status,
  on-chain verification stamps and explorer-linked hashes.
- **Cancel request** — a pending transaction can be cancelled by the user
  with one tap (before on-chain verification succeeds), unlocking the account.
- **Exact crediting** — stablecoin (USDT/USDC) wallet deposits credit the full
  on-chain verified amount, so overpayment is credited instead of lost.
- **Referrals** — `/start ref_<id>` deep links are recorded for brand-new
  users; `/refer` shows the personal invite link and count; an optional
  `REFERRAL_BONUS_USD` bonus pays the referrer when the invitee completes
  their first approved SAFE SELL.
- **Trust badges** — 🥉 (≥$250) / 🥈 (≥$1000) / 🥇 (≥$5000) completed SAFE
  SELL volume badges appear in My Stats and next to the username in ads.
- **Hindi toggle** — `/lang` or the 🇮🇳 button on the stats screen switches
  the core screens (welcome, SAFE SELL, deposit, verification, wallet) to
  Hindi; anything untranslated falls back to English.

## On-Chain Verification

Deposits (SAFE SELL Express and wallet top-ups) are verified directly on the
blockchain before an admin can credit anything. Screenshots alone are no
longer accepted on supported networks.

Flow:

1. After sending payment, the user taps **CHECK PAYMENT** and pastes the
   transaction hash / TxID (a screenshot can be added as extra proof).
2. The bot checks the transaction on-chain in the background
   (~6 minutes max) and shows the result on the admin review card.
3. The **Approve** button only works once verification is `✅ VERIFIED`
   (or `⚠️ MANUAL` for networks without an automatic verifier).

What gets verified:

| Network | Provider | Check |
| --- | --- | --- |
| USDT/USDC on ERC20 / BEP20 / MATIC / BASE / ARBITRUM / OPTIMISM | Etherscan V2, then Infura, then public RPC fallback | token contract, recipient, amount ≥ expected USD, confirmations |
| ETH / BNB native transfers | same as above | recipient, amount reported (not USD-pegged), confirmations |
| USDT on TRC20 | TronGrid (`only_confirmed`) | token contract, recipient, amount |
| BTC on Bitcoin | blockstream.info (no key needed) | output pays the address, ≥1 confirmation |

Networks without a trusted registry entry (e.g. SOL) and chains with no
configured deposit address fall back to the old screenshot-only review, and
the admin card says `⚠️ MANUAL` explicitly. A transaction hash can only be
credited once — resubmitted hashes are refused.

Useful settings:

- `ETHERSCAN_API_KEY` — one Etherscan V2 key covers every EVM chain; free
  plans may not include BSC, in which case the bot automatically falls back
  to Infura / public RPC endpoints.
- `INFURA_API_KEY` / `INFURA_URL` — used as fallback RPC for
  Ethereum/Polygon/Arbitrum/Optimism/Base.
- `TRONGRID_API_KEY` — optional but avoids rate limits on TRON queries.
- `VERIFY_MIN_CONFIRMATIONS` — optional override of the per-chain
  confirmation targets (defaults: 12 ETH, 15 BSC, 32 Polygon, 1 BTC).
- `/recheck TX_ID` — rerun verification for a transaction whose payment
  confirmed after the bot timed out.

Admin approval buttons are attached to every pending screenshot/withdrawal submission:

- Approve unlocks the user. For `express_sell` / `wallet_deposit`, Approve is blocked until on-chain verification is `✅ VERIFIED` (or `⚠️ MANUAL` on unsupported networks).
- Approve for `express_sell` increments user and global SAFE-SOLD stats.
- Approve for `wallet_deposit` credits wallet balance and increments user/global SAFE-SOLD stats.
- Approve for `withdrawal` debits wallet balance.
- Reject unlocks the user and sends retry/support instructions.

## Branding Assets

The bot generates a MARCO banner image automatically for `/start` cards. To use a custom astronaut/shield banner, set:

```env
BANNER_IMAGE_PATH=C:\absolute\path\to\banner.png
```

## Notes

- Message copy and button labels are centralized in `marco_bot/messages.py` and `marco_bot/constants.py`.
- The reply-keyboard cooldown label is computed from `users.post_ad_cooldown_until`.
- Today's global total resets by the configured `TIMEZONE` date.
- Long polling is used for simple hosting. For production, run it behind a process manager and make sure your Telegram bot/channel/group permissions are correct.
