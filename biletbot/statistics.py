from datetime import datetime, time, timedelta, timezone
from html import escape
import json

from .rich_messages import cell


def info_rows(storage, zone, now=None):
    now = (now or datetime.now(zone)).astimezone(zone)
    today = now.date()

    def utc(day):
        return datetime.combine(day, time.min, zone).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows = []
    searches = storage.db.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
    users = storage.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    subscriptions, active = storage.db.execute("SELECT COUNT(*), COALESCE(SUM(active=1),0) FROM alerts").fetchone()
    rows.append(("Всего", searches, users, subscriptions, active))
    for label, start, end in [
        ("Сегодня", today, today + timedelta(days=1)),
        ("Вчера", today - timedelta(days=1), today),
        ("7 дней", today - timedelta(days=6), today + timedelta(days=1)),
        ("30 дней", today - timedelta(days=29), today + timedelta(days=1)),
    ]:
        count, people = storage.db.execute("""SELECT COUNT(*), COUNT(DISTINCT user_id)
            FROM searches WHERE created_at>=? AND created_at<?""", (utc(start), utc(end))).fetchone()
        subscriptions, active = storage.db.execute("""SELECT COUNT(*), COALESCE(SUM(active=1),0)
            FROM alerts WHERE created_at>=? AND created_at<?""", (utc(start), utc(end))).fetchone()
        rows.append((label, count, people, subscriptions, active))
    return rows


async def send_info(api, chat_id, storage, zone):
    rows = info_rows(storage, zone)
    cells = [[cell(value, True) for value in ["Период", "Запросы", "Пользователи", "На человека", "Подписки всего", "Активные"]]]
    cells.extend([cell(label), cell(str(count)), cell(str(people)),
                  cell(f"{count / people if people else 0:.2f}"), cell(str(subscriptions)), cell(str(active))]
                 for label, count, people, subscriptions, active in rows)
    blocks = [
        {"type": "paragraph", "text": {"type": "bold", "text": "📊 Статистика поисков и подписок"}},
        {"type": "table", "cells": cells, "is_bordered": True, "is_striped": True, "is_compact": True},
        {"type": "footer", "text": f"Часовой пояс: {zone}. 7 и 30 дней включают сегодня. "
         "Всего пользователей — база; в периодах — выполнявшие поиск. "
         "Подписки в периодах — созданные за период; активные — из них действующие сейчас."},
    ]
    response = await api.telegram_http.post(
        f"https://api.telegram.org/bot{api.config.telegram_token}/sendRichMessage",
        data={"chat_id": str(chat_id), "rich_message": json.dumps({"blocks": blocks}, ensure_ascii=False)})
    payload = response.json()
    if not payload.get("ok"):
        raise ValueError("Не удалось отправить таблицу статистики")
    return payload["result"]


def info_text(storage, zone, now=None):
    rows = [row[:3] for row in info_rows(storage, zone, now)]
    table = [["Период", "Запросы", "Люди", "На чел."]]
    table.extend([label, str(count), str(people), f"{count / people if people else 0:.2f}"]
                 for label, count, people in rows)
    widths = [max(len(row[i]) for row in table) for i in range(4)]
    lines = ["  ".join(value.ljust(widths[i]) if i == 0 else value.rjust(widths[i])
                       for i, value in enumerate(row)) for row in table]
    subscriptions, subscribers = storage.db.execute(
        "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM alerts WHERE active=1").fetchone()
    average = subscriptions / subscribers if subscribers else 0
    return ("📊 <b>Статистика поисков</b>\n<pre>" + escape("\n".join(lines)) + "</pre>\n"
            f"<b>Активные подписки</b>\nПодписок: {subscriptions}\n"
            f"Пользователей подписок: {subscribers}\nПодписок на пользователя: {average:.2f}\n\n"
            f"<i>Часовой пояс: {escape(str(zone))}. 7 и 30 дней включают сегодня. "
            "В строке «Всего» — пользователи базы; в периодах — пользователи, выполнявшие поиск.</i>")
