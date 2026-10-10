from datetime import date

import pytest

from biletbot.api import API
from biletbot.messages import search_results_text
from biletbot.models import Search


@pytest.mark.parametrize("params,mode,arguments", [
    ({"date_from": date(2027, 11, 10)}, "OW_DATE", ["depart_dates"]),
    ({"month": date(2027, 11, 1)}, "OW_MONTH", ["depart_months"]),
    ({"depart_date_min": date(2027, 11, 10), "depart_date_max": date(2027, 11, 20)},
     "OW_RANGE", ["depart_date_min", "depart_date_max"]),
    ({"trip_type": "RT", "date_from": date(2027, 11, 10), "date_to": date(2027, 11, 20)},
     "RT_DATES", ["depart_dates", "return_dates"]),
    ({"trip_type": "RT", "date_from": date(2027, 11, 10)},
     "RT_DATE_DUR", ["depart_dates", "trip_duration_min", "trip_duration_max"]),
    ({"trip_type": "RT", "month": date(2027, 11, 1)},
     "RT_MONTH", ["depart_months", "trip_duration_min", "trip_duration_max"]),
    ({"trip_type": "RT", "depart_date_min": date(2027, 11, 10), "depart_date_max": date(2027, 11, 20)},
     "RT_RANGE", ["depart_date_min", "depart_date_max", "trip_duration_min", "trip_duration_max"]),
])
def test_all_original_modes(params, mode, arguments):
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи", **params)
    assert search.mode == mode
    field, args, _ = API.graphql(search)
    assert field == ("prices_one_way" if mode.startswith("OW") else "prices_round_trip")
    for arg in arguments:
        assert f"{arg}:" in args
    if mode == "RT_DATES":
        assert "trip_duration_min" not in args


@pytest.mark.parametrize("params,count", [
    ({"date_from": date(2027, 11, 10)}, 1),
    ({"trip_type": "RT", "date_from": date(2027, 11, 10), "date_to": date(2027, 11, 20)}, 1),
    ({"month": date(2027, 11, 1)}, 3),
    ({"trip_type": "RT", "date_from": date(2027, 11, 10)}, 1),
])
def test_compact_output(params, count):
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи", **params)
    tickets = [dict(departure_at=f"2027-11-{10+i:02d}", value=10000+i*1000,
                    number_of_changes=0, baggage_code="1PC") for i in range(5)]
    text = search_results_text(search, tickets[::-1], "123")
    assert text.count("Открыть билет") == count
    assert "10 000 ₽" in text
    assert len(text) < 4096


@pytest.mark.parametrize("trip_type", ["OW", "RT"])
def test_fixed_date_cheapest_then_direct(trip_type):
    from biletbot.messages import select_tickets

    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    date_from=date(2027, 11, 10), trip_type=trip_type)
    cheapest = dict(departure_at="2027-11-10", value=5000, number_of_changes=1)
    direct = {**cheapest, "value": 8000, "number_of_changes": 0}
    expensive = {**direct, "value": 9000}
    assert select_tickets(search, [expensive, direct, cheapest]) == [cheapest, direct]
    assert select_tickets(search, [direct, expensive]) == [direct]
    assert select_tickets(search, [cheapest]) == [cheapest]
    assert select_tickets(search, []) == []


def test_convenient_route_within_five_percent_is_first():
    from biletbot.messages import select_tickets
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    month=date(2027, 11, 1))
    cheap = dict(departure_at="2027-11-10", value=10000, number_of_changes=2)
    convenient = {**cheap, "value": 10500, "number_of_changes": 1}
    expensive = {**cheap, "value": 10600, "number_of_changes": 0}
    assert select_tickets(search, [cheap, expensive, convenient]) == [convenient, cheap, expensive]
    assert select_tickets(search, [cheap, expensive])[0] == cheap
