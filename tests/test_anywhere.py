import asyncio
from datetime import date
from types import SimpleNamespace
import httpx
from biletbot.api import API
from biletbot.models import Search
from biletbot.messages import select_tickets


def test_anywhere_rest_cheapest_per_destination_and_return_month():
    async def run():
        api = API(SimpleNamespace(travel_token="test", request_interval=0))
        await api.http.aclose()
        api.today = lambda: date(2026, 10, 10)
        async def resolve(code):
            return code, code
        api.resolve = resolve
        search = Search(origin="MOW", destination="ANY", origin_name="Москва", destination_name="Куда угодно",
                        anywhere=True, month=date(2026, 11, 1), trip_type="RT")
        def respond(request):
            assert request.url.path.endswith("prices_for_dates")
            assert request.url.params["one_way"] == "false"
            assert request.url.params["return_at"] == "2026-11"
            row = dict(origin="MOW", destination="AER", departure_at="2026-11-01", return_at="2026-11-20", price=9000)
            return httpx.Response(200, json={"success": True, "data": [row, {**row, "price": 8000}]})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api.http = client
            tickets = await api.search_flights(search, all_pages=False)
            assert len(tickets) == 1 and tickets[0]["value"] == 8000
            assert select_tickets(search, tickets) == tickets
    asyncio.run(run())
