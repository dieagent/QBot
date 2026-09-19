from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramBadRequest

from marco_bot import animation


def run(coro):
    return asyncio.run(coro)


class FakeMessage:
    def __init__(self, fail_text: bool = False):
        self.edits: list[str] = []
        self.caption_edits: list[str] = []
        self.deleted = False
        self.fail_text = fail_text

    async def edit_text(self, text: str):
        if self.fail_text:
            raise TelegramBadRequest(method=None, message="there is no text in the message to edit")
        self.edits.append(text)

    async def edit_caption(self, caption: str | None = None, **kwargs):
        self.caption_edits.append(caption or "")

    async def delete(self):
        self.deleted = True


class FakeCallback:
    def __init__(self, message):
        self.message = message
        self.answered = False

    @property
    def data(self):
        return "nav:back"

    async def answer(self, *args, **kwargs):
        self.answered = True


def test_bar_frames_progress_to_100():
    frames = animation.bar_frames("Loading payment methods", steps=4)
    assert len(frames) == 4
    assert "25%" in frames[0] and "Loading payment methods" in frames[0]
    assert "100%" in frames[-1] and frames[-1].endswith("✅")
    assert "█" in frames[-1]


def test_spinner_frames_cycle():
    frames = animation.spinner_frames("Connecting", cycles=5)
    assert len(frames) == 5
    assert all("Connecting" in frame for frame in frames)
    assert len({frame for frame in frames}) > 1  # frames actually differ


def test_animate_action_enabled_edits_then_deletes(monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    async def scenario():
        message = FakeMessage()
        callback = FakeCallback(message)
        await animation.animate_action(callback, "Going back", enabled=True)
        assert callback.answered
        assert message.deleted
        assert len(message.edits) == len(animation.bar_frames("Going back"))
        assert message.edits[-1].endswith("✅")

    run(scenario())


def test_animate_action_disabled_skips_animation():
    async def scenario():
        message = FakeMessage()
        callback = FakeCallback(message)
        await animation.animate_action(callback, "Going back", enabled=False)
        assert callback.answered
        assert message.deleted
        assert message.edits == []

    run(scenario())


def test_animate_action_uses_caption_for_photo_messages(monkeypatch):
    async def no_sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    async def scenario():
        message = FakeMessage(fail_text=True)
        callback = FakeCallback(message)
        await animation.animate_action(callback, "Opening wallet", enabled=True)
        assert not message.edits
        assert len(message.caption_edits) == len(animation.bar_frames("Opening wallet"))
        assert message.deleted

    run(scenario())


def test_animate_action_without_message_still_answers():
    async def scenario():
        callback = FakeCallback(message=None)
        await animation.animate_action(callback, "Anything", enabled=True)
        assert callback.answered

    run(scenario())
