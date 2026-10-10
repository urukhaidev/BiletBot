import asyncio
import json
from urllib.parse import urlencode

from .boarding_pass import boarding_pass
from .messages import (LABELS, baggage_text, duration_text, human_date, price_text,
                       select_tickets, transfer_text)


def cell(text, header=False):
    result = {"text": text, "align": "left", "valign": "middle"}
    if header:
        result["is_header"] = True
    return result


def ticket_url(search, ticket, marker):
    departure = ticket["departure_at"][:10]
    returning = (ticket.get("return_at") or "")[:10]
    tail = returning[8:10] + returning[5:7] + "1" if returning else "1"
    origin = ticket.get("origin_city_iata", search.origin)
    destination = ticket.get("destination_city_iata", search.destination)
    return f"https://www.aviasales.ru/search/{origin}{departure[8:10]}{departure[5:7]}{destination}{tail}?" + urlencode({"marker": marker})


def rich_blocks(search, tickets, marker, title=None):

    blocks = [{"type": "paragraph", "text": {"type": "bold", "text":
               title or ("В одну сторону" if search.trip_type == "OW" else "Туда-обратно")}}]
    if not tickets:
        blocks.append({"type": "paragraph", "text": "Билеты не найдены. Можно создать отслеживание со своей ценой."})
        return blocks
    headers = ["Билет", "Цена"]
    rows = [[cell(h, True) for h in headers]]
    for i, ticket in enumerate(tickets, 1):
        dates = human_date(ticket["departure_at"]).rsplit(" ", 1)[0]
        if search.trip_type == "RT":
            dates += " — " + human_date(ticket["return_at"]).rsplit(" ", 1)[0]
        duration = duration_text(ticket).replace("туда ", "").replace(", обратно ", " / ")
        info = (dates + "\n" + transfer_text(ticket) + "\nВ пути " + duration
                + "\n" + baggage_text(ticket.get("baggage_code")))
        if ticket.get("destination_name") or ticket.get("origin_name"):
            info = (ticket.get("origin_name", search.origin_name) + " — "
                    + ticket.get("destination_name", search.destination_name) + "\n" + info)
        price_link = {"type": "url", "url": ticket_url(search, ticket, marker), "text": "👉 " + price_text(ticket)}
        values = [info, price_link]
        rows.append([cell(v) for v in values])
    blocks.append({"type": "table", "cells": rows, "is_bordered": True, "is_striped": True, "is_compact": True})
    return blocks


async def send_search_result(api, chat_id, search, flights, sid):
    return await send_search_results(api, chat_id, [(search, flights, sid)])


async def send_search_results(api, chat_id, results):
    first_search = results[0][0]
    blocks = []
    files = {}
    for search, flights, sid in results:
        tickets = select_tickets(search, flights)
        if tickets:
            ticket = tickets[0]
            card_search = search.model_copy(update={
                "origin": ticket.get("origin_city_iata", search.origin),
                "destination": ticket.get("destination_city_iata", search.destination),
                "origin_name": ticket.get("origin_name", search.origin_name),
                "destination_name": ticket.get("destination_name", search.destination_name)})
            image = await asyncio.to_thread(boarding_pass, card_search, ticket)
            files = {"ticket1": ("ticket1.png", image.getvalue(), "image/png")}
            blocks.append({"type": "photo", "photo": {"type": "photo", "media": "attach://ticket1"}})
            break
    blocks.append({"type": "paragraph", "text": {"type": "bold", "text":
                   f"🎫 {first_search.origin_name} — {first_search.destination_name}"}})
    buttons = []
    for search, flights, sid in results:
        tickets = select_tickets(search, flights)
        connecting = [t for t in tickets if int(t["number_of_changes"]) != 0]
        direct = [t for t in tickets if int(t["number_of_changes"]) == 0]
        trip = "В одну сторону" if search.trip_type == "OW" else "Туда-обратно"
        if connecting or not tickets:
            blocks.extend(rich_blocks(search, connecting, api.config.marker))
        if direct:
            blocks.extend(rich_blocks(search, direct, api.config.marker, title=f"{trip} · Прямые рейсы"))
        label = "в одну сторону" if search.trip_type == "OW" else "туда-обратно"
        callback = f"track:{sid}:{round(min(float(t['value']) for t in flights))}" if tickets else f"custom:{sid}"
        buttons.append([{"text": f"📉 Отслеживать {label}", "callback_data": callback}])
    blocks.append({"type": "footer", "text": " · ".join(LABELS[search.mode] for search, _, _ in results)})
    buttons.append([{"text": "Дополнить / изменить запрос", "callback_data": f"edit:{results[0][2]}"}])
    if first_search.query:
        blocks.append({"type": "paragraph", "text": {"type": "code", "text": first_search.query}})
    keyboard = {"inline_keyboard": buttons}
    response = await getattr(api, "telegram_http", api.http).post(f"https://api.telegram.org/bot{api.config.telegram_token}/sendRichMessage",
        data={"chat_id": str(chat_id), "rich_message": json.dumps({"blocks": blocks}, ensure_ascii=False),
              "reply_markup": json.dumps(keyboard, ensure_ascii=False)}, files=files)
    # Avoid HTTPStatusError URLs containing the bot token.
    payload = response.json()
    if not payload.get("ok"):
        description = payload.get("description", "Ошибка отправки Rich Message")
        raise ValueError("Telegram: " + description.replace(api.config.telegram_token, "[REDACTED]"))
    return payload["result"]
