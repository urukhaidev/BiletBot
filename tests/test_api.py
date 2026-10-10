from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from biletbot.api import API
from biletbot.models import Search


def config():
    return SimpleNamespace(travel_token="test", request_interval=0)


async def test_structured_llm_includes_router_json_marker():
    import json

    cfg = SimpleNamespace(llm_model="test", llm_url="https://router.example/v1", llm_key="test")
    api = API(cfg)
    await api.http.aclose()

    def respond(request):
        body = json.loads(request.content)
        assert "json" in body["messages"][0]["content"]
        assert "json" in body["messages"][1]["content"]
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    api.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    try:
        assert await api.llm("Верни параметры", "Москва Сочи", structured=True) == '{"ok":true}'
    finally:
        await api.http.aclose()


async def test_graphql_errors_are_not_empty_results():
    api = API(config())
    await api.http.aclose()
    api.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"errors": [{"message": "Access denied"}]})))
    try:
        with pytest.raises(ValueError, match="Access denied"):
            await api.request_graphql("query { test }")
    finally:
        await api.http.aclose()


async def test_fetches_next_page_and_filters_results():
    api = API(config())
    api.today = lambda: date(2027, 1, 1)
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    date_from=date(2027, 1, 10), baggage=True)
    fare = dict(origin_city_iata="MOW", destination_city_iata="AER", departure_at="2027-01-10",
                value=9000, number_of_changes=0, baggage_code="0PC")
    valid = {**fare, "baggage_code": "1PC23", "value": 8000}
    api.request_graphql = AsyncMock(side_effect=[
        {"data": {"prices_one_way": [fare] * 400}},
        {"data": {"prices_one_way": [valid]}},
    ])
    try:
        assert await api.flights(search) == [valid]
        assert "offset: 400" in api.request_graphql.call_args_list[1].args[0]
    finally:
        await api.http.aclose()


async def test_interactive_search_does_not_fetch_all_pages():
    api = API(config())
    api.today = lambda: date(2027, 1, 1)
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    date_from=date(2027, 1, 10))
    fare = dict(origin_city_iata="MOW", destination_city_iata="AER", departure_at="2027-01-10",
                value=9000, number_of_changes=0, baggage_code="1PC")
    api.request_graphql = AsyncMock(return_value={"data": {"prices_one_way": [fare] * 400}})
    try:
        await api.flights(search, all_pages=False)
        assert api.request_graphql.await_count == 2
        assert all("offset: 0" in call.args[0] for call in api.request_graphql.call_args_list)
        assert "direct: true" in api.request_graphql.call_args_list[1].args[0]
    finally:
        await api.http.aclose()


async def test_egypt_search_covers_three_destinations():
    api = API(config())
    search = Search(query="Сочи Египет прямой", origin="AER", destination="HRG", origin_name="Сочи",
                    destination_name="Хургада", month=date(2027, 11, 1), direct=True)

    async def fares(variant, **kwargs):
        return [{"destination_city_iata": variant.destination, "value": 10000}]

    api.flights = AsyncMock(side_effect=fares)
    try:
        result = await api.search_flights(search, all_pages=False)
        assert {t["destination_city_iata"] for t in result} == {"HRG", "SSH", "CAI"}
        assert all(call.args[0].direct for call in api.flights.call_args_list)
    finally:
        await api.http.aclose()


async def test_interactive_search_adds_direct_fares_outside_first_page():
    api = API(config())
    api.today = lambda: date(2027, 1, 1)
    search = Search(origin="MOW", destination="MLE", origin_name="Москва", destination_name="Мале",
                    month=date(2027, 1, 1), baggage=True)
    connecting = dict(origin_city_iata="MOW", destination_city_iata="MLE", departure_at="2027-01-10",
                      value=9000, number_of_changes=1, baggage_code="1PC23")
    direct = {**connecting, "value": 20000, "number_of_changes": 0}
    api.request_graphql = AsyncMock(side_effect=[
        {"data": {"prices_one_way": [connecting] * 400}},
        {"data": {"prices_one_way": [direct, {**direct, "baggage_code": "0PC"}]}},
    ])
    try:
        fares = await api.flights(search, all_pages=False)
        assert direct in fares
        assert len(fares) == 401
        query = api.request_graphql.call_args_list[1].args[0]
        assert "direct: true" in query and "with_baggage: true" in query
    finally:
        await api.http.aclose()
