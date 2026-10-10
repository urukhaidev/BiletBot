import hashlib
import hmac
import json
from datetime import date
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from mini_app.auth import authenticate
from mini_app.server import SearchForm, app, build_searches, user


def signed(data, token="test"):
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    return urlencode({**data, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})


def test_telegram_auth_rejects_forgery_and_expired_data():
    data = {"user": json.dumps({"id": 123}), "auth_date": "1000", "query_id": "abc"}
    init = signed(data)
    assert authenticate(init, "test", now=1050)["id"] == 123
    with pytest.raises(ValueError):
        authenticate(init, "wrong", now=1050)
    with pytest.raises(ValueError):
        authenticate(init, "test", now=100000)
    with pytest.raises(ValueError):
        authenticate(init + "&user=forged", "test", now=1050)


def test_multiple_months_and_both_trip_types():
    form = SearchForm(origin="Москва", destination="Сочи", months=[date(2027, 11, 1), date(2027, 12, 1)],
                      baggage=True, direct=True, duration_min=7, duration_max=15)
    searches = build_searches(form, ("MOW", "Москва"), ("AER", "Сочи"), date(2027, 10, 1))
    assert [s.mode for s in searches] == ["OW_MONTH", "RT_MONTH", "OW_MONTH", "RT_MONTH"]
    assert all(s.direct and s.baggage for s in searches)
    assert searches[1].duration_max == 15


def test_exact_return_and_range_validation():
    form = SearchForm(origin="Москва", destination="Сочи", date_mode="dates", trip_type="RT",
                      departure=date(2027, 11, 10), returning=date(2027, 11, 17))
    searches = build_searches(form, ("MOW", "Москва"), ("AER", "Сочи"), date(2027, 10, 1))
    assert searches[0].mode == "RT_DATES"
    with pytest.raises(ValueError):
        SearchForm(origin="Москва", destination="Сочи", date_mode="range", departure=date(2027, 11, 10))
    with pytest.raises(ValueError):
        build_searches(form, ("MOW", "Москва"), ("AER", "Сочи"), date(2028, 1, 1))


def test_static_page_and_private_job_ownership():
    app.dependency_overrides[user] = lambda: {"id": 1}
    app.state.jobs = {"other": {"user_id": 2, "status": "done"}}
    try:
        client = TestClient(app)
        assert client.get("/mini-app").status_code == 200
        assert client.get("/mini-app/static/app.js").status_code == 200
        assert client.get("/mini-app/api/search/other").status_code == 404
    finally:
        app.dependency_overrides.clear()


async def test_history_only_returns_current_user(tmp_path):
    from biletbot.storage import Storage
    from mini_app.server import history
    store = Storage(str(tmp_path / "history.sqlite3"))
    store.db.execute("CREATE TABLE mini_history(id TEXT, user_id INTEGER, form TEXT, result TEXT, created_at TEXT)")
    store.db.executemany("INSERT INTO mini_history VALUES (?,?,?,?,?)", [
        ("mine", 1, '{"origin":"Москва"}', '[]', "2026-10-09"),
        ("other", 2, '{}', '[]', "2026-10-09"),
    ])
    store.db.commit()
    own = SearchForm(origin="Москва", destination="Сочи", months=[date(2027, 11, 1)])
    search = build_searches(own, ("MOW", "Москва"), ("AER", "Сочи"), date(2027, 10, 1))[0]
    store.save_search(1, 1, search)
    store.save_search(2, 2, search)
    app.state.storage = store
    app.dependency_overrides[user] = lambda: {"id": 1}
    try:
        response = await history(me={"id": 1})
        assert {r["id"] for r in response} == {"mine", "bot-1"}
        restored = next(r for r in response if r["source"] == "bot")
        assert restored["form"]["months"] == ["2027-11-01"]
    finally:
        app.dependency_overrides.clear()
        store.db.close()


async def test_place_suggestions_personal_history_and_popularity(tmp_path):
    from biletbot.storage import Storage
    from mini_app.server import place_suggestions
    store = Storage(str(tmp_path / "places.sqlite3"))
    base = SearchForm(origin="Москва", destination="Сочи", months=[date(2027, 11, 1)])
    search = build_searches(base, ("MOW", "Москва"), ("AER", "Сочи"), date(2027, 10, 1))[0]
    cities = [("MOW", "Москва"), ("LED", "Санкт-Петербург"), ("KZN", "Казань"), ("SVX", "Екатеринбург")]
    for code, name in cities:
        store.save_search(1, 1, search.model_copy(update={"origin": code, "origin_name": name}))
    for _ in range(10):
        store.save_search(1, 1, search.model_copy(update={"origin": "SVX", "origin_name": "Екатеринбург"}))
    store.save_search(2, 2, search.model_copy(update={"origin": "MOW", "destination": "IST", "destination_name": "Стамбул"}))
    app.state.storage = store
    try:
        origin = await place_suggestions("origin", me={"id": 1})
        assert [p["code"] for p in origin["recent"]] == ["SVX", "KZN", "LED"]
        assert origin["popular"][0]["code"] == "MOW"
        assert len(origin["popular"]) == len({p["code"] for p in origin["popular"]}) == 5
        destination = await place_suggestions("destination", me={"id": 1})
        assert [p["code"] for p in destination["recent"]] == ["AER"]
        assert len(destination["popular"]) == 5
        newcomer = await place_suggestions("origin", me={"id": 3})
        assert newcomer["recent"] == []
    finally:
        store.db.close()


async def test_tracking_sends_price_choices_and_help(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from biletbot.storage import Storage
    from mini_app.server import track, help_message, create_alert, AlertForm
    store = Storage(str(tmp_path / "track.sqlite3"))
    form = SearchForm(origin="Москва", destination="Сочи", months=[date(2027, 11, 1)])
    search = build_searches(form, ("MOW", "Москва"), ("AER", "Сочи"), date(2027, 10, 1))[0]
    sid = store.save_search(1, 1, search)
    store.db.execute("CREATE TABLE mini_history(user_id INTEGER, result TEXT, created_at TEXT)")
    store.db.execute("INSERT INTO mini_history VALUES (?,?,?)", (1, json.dumps([{"search_id": sid, "tickets": [{"price": 9000}]}]), "2026-10-09"))
    store.db.commit()
    app.state.storage = store
    app.state.bot = SimpleNamespace(send_message=AsyncMock())
    try:
        assert await track(sid, me={"id": 1}) == {"ok": True}
        markup = app.state.bot.send_message.call_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == f"price:{sid}:9000"
        assert await help_message(me={"id": 1}) == {"ok": True}
        assert "/alerts" in app.state.bot.send_message.call_args.args[1]
        assert await create_alert(AlertForm(search_id=sid, price=8000), me={"id": 1}) == {"ok": True}
        assert store.alerts(1)[0]["threshold"] == 8000
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            await create_alert(AlertForm(search_id=sid, price=7000), me={"id": 2})
    finally:
        store.db.close()
