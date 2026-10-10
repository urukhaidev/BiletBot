from datetime import date

from PIL import Image

from biletbot.boarding_pass import boarding_pass
from biletbot.messages import baggage_text, duration_text, human_date, search_results_text, transfer_text
from biletbot.models import Search


def fare():
    return dict(departure_at="2027-11-10T08:00:00+03:00", value=15000, number_of_changes=1,
                baggage_code="2PC23", duration=300, segments=[{
                    "departure_at": "2027-11-10T08:00:00+03:00",
                    "arrival_at": "2027-11-10T13:30:00+04:00",
                    "transfers": [{"at": "KZN", "at_name": "Казань (KZN)", "to": "KZN", "duration_seconds": 5400}]}])


def test_human_ticket_details():
    assert human_date("2027-11-10") == "10 ноября 2027"
    assert baggage_text("1PC20") == "Багаж 20 кг"
    assert "2 места по 23 кг" in baggage_text("2PC23")
    assert "Без багажа" in baggage_text("0PC")
    assert duration_text(fare()) == "5 ч"
    assert transfer_text(fare()) == "Одна пересадка: Казань (2 ч)"
    search = Search(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи",
                    date_from=date(2027, 11, 10))
    text = search_results_text(search, [fare()], "123")
    assert "<pre>" in text
    assert text.endswith("<i>В одну сторону · точная дата</i>")
    assert "Казань" in text
    image = Image.open(boarding_pass(search, fare()))
    assert image.size == (1400, 760)
    assert image.getpixel((0, 0)) == (20, 84, 163)


def test_implicit_trip_type_variants():
    base = dict(origin="MOW", destination="AER", origin_name="Москва", destination_name="Сочи")
    flexible = Search(**base, month=date(2027, 11, 1), trip_type_explicit=False)
    assert [s.mode for s in flexible.variants()] == ["OW_MONTH", "RT_MONTH"]
    fixed = Search(**base, date_from=date(2027, 11, 10), trip_type_explicit=False)
    assert [s.mode for s in fixed.variants()] == ["OW_DATE", "RT_DATE_DUR"]
    explicit = Search(**base, month=date(2027, 11, 1), trip_type="RT")
    assert [s.mode for s in explicit.variants()] == ["RT_MONTH"]


def test_month_with_seven_day_duration_shows_three_roundtrips():
    from biletbot.messages import select_tickets
    search = Search(origin="AER", destination="MLE", origin_name="Сочи", destination_name="Мальдивы",
                    trip_type="RT", month=date(2027, 11, 1), duration_min=7, duration_max=7)
    tickets = [{**fare(), "departure_at": f"2027-11-{10+i}", "return_at": f"2027-11-{17+i}"}
               for i in range(5)]
    assert len(select_tickets(search, tickets)) == 3


def test_two_transfers_compact_hours_without_iata():
    ticket = fare()
    ticket["number_of_changes"] = 2
    ticket["segments"][0]["transfers"] = [
        {"at": "BKK", "at_name": "Бангкок (BKK)", "duration_seconds": (20 * 60 + 25) * 60},
        {"at": "SVX", "at_name": "Екатеринбург (SVX)", "duration_seconds": 3 * 3600},
    ]
    assert transfer_text(ticket) == "Две пересадки: Бангкок (20 ч), Екатеринбург (3 ч)"
    ticket.pop("segments")
    ticket["duration"] = 37 * 60 + 5
    assert duration_text(ticket) == "37 ч"


def test_flexible_search_adds_three_unique_direct_fares():
    from biletbot.messages import select_tickets
    search = Search(origin="MOW", destination="MLE", origin_name="Москва", destination_name="Мале",
                    month=date(2027, 11, 1))
    connecting = [{**fare(), "departure_at": f"2027-11-{10+i}", "value": 10000+i} for i in range(4)]
    direct = [{**fare(), "departure_at": f"2027-11-{15+i}", "value": 20000+i,
               "number_of_changes": 0} for i in range(4)]
    selected = select_tickets(search, connecting + direct + [direct[0]])
    assert selected == connecting[:3] + direct[:3]
    assert select_tickets(search, direct) == direct[:3]


def test_seven_nights_with_long_flight_uses_api_duration():
    search = Search(origin="AER", destination="MLE", origin_name="Сочи", destination_name="Мале",
                    trip_type="RT", month=date(2026, 10, 1), duration_min=7, duration_max=7)
    ticket = dict(origin_city_iata="AER", destination_city_iata="MLE", departure_at="2026-10-15",
                  return_at="2026-10-23", trip_duration=7, value=70000, number_of_changes=2)
    assert search.matches(ticket, date(2026, 10, 9))
    ticket["trip_duration"] = 8
    assert not search.matches(ticket, date(2026, 10, 9))


def test_maximum_one_transfer_is_enforced_for_roundtrip():
    search = Search(origin="AER", destination="MLE", origin_name="Сочи", destination_name="Мале",
                    trip_type="RT", month=date(2026, 10, 1), duration_min=7, duration_max=7, max_changes=1)
    ticket = dict(origin_city_iata="AER", destination_city_iata="MLE", departure_at="2026-10-15",
                  return_at="2026-10-23", trip_duration=7, value=70000, number_of_changes=2)
    assert not search.matches(ticket, date(2026, 10, 9))
    ticket["number_of_changes"] = 1
    assert search.matches(ticket, date(2026, 10, 9))
    ticket["number_of_changes"] = 0
    assert search.matches(ticket, date(2026, 10, 9))
