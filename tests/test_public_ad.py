from __future__ import annotations

import asyncio
from types import SimpleNamespace

from marco_bot.config import Settings
from marco_bot.handlers import user
from marco_bot.models import Ad


def _settings() -> Settings:
    return Settings(
        bot_token="123456:ABC",
        database_url="sqlite+aiosqlite:///./test.sqlite3",
        admin_ids=[],
        admin_review_chat_id=None,
        ads_channel_id="@MARCO_P2P",
        ads_group_id="-1001234567890",
        required_groups=[],
        post_ad_cooldown_seconds=10800,
        timezone="Asia/Kolkata",
        support_url="https://t.me/MARCO_Escrow_Chat",
        banner_image_path=None,
        deposit_addresses={},
        trx_address=None,
        bnb_address=None,
        eth_address=None,
        etherscan_api_key=None,
        infura_url=None,
        infura_api_key=None,
        trongrid_api_key=None,
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_phone=None,
    )


def test_post_public_ad_posts_to_channel_and_group(monkeypatch) -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def fake_send_message(chat_id, text, reply_markup=None, parse_mode=None):
        calls.append((str(chat_id), text, parse_mode))
        return SimpleNamespace(message_id=101 if len(calls) == 1 else 202)

    fake_bot = SimpleNamespace(send_message=fake_send_message)
    fake_callback = SimpleNamespace(bot=fake_bot, message=SimpleNamespace(answer=lambda *_args, **_kwargs: None))
    ad = Ad(
        ref_code="ABC12345",
        user_id=1,
        side="sell",
        coin="USDT",
        chain="BEP20",
        funds_source="Legit",
        rate=94,
        amount=100,
        payment_method="UPI",
        dm_username="demo",
    )

    monkeypatch.setattr(user, "settings", _settings)

    asyncio.run(user.post_public_ad(fake_callback, ad, {"side": "sell", "coin": "USDT", "chain": "BEP20", "funds_source": "Legit", "rate": "94", "amount": "100", "payment_method": "UPI"}, "demo"))

    assert calls == [
        ("@MARCO_P2P", user.msg.ad_text({"side": "sell", "coin": "USDT", "chain": "BEP20", "funds_source": "Legit", "rate": "94", "amount": "100", "payment_method": "UPI"}, "demo", preview=False), "HTML"),
        ("-1001234567890", user.msg.ad_text({"side": "sell", "coin": "USDT", "chain": "BEP20", "funds_source": "Legit", "rate": "94", "amount": "100", "payment_method": "UPI"}, "demo", preview=False), "HTML"),
    ]
    assert ad.channel_msg_id == 101
    assert ad.group_msg_id == 202