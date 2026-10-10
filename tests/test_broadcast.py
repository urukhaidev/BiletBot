from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.error import Forbidden, RetryAfter

from biletbot.broadcast import Broadcast
from biletbot.storage import Storage
from biletbot.models import Search
from datetime import date


def update(uid, text=None, photo=None):
    message = SimpleNamespace(text=text, photo=photo, media_group_id=None, chat_id=uid,
                              message_id=42, reply_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=uid),
                           effective_chat=SimpleNamespace(id=uid), effective_message=message)


def test_import_users_is_idempotent_and_excludes_groups(tmp_path):
    store = Storage(str(tmp_path / "users.sqlite3"))
    try:
        assert store.import_users(["user_id", "123", "123", "456", "-100123", ""]) == 2
        assert store.import_users(["123", "456"]) == 0
        store.deactivate_user(123)
        assert store.broadcast_users() == [456]
        store.register_user(123)
        assert store.broadcast_users() == [123, 456]
    finally:
        store.db.close()


def test_saved_private_search_adds_broadcast_recipient(tmp_path):
    store = Storage(str(tmp_path / "search-users.sqlite3"))
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи", month=date(2027, 11, 1))
    try:
        assert store.broadcast_users() == []
        store.save_search(123, -100456, search)
        assert store.broadcast_users() == []
        store.save_search(123, 123, search)
        assert store.broadcast_users() == [123]
    finally:
        store.db.close()


async def test_only_admin_can_start_and_cancel_broadcast(tmp_path):
    store = Storage(str(tmp_path / "users.sqlite3"))
    try:
        broadcast = Broadcast(store, 123)
        context = SimpleNamespace(bot=SimpleNamespace())
        assert await broadcast.handle(update(456, "/admin"), context)
        assert not broadcast.waiting
        admin = update(123, "/admin")
        assert await broadcast.handle(admin, context)
        assert broadcast.waiting
        assert "Людей в базе:" in admin.effective_message.reply_text.call_args.args[0]
        assert not await broadcast.handle(update(456, "hello"), context)
        assert await broadcast.handle(update(123, "/cancel"), context)
        assert not broadcast.waiting
    finally:
        store.db.close()


async def test_broadcast_copies_photo_and_retries_rate_limit(tmp_path):
    store = Storage(str(tmp_path / "users.sqlite3"))
    store.import_users(["1", "2", "3"])
    bot = SimpleNamespace(copy_message=AsyncMock(side_effect=[RetryAfter(1), None, Forbidden("blocked"), None]),
                          send_message=AsyncMock())
    broadcast = Broadcast(store, 123)
    context = SimpleNamespace(bot=bot)
    try:
        await broadcast.handle(update(123, "/admin"), context)
        with patch("biletbot.broadcast.asyncio.sleep", new=AsyncMock()):
            assert await broadcast.handle(update(123, photo=["photo"]), context)
            await broadcast.task
        assert bot.copy_message.await_count == 4
        assert bot.copy_message.call_args.kwargs == {"chat_id": 3, "from_chat_id": 123, "message_id": 42}
        assert store.broadcast_users() == [1, 3]
        assert "Доставлено: 2" in bot.send_message.call_args.args[1]
        assert "Бот заблокирован: 1" in bot.send_message.call_args.args[1]
    finally:
        store.db.close()


async def test_broadcast_plain_text_starts_sending(tmp_path):
    store = Storage(str(tmp_path / "text.sqlite3"))
    store.import_users(["1"])
    bot = SimpleNamespace(copy_message=AsyncMock(), send_message=AsyncMock())
    broadcast = Broadcast(store, 123)
    context = SimpleNamespace(bot=bot)
    try:
        await broadcast.handle(update(123, "/admin"), context)
        with patch("biletbot.broadcast.asyncio.sleep", new=AsyncMock()):
            assert await broadcast.handle(update(123, "Привет! Новые билеты"), context)
            assert not broadcast.waiting
            await broadcast.task
        bot.copy_message.assert_awaited_once_with(chat_id=1, from_chat_id=123, message_id=42)
    finally:
        store.db.close()
