from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from biletbot.api import API
from biletbot.models import Search
from biletbot.monitor import Monitor
from biletbot.storage import Storage


def search(**overrides):
    return Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                  date_from=date(2027, 1, 10), **overrides)


def ticket(price=9000, **overrides):
    return dict(origin_city_iata="MOW", destination_city_iata="AER", departure_at="2027-01-10T12:00:00",
                value=price, number_of_changes=0, baggage_code="1PC23", **overrides)


def setup(tmp_path, threshold=10000):
    store = Storage(str(tmp_path / "bot.sqlite3"))
    sid = store.save_search(1, 1, search())
    store.subscribe(sid, 1, 1, threshold)
    api = SimpleNamespace(today=lambda: date(2027, 1, 1), flights=AsyncMock(return_value=[ticket()]))
    bot = SimpleNamespace(send_message=AsyncMock())
    return store, api, bot, Monitor(store, api, bot, SimpleNamespace(marker="123"))


async def test_threshold_and_further_drop(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    api.flights.return_value = [ticket(10000)]
    await monitor.check_once()
    bot.send_message.assert_not_called()
    api.flights.return_value = [ticket(9000)]
    await monitor.check_once()
    await monitor.check_once()
    assert bot.send_message.call_count == 1
    api.flights.return_value = [ticket(8500)]
    await monitor.check_once()
    assert bot.send_message.call_count == 2
    assert store.alerts()[0]["last_notified"] == 8500


async def test_restart_no_duplicate(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    await monitor.check_once()
    store.db.close()
    restarted = Storage(str(tmp_path / "bot.sqlite3"))
    await Monitor(restarted, api, bot, SimpleNamespace(marker="123")).check_once()
    assert bot.send_message.call_count == 1


async def test_delivery_failure_retried(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    bot.send_message.side_effect = RuntimeError("network")
    await monitor.check_once()
    assert store.alerts()[0]["last_notified"] is None
    bot.send_message.side_effect = None
    await monitor.check_once()
    assert bot.send_message.call_count == 2
    assert store.alerts()[0]["last_notified"] == 9000


async def test_api_failure_does_not_stop_other_subscribers(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    sid = store.save_search(2, 2, search())
    store.subscribe(sid, 2, 2, 10000)
    api.flights.side_effect = [RuntimeError("API"), [ticket()]]
    await monitor.check_once()
    assert len(store.alerts()) == 2
    assert bot.send_message.call_count == 1
    assert store.alerts(1)[0]["last_error"] == "RuntimeError"


async def test_empty_result_then_price_appears(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    api.flights.return_value = []
    await monitor.check_once()
    assert len(store.alerts()) == 1
    api.flights.return_value = [ticket()]
    await monitor.check_once()
    bot.send_message.assert_called_once()


async def test_stop_during_request(tmp_path):
    store, api, bot, monitor = setup(tmp_path)

    async def stopped(search):
        store.stop(store.alerts()[0]["id"], 1)
        return [ticket()]

    api.flights.side_effect = stopped
    await monitor.check_once()
    bot.send_message.assert_not_called()


async def test_expired_alert_is_disabled(tmp_path):
    store, api, bot, monitor = setup(tmp_path)
    api.today = lambda: date(2027, 1, 11)
    await monitor.check_once()
    assert not store.alerts()
    api.flights.assert_not_called()
    bot.send_message.assert_not_called()


def test_ownership_and_pending(tmp_path):
    store, _, _, _ = setup(tmp_path)
    sid = store.alerts()[0]["search_id"]
    with pytest.raises(ValueError):
        store.subscribe(sid, 2, 2, 10000)
    assert not store.stop(store.alerts()[0]["id"], 2)
    store.set_pending(sid, 1, 1)
    assert store.pending(1, 1) == sid
    assert store.pending(1, 2) is None
    store.subscribe(sid, 1, 1, 8000)
    assert store.pending(1, 1) is None
    assert len(store.alerts()) == 1
    assert store.alerts()[0]["threshold"] == 8000


def test_edit_state_ownership_persistence_and_price_switch(tmp_path):
    store, _, _, _ = setup(tmp_path)
    sid = store.alerts()[0]["search_id"]
    with pytest.raises(ValueError):
        store.set_edit(sid, 2, 2)
    store.set_pending(sid, 1, 1)
    store.set_edit(sid, 1, 1)
    assert store.pending(1, 1) is None
    assert store.pending_edit(1, 1) == sid
    assert store.pending_edit(1, 2) is None
    store.db.close()
    store = Storage(str(tmp_path / "bot.sqlite3"))
    assert store.pending_edit(1, 1) == sid
    store.set_pending(sid, 1, 1)
    assert store.pending_edit(1, 1) is None


def test_roundtrip_constraints_and_graphql():
    s = search(trip_type="RT", date_to=date(2027, 1, 17), direct=True, baggage=True)
    field, args, fields = API.graphql(s)
    assert field == "prices_round_trip"
    assert 'return_dates: "2027-01-17"' in args
    assert "return_at" in fields
    assert s.matches(ticket(return_at="2027-01-17T12:00:00"), date(2027, 1, 1))
    assert not s.matches(ticket(return_at="2027-01-18T12:00:00"), date(2027, 1, 1))
    fare = ticket(return_at="2027-01-17T12:00:00")
    fare["baggage_code"] = "0PC"
    assert not s.matches(fare, date(2027, 1, 1))
    fare["baggage_code"] = "1PC"
    fare["number_of_changes"] = 1
    assert not s.matches(fare, date(2027, 1, 1))


def test_month_expiry_and_duration():
    s = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
               trip_type="RT", month=date(2028, 2, 1), duration_min=7, duration_max=9)
    assert s.last_departure() == date(2028, 2, 29)
    fare = ticket(return_at="2028-02-17T12:00:00")
    fare["departure_at"] = "2028-02-10T12:00:00"
    assert s.matches(fare, date(2028, 2, 1))
    fare["return_at"] = "2028-02-20T12:00:00"
    assert not s.matches(fare, date(2028, 2, 1))
