from __future__ import annotations

import asyncio
from types import SimpleNamespace

from marco_bot.services import _photo_cache_key, _photo_file_id_cache, _send_photo_cached


class FakeInputFile:
    def __init__(self, path=None, filename=None):
        if path is not None:
            self.path = path
        if filename is not None:
            self.filename = filename


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_photo(self, chat_id, photo, **kwargs):
        self.sent.append(photo)
        return SimpleNamespace(photo=[SimpleNamespace(file_id="SMALL"), SimpleNamespace(file_id="BIG_FILE_ID")])


def run(coro):
    return asyncio.run(coro)


def setup_function():
    _photo_file_id_cache.clear()


def test_cache_key_from_path_and_filename():
    assert _photo_cache_key(FakeInputFile(path="/tmp/banner.jpg")) == "path:/tmp/banner.jpg"
    assert _photo_cache_key(FakeInputFile(filename="brand.png")) == "file:brand.png"
    assert _photo_cache_key(object()) is None


def test_first_send_uploads_then_caches_file_id():
    bot = FakeBot()
    photo = FakeInputFile(path="/tmp/banner.jpg")
    run(_send_photo_cached(bot, 1, photo, caption="one"))
    run(_send_photo_cached(bot, 1, FakeInputFile(path="/tmp/banner.jpg"), caption="two"))
    # first send passed the input file, second send reused the cached file_id
    assert bot.sent[0] is photo
    assert bot.sent[1] == "BIG_FILE_ID"


def test_distinct_photos_cached_independently():
    bot = FakeBot()
    run(_send_photo_cached(bot, 1, FakeInputFile(filename="a.png")))
    run(_send_photo_cached(bot, 1, FakeInputFile(filename="b.png")))
    assert len(bot.sent) == 2
    assert all(getattr(sent, "filename", None) for sent in bot.sent)
