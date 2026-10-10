from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from biletbot.models import Search
from biletbot.rich_messages import rich_blocks, send_search_result, send_search_results


def sample():
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    date_from=date(2027, 11, 10))
    ticket = dict(departure_at="2027-11-10", value=9000, number_of_changes=0, baggage_code="1PC23", duration=230, airline_name="Аэрофлот")
    return search, ticket


def test_native_table_and_photo_blocks():
    search, ticket = sample()
    blocks = rich_blocks(search, [ticket], "123")
    assert blocks[1]["type"] == "table"
    assert blocks[1]["cells"][1][0]["text"] == "10 ноября\nПрямой рейс\nВ пути 4 ч\nБагаж 23 кг\nАвиакомпания: Аэрофлот"
    assert blocks[1]["cells"][0][0]["text"] == "Билет"
    assert "Вариант" not in str(blocks)
    assert not any(b["type"] == "photo" for b in blocks)


def test_roundtrip_dates_and_durations_share_cells():
    search, ticket = sample()
    search = search.model_copy(update={"trip_type": "RT"})
    ticket.update(return_at="2027-11-17", segments=[
        {"departure_at": "2027-11-10T10:00:00+03:00", "arrival_at": "2027-11-10T13:30:00+03:00"},
        {"departure_at": "2027-11-17T10:00:00+03:00", "arrival_at": "2027-11-17T14:15:00+03:00"},
    ])
    blocks = rich_blocks(search, [ticket], "123")
    table = blocks[1]
    assert len(table["cells"][0]) == 2
    assert table["cells"][1][0]["text"] == "10 ноября — 17 ноября\nПрямой рейс\nВ пути 4 ч / 4 ч\nБагаж 23 кг\nАвиакомпания: Аэрофлот"
    assert [c["text"] for c in table["cells"][0]] == ["Билет", "Цена"]
    link = table["cells"][1][1]["text"]
    assert link["type"] == "url"
    assert link["text"] == "👉 9 000 ₽"
    assert "MOW1011AER17111" in link["url"]
    assert len(blocks) == 2


async def test_single_multipart_message_includes_image_and_text():
    search, ticket = sample()

    def respond(request):
        assert request.url.path.endswith("/sendRichMessage")
        assert b"image/png" in request.content
        assert b"attach://ticket1" in request.content
        assert b'"type": "table"' in request.content
        assert b"track:42:9000" in request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        api = SimpleNamespace(http=http, config=SimpleNamespace(telegram_token="secret", marker="123"))
        assert await send_search_result(api, 1, search, [ticket], 42) == {"message_id": 1}


async def test_error_does_not_expose_token():
    search, ticket = sample()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(
            400, json={"ok": False, "description": "bad secret"}))) as http:
        api = SimpleNamespace(http=http, config=SimpleNamespace(telegram_token="secret", marker="123"))
        with pytest.raises(ValueError, match="REDACTED"):
            await send_search_result(api, 1, search, [ticket], 42)


async def test_combined_month_has_six_tickets_and_one_first_photo():
    import json
    from email.parser import BytesParser
    from email.policy import default

    search = Search(origin="MOW", destination="BKK", origin_name="Москва", destination_name="Бангкок",
                    month=date(2027, 10, 1), trip_type_explicit=False, query="Москва Бангкок в октябре")
    ow = [dict(departure_at=f"2027-10-{10+i}", value=30000+i*1000, number_of_changes=0,
               baggage_code="1PC23", duration=600) for i in range(3)]
    rt = [{**t, "return_at": f"2027-10-{17+i}", "value": 60000+i*1000} for i, t in enumerate(ow)]

    def respond(request):
        message = BytesParser(policy=default).parsebytes(
            b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.content)
        parts = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in message.iter_parts()}
        blocks = json.loads(parts["rich_message"])["blocks"]
        assert blocks[0]["type"] == "photo"
        assert sum(b["type"] == "photo" for b in blocks) == 1
        tables = [b for b in blocks if b["type"] == "table"]
        assert len(tables) == 2
        assert [len(t["cells"]) for t in tables] == [4, 4]
        assert all(len(row) == 2 for table in tables for row in table["cells"])
        assert tables[1]["cells"][1][0]["text"].startswith("10 октября — 17 октября\nПрямой рейс")
        assert blocks[-2]["type"] == "footer"
        assert blocks[-1] == {"type": "paragraph", "text": {"type": "code", "text": "Москва Бангкок в октябре"}}
        assert "ticket1" in parts and "ticket2" not in parts
        keyboard = json.loads(parts["reply_markup"])["inline_keyboard"]
        assert len(keyboard) == 3
        assert keyboard[-1][0] == {"text": "Дополнить / изменить запрос", "callback_data": "edit:1"}
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        api = SimpleNamespace(http=http, config=SimpleNamespace(telegram_token="secret", marker="123"))
        await send_search_results(api, 1, [(search, ow, 1), (search.variants()[1], rt, 2)])
