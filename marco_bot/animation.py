"""Short in-place loading animations for menus (Telegram message-edit trick).

Telegram bots can't send real animations on demand, but editing a message
through a few "frames" (progress bar / spinner) before showing the final
content gives a nice loading effect — same idea as the Global Stats loader.

Frames are played by editing the callback's message in place (works for both
text messages and photo captions), then the caller continues its normal
flow (usually deleting the message and sending the final menu). Kept to
~2 seconds so it feels snappy and stays well within serverless time limits.

Turn everything off with UI_ANIMATIONS=off.
"""
from __future__ import annotations

import asyncio

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, Message

FRAME_INTERVAL = 0.45  # seconds between frames (rate-limit friendly)
BAR_WIDTH = 10

SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴"]


def bar_frames(title: str, steps: int = 4) -> list[str]:
    """Progress bar frames ending at 100%: '⏳ Title...\n[██████░░░░] 60%'"""
    frames: list[str] = []
    for i in range(1, steps + 1):
        percent = (100 * i) // steps
        filled = BAR_WIDTH * i // steps
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        suffix = " ✅" if percent >= 100 else ""
        frames.append(f"⏳ {title}\n[{bar}] {percent}%{suffix}")
    return frames


def spinner_frames(title: str, cycles: int = 5) -> list[str]:
    """Braille spinner frames: '⠙ Connecting to blockchain...'"""
    frames: list[str] = []
    for i in range(cycles):
        dot = SPINNER[i % len(SPINNER)]
        ellipsis = "." * (1 + i % 3)
        frames.append(f"{dot} {title}{ellipsis}")
    return frames


def frames_for(style: str, title: str) -> list[str]:
    if style == "spinner":
        return spinner_frames(title)
    return bar_frames(title)


async def _set_message_content(message: Message, text: str) -> None:
    """Edit a message whether it is a text message or a photo caption."""
    try:
        await message.edit_text(text)
    except TelegramBadRequest:
        await message.edit_caption(caption=text)


async def play_frames(message: Message, frames: list[str], interval: float = FRAME_INTERVAL) -> None:
    for frame in frames:
        try:
            await _set_message_content(message, frame)
        except TelegramBadRequest:
            return  # message gone or uneditable — stop the animation quietly
        await asyncio.sleep(interval)


async def animate_action(
    callback: CallbackQuery,
    title: str,
    *,
    enabled: bool = True,
    style: str = "bar",
) -> None:
    """Answer the callback, play a loading animation, then delete the message.

    Drop-in replacement for the old delete_callback_message + callback.answer
    pair used across menu handlers: the user sees a ~2s loading effect before
    the next menu lands. Disabled via settings; falls back to plain behaviour.
    """
    try:
        await callback.answer()
    except TelegramBadRequest:
        pass
    message = callback.message
    if message is None:
        return
    if enabled:
        await play_frames(message, frames_for(style, title))
    try:
        await message.delete()
    except TelegramBadRequest:
        pass
