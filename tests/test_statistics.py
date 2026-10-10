from datetime import datetime
from zoneinfo import ZoneInfo

from biletbot.statistics import info_text
from biletbot.statistics import send_info
from types import SimpleNamespace
import httpx
import json
from urllib.parse import parse_qs
from biletbot.storage import Storage


def test_info_periods_use_local_midnight_and_unique_users(tmp_path):
    store = Storage(str(tmp_path / "stats.sqlite3"))
    try:
        store.import_users(["1", "2", "3"])
        for uid, timestamp in [(1, "2026-10-09 21:00:00"), (1, "2026-10-10 10:00:00"),
                               (2, "2026-10-09 20:59:59"), (2, "2026-10-04 21:00:00"),
                               (3, "2026-09-10 21:00:00")]:
            store.db.execute("INSERT INTO searches(user_id,chat_id,params,created_at) VALUES (?,?,?,?)",
                             (uid, uid, "{}", timestamp))
        result = info_text(store, ZoneInfo("Europe/Moscow"), datetime(2026, 10, 10, 18, tzinfo=ZoneInfo("Europe/Moscow")))
        lines = {line.split()[0]: line.split()[1:] for line in result.split("<pre>")[1].split("</pre>")[0].splitlines()[1:3]}
        assert lines["Всего"] == ["5", "3", "1.67"]
        assert lines["Сегодня"] == ["2", "1", "2.00"]
        assert "Вчера" in result and "7 дней" in result and "30 дней" in result
        assert "Подписок на пользователя: 0.00" in result
    finally:
        store.db.close()


async def test_info_uses_native_rich_table_with_subscriptions(tmp_path):
    store = Storage(str(tmp_path / "rich-stats.sqlite3"))
    def respond(request):
        assert request.url.path.endswith("/sendRichMessage")
        data = parse_qs(request.content.decode())
        blocks = json.loads(data["rich_message"][0])["blocks"]
        table = blocks[1]
        assert table["type"] == "table"
        assert len(table["cells"]) == 6
        assert [c["text"] for c in table["cells"][0][-2:]] == ["Подписки всего", "Активные"]
        assert all(len(row) == 6 for row in table["cells"])
        assert table["cells"][-1][-1]["text"] == "0"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            api = SimpleNamespace(telegram_http=http, config=SimpleNamespace(telegram_token="test"))
            assert await send_info(api, 123, store, ZoneInfo("Europe/Moscow")) == {"message_id": 1}
    finally:
        store.db.close()
