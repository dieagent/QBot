from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from marco_bot.handlers import user


def test_send_welcome_falls_back_to_text(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class DummyUser:
        user_id = 123
        first_name = "Friend"
        post_ad_cooldown_until = None

    @asynccontextmanager
    async def fake_session_scope():
        yield object()

    async def fake_photo(*args, **kwargs):
        raise RuntimeError("photo send failed")

    async def fake_message(session, bot, user_id, chat_id, text, reply_markup=None, parse_mode=None, entities=None):
        calls.append(("message", text))

    monkeypatch.setattr(user, "session_scope", fake_session_scope)
    monkeypatch.setattr(user, "send_tracked_menu_photo", fake_photo)
    monkeypatch.setattr(user, "send_tracked_menu_message", fake_message)

    target = SimpleNamespace(bot=object(), chat=SimpleNamespace(id=456))
    asyncio.run(user.send_welcome(target, DummyUser()))

    assert calls == [("message", user.msg.welcome_render())]