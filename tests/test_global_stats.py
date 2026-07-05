from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

from marco_bot.handlers import user
from marco_bot.models import GlobalStats


def test_global_stats_keeps_poster_visible(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class DummySession:
        def __init__(self) -> None:
            self.stats = GlobalStats(
                id=1,
                total_safe_sold_amount=Decimal("123.45"),
                today_safe_sold_amount=Decimal("67.89"),
                total_deals_completed=5,
            )

        async def get(self, model, pk):
            return self.stats

        async def flush(self):
            return None

    @asynccontextmanager
    async def fake_session_scope():
        yield DummySession()

    async def fake_sleep(_seconds):
        return None

    async def fake_send_tracked_menu_photo(session, bot, user_id, chat_id, photo, caption, reply_markup=None, parse_mode=None, caption_entities=None):
        calls.append(("photo", caption))
        return SimpleNamespace(message_id=777)

    async def fail_if_message(*args, **kwargs):
        raise AssertionError("show_global_stats should not send a second message")

    edit_calls: list[tuple[int, str]] = []

    async def fake_edit_message_caption(chat_id, message_id, caption, parse_mode=None):
        edit_calls.append((message_id, caption))

    fake_bot = SimpleNamespace(edit_message_caption=fake_edit_message_caption)
    fake_message = SimpleNamespace(from_user=SimpleNamespace(id=42), chat=SimpleNamespace(id=99), bot=fake_bot)

    monkeypatch.setattr(user, "session_scope", fake_session_scope)
    monkeypatch.setattr(user, "asyncio", SimpleNamespace(sleep=fake_sleep))
    monkeypatch.setattr(user, "send_tracked_menu_photo", fake_send_tracked_menu_photo)
    monkeypatch.setattr(user, "send_tracked_menu_message", fail_if_message)
    monkeypatch.setattr(user, "settings", lambda: SimpleNamespace(timezone="Asia/Kolkata"))

    asyncio.run(user.show_global_stats(fake_message))

    assert calls == [("photo", user.msg.loading_animation(10))]
    assert edit_calls[0] == (777, user.msg.loading_animation(30))
    assert edit_calls[-1][0] == 777
    assert "Global Stats" in edit_calls[-1][1]