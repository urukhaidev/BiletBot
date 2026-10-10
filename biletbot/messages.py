from html import escape
from datetime import datetime
import re
from urllib.parse import urlencode

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
LABELS = {"OW_DATE": "В одну сторону · точная дата", "OW_MONTH": "В одну сторону · месяц",
          "OW_RANGE": "В одну сторону · диапазон вылета", "RT_DATES": "Туда-обратно · точные даты",
          "RT_DATE_DUR": "Туда-обратно · точный вылет, гибкий возврат",
          "RT_MONTH": "Туда-обратно · месяц", "RT_RANGE": "Туда-обратно · диапазон вылета"}


def human_date(value):
    dt = datetime.fromisoformat(value[:10])
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def baggage_text(code):
    if not code:
        return "Багаж не указан"
    match = re.fullmatch(r"(\d+)PC(\d+)?", code)
    if not match:
        return f"Багаж: {code}"
    count, weight = int(match[1]), match[2]
    if count == 0:
        return "Без багажа (ручная кладь)"
    if weight:
        return f"Багаж {weight} кг" if count == 1 else f"Багаж: {count} места по {weight} кг"
    return "Багаж включён, 1 место" if count == 1 else f"Багаж включён: {count} места"


def hours_minutes(minutes):
    hours = int(float(minutes) / 60 + .5)
    return f"{hours} ч" if hours else "<1 ч"


def duration_text(ticket):
    segments = ticket.get("segments") or []
    durations = []
    for segment in segments:
        if segment.get("departure_at") and segment.get("arrival_at"):
            seconds = (datetime.fromisoformat(segment["arrival_at"]) -
                       datetime.fromisoformat(segment["departure_at"])).total_seconds()
            if seconds > 0:
                durations.append(hours_minutes(seconds / 60))
    if durations:
        return "туда " + durations[0] + ", обратно " + durations[1] if len(durations) == 2 else " / ".join(durations)
    return hours_minutes(ticket["duration"]) if ticket.get("duration") else "не указана"


def transfer_text(ticket):
    changes = int(ticket["number_of_changes"])
    if changes == 0:
        return "Прямой рейс"
    routes = []
    for i, segment in enumerate(ticket.get("segments") or []):
        places = []
        for tr in segment.get("transfers") or []:
            place = tr.get("at_name") or tr.get("at") or "место не указано"
            place = re.sub(r"\s*\([A-Z]{3}\)", "", place)
            if tr.get("to") and tr.get("to") != tr.get("at"):
                place += " → " + re.sub(r"\s*\([A-Z]{3}\)", "", tr.get("to_name") or tr["to"])
            if tr.get("duration_seconds"):
                place += f" ({hours_minutes(tr['duration_seconds'] / 60)})"
            places.append(place)
        if places:
            prefix = ("Туда: " if i == 0 else "Обратно: ") if len(ticket.get("segments", [])) > 1 else ""
            routes.append(prefix + ", ".join(places))
    label = {1: "Одна пересадка", 2: "Две пересадки", 3: "Три пересадки"}.get(changes, f"Пересадок: {changes}")
    return label + ": " + "; ".join(routes) if routes else label + "; место не указано API"


def price_text(ticket):
    return f"{int(float(ticket['value']) + .5):,}".replace(",", " ") + " ₽"


def select_tickets(search, tickets):
    ordered = sorted(tickets, key=lambda t: float(t["value"]))
    if search.anywhere:
        selected, seen = [], set()
        for ticket in ordered:
            code = ticket["destination_city_iata"]
            if code not in seen:
                selected.append(ticket)
                seen.add(code)
        return selected
    if not ordered:
        return []
    # Prefer fewer transfers within a 5% premium; preserve price order outside it.
    ceiling = float(ordered[0]["value"]) * 1.05
    convenient = sorted((t for t in ordered if float(t["value"]) <= ceiling),
                        key=lambda t: (int(t["number_of_changes"]), float(t["value"])))
    ranked = convenient + [t for t in ordered if float(t["value"]) > ceiling]
    if search.date_from:
        if not ordered:
            return []
        cheapest = ordered[0]
        selected = [cheapest]
        if int(ranked[0]["number_of_changes"]) < int(cheapest["number_of_changes"]):
            selected.append(ranked[0])
        if int(cheapest["number_of_changes"]) != 0:
            direct = next((t for t in ordered if int(t["number_of_changes"]) == 0), None)
            if direct and direct not in selected:
                selected.append(direct)
        return sorted(selected, key=lambda t: ranked.index(t))
    limit = 3
    selected, seen = [], set()
    for ticket in ranked:
        key = (ticket.get("origin_city_iata"), ticket.get("destination_city_iata"),
               ticket["departure_at"][:10], (ticket.get("return_at") or "")[:10], ticket["number_of_changes"])
        if key in seen:
            continue
        seen.add(key)
        selected.append(ticket)
        if len(selected) == limit:
            break
    # Keep the usual recommendations and include up to three distinct direct fares.
    direct_count = sum(int(t["number_of_changes"]) == 0 for t in selected)
    for ticket in ordered:
        if direct_count >= 3:
            break
        if int(ticket["number_of_changes"]) != 0:
            continue
        key = (ticket.get("origin_city_iata"), ticket.get("destination_city_iata"),
               ticket["departure_at"][:10], (ticket.get("return_at") or "")[:10], ticket["number_of_changes"])
        if key not in seen:
            seen.add(key)
            selected.append(ticket)
            direct_count += 1
    return selected


def airline_text(ticket):
    name = ticket.get("airline_name") or ticket.get("main_airline") or ticket.get("airline")
    return f"Авиакомпания: {name}" if name else "Авиакомпания не указана"


def ticket_text(search, ticket, marker):
    departing = ticket["departure_at"][:10]
    returning = (ticket.get("return_at") or "")[:10]
    dates = human_date(departing) + (f" — {human_date(returning)}" if returning else "")
    # Dates come from the API, including the year, rather than from ticket_link.
    ddmm = departing[8:10] + departing[5:7]
    tail = returning[8:10] + returning[5:7] + "1" if returning else "1"
    origin = ticket.get("origin_city_iata", search.origin)
    destination = ticket.get("destination_city_iata", search.destination)
    link = f"https://www.aviasales.ru/search/{origin}{ddmm}{destination}{tail}?" + urlencode({"marker": marker})
    return (f"🎫 <b>{escape(ticket.get('origin_name', search.origin_name))} — {escape(ticket.get('destination_name', search.destination_name))}</b>\n"
            f"{dates}\n<b>{price_text(ticket)}</b>\n"
            f"{escape(airline_text(ticket))}\n{escape(baggage_text(ticket.get('baggage_code')))}\n"
            f"В пути: {escape(duration_text(ticket))}\n{escape(transfer_text(ticket))}\n"
            f"<a href=\"{escape(link, quote=True)}\">Открыть билет</a>")


def search_results_text(search, tickets, marker):
    selected = select_tickets(search, tickets)
    roundtrip = search.trip_type == "RT"
    rows = ["№  Вылет / возврат              Цена" if roundtrip else "№  Вылет             Цена", "─" * 32]
    for i, ticket in enumerate(selected, 1):
        dates = human_date(ticket['departure_at'])
        if roundtrip and ticket.get("return_at"):
            dates += " / " + human_date(ticket["return_at"])
        rows.append(f"{i}  {dates:<18} {price_text(ticket)}")
    table = "<pre>" + escape("\n".join(rows)) + "</pre>"
    details = "\n\n".join(f"<b>Вариант {i}</b>\n" + ticket_text(search, t, marker)
                            for i, t in enumerate(selected, 1))
    return table + "\n\n" + details + f"\n\n<i>{LABELS[search.mode]}</i>"


def price_keyboard(sid, price):
    rows = [[InlineKeyboardButton(f"Ниже {max(1, round(price * ratio))} ₽",
                                 callback_data=f"price:{sid}:{max(1, round(price * ratio))}")]
            for ratio in (1, .95, .9, .8)]
    rows.append([InlineKeyboardButton("✍️ Своя цена", callback_data=f"custom:{sid}")])
    return InlineKeyboardMarkup(rows)
