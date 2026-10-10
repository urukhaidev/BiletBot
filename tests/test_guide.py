import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from biletbot.guide import is_guide_query, send_guide
from biletbot.storage import Storage


@pytest.mark.parametrize("prefix", ["Куда сходить", "Что посмотреть", "Чем заняться", "Что попробовать", "Посоветуй отель", "Составь маршрут"])
def test_guide_requires_query_prefix(prefix):
    assert is_guide_query(prefix + " в Стамбуле")
    assert not is_guide_query("Подскажи, " + prefix)
    assert not is_guide_query(prefix + "другое")


async def test_guide_rejects_non_tourism_and_sends_rich_message():
    def respond(request):
        blocks = json.loads(parse_qs(request.content.decode())["rich_message"][0])["blocks"]
        assert blocks[1]["text"]["text"] == "Составь маршрут решения уравнения"
        assert "только на туристические" in blocks[2]["text"]
        assert "нетуристический ответ" not in str(blocks)
        return httpx.Response(200, json={"ok": True})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        api = SimpleNamespace(telegram_http=http, config=SimpleNamespace(telegram_token="test"),
                              llm=AsyncMock(return_value='{"tourism":false,"paragraphs":["нетуристический ответ"]}'))
        await send_guide(api, 1, "Составь маршрут решения уравнения")


def test_request_limit_shared_across_storage_connections(tmp_path):
    path = str(tmp_path / "limits.sqlite3")
    bot, mini = Storage(path), Storage(path)
    try:
        assert bot.request_wait(1, now=100) == 0
        assert mini.request_wait(1, now=101) == 9
        assert mini.request_wait(2, now=101) == 0
        assert mini.request_wait(1, now=109.5) == 1
        assert bot.request_wait(1, now=110) == 0
    finally:
        bot.db.close()
        mini.db.close()
