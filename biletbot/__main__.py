import asyncio
import logging
import re
from pathlib import Path
from contextlib import suppress

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove, MenuButtonWebApp, WebAppInfo
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from .api import API
from .config import Config
from .messages import price_keyboard
from .boarding_pass import boarding_pass
from .models import Search
from .monitor import Monitor
from .storage import Storage
from .rich_messages import send_search_results
from .broadcast import Broadcast
from .statistics import send_info
from .guide import is_guide_query, send_guide

HELP = """🎫 Привет! Найду авиабилеты и помогу спланировать поездку.

✈️ Напишите откуда, куда и когда лететь:
• <code>Москва — Анталья в одну сторону в октябре</code>
• <code>Москва — Питер на 7–10 дней в ноябре</code>
• <code>Казань — Стамбул с багажом, только прямые</code>
• <code>Москва, горящие в октябре</code> — поиск куда угодно

Добавляйте даты, длительность, багаж, бюджет и число пересадок. Если месяц не указан, ищу в текущем. Можно прислать голосовое до 20 секунд.

В результатах — цены, авиакомпании и пересадки. Проверю также прямые рейсы, если они доступны.

🔔 Для конкретного направления нажмите «Отслеживать цены» и задайте порог. Для «Куда угодно» отслеживание недоступно.

🧭 Туристический гид — начните сообщение так:
• <code>Куда сходить в Стамбуле?</code>
• <code>Что посмотреть в Анталье?</code>
• <code>Чем заняться в Сочи?</code>
• <code>Что попробовать в Грузии?</code>
• <code>Посоветуй отель в Дубае</code>
• <code>Составь маршрут по Петербургу на 3 дня</code>

📱 Поиск через форму или AI в мини-аппе:
https://t.me/bilet_bot?startapp

/alerts — ваши подписки
/history — история поисков
/cancel — отменить ввод цены или изменение запроса
/help — эта инструкция

⏱ Между запросами — 10 секунд, общий лимит для бота и мини-аппа.
Итоговую стоимость проверяйте по ссылке на билет."""


def main():
    config = Config.load()
    storage = Storage(config.database)
    legacy = Path("list_id.txt")
    if legacy.is_file():
        storage.import_users(legacy.read_text(encoding="utf-8-sig").splitlines())
    api = API(config)
    broadcast = Broadcast(storage, config.admin_id)
    monitor = None
    worker = None

    async def startup(app):
        nonlocal monitor, worker
        await app.bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
            text="Найти", web_app=WebAppInfo(url="https://biletbot.ru/mini-app")))
        monitor = Monitor(storage, api, app.bot, config)
        worker = asyncio.create_task(monitor.run())

    async def shutdown(app):
        if broadcast.task and not broadcast.task.done():
            broadcast.task.cancel()
            with suppress(asyncio.CancelledError):
                await broadcast.task
        if worker:
            worker.cancel()
            with suppress(asyncio.CancelledError):
                await worker
        await api.http.aclose()
        if api.telegram_http is not api.http:
            await api.telegram_http.aclose()
        storage.db.close()

    builder = Application.builder().token(config.telegram_token).post_init(startup).post_shutdown(shutdown)
    if config.telegram_proxy:
        builder = builder.proxy(config.telegram_proxy).get_updates_proxy(config.telegram_proxy)
    app = builder.build()

    async def callback(update, context):
        query = update.callback_query
        await query.answer()
        uid, cid = query.from_user.id, query.message.chat_id
        wait = storage.request_wait(uid)
        if wait:
            await query.message.reply_text(f"Подождите {wait} сек. Между запросами — 10 секунд.")
            return
        try:
            parts = query.data.split(":")
            action, sid = parts[0], int(parts[1])
            if action == "cancel_edit":
                storage.get_search(sid, uid, cid)
                if storage.pending_edit(uid, cid) == sid:
                    storage.clear_edit(uid, cid)
                    await query.message.edit_text("Изменение запроса отменено.")
                else:
                    await query.message.reply_text("Этот ввод уже завершён.")
                return
            if action == "card":
                search, ticket = storage.get_card(sid, uid, cid)
                image = await asyncio.to_thread(boarding_pass, search, ticket)
                await query.message.reply_photo(image)
                return
            if action == "stop":
                stopped = storage.stop(sid, uid)
                await query.message.reply_text("Отслеживание остановлено." if stopped else "Подписка не найдена.")
                return
            search = storage.get_search(sid, uid, cid)
            if action in ("track", "custom", "price") and search.anywhere:
                raise ValueError("Отслеживание недоступно для поиска «Куда угодно». Выберите конкретное направление.")
            if action == "edit":
                base = storage.get_search(sid, uid, cid)
                storage.set_edit(sid, uid, cid)
                await query.message.reply_text(
                    f"Исходный запрос: {base.query}\n\nНапишите, что изменить или добавить: «в декабре», «с багажом», «можно с пересадками». Можно прислать полный новый запрос. Отмена: /cancel",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Отмена", callback_data=f"cancel_edit:{sid}")]]))
            elif action == "track":
                await query.message.reply_text("Укажите цену, ниже которой прислать уведомление:",
                    reply_markup=price_keyboard(sid, float(parts[2])))
            elif action == "custom":
                storage.set_pending(sid, uid, cid)
                await query.message.reply_text("Введите целую цену в рублях, например 25 000. Отмена: /cancel")
            elif action == "price":
                storage.subscribe(sid, uid, cid, int(parts[2]))
                await query.message.reply_text(f"Отслеживание создано: дешевле {parts[2]} ₽. Проверка каждые {config.interval} секунд.")
        except (ValueError, IndexError) as exc:
            await query.message.reply_text(str(exc) if isinstance(exc, ValueError) else "Некорректная кнопка.")

    async def message(update, context):
        msg = update.effective_message
        uid, cid = update.effective_user.id, update.effective_chat.id
        command = (msg.text or "").split()[0].split("@")[0] if msg.text else ""
        if await broadcast.handle(update, context):
            return
        remove_keyboard = context.user_data.get("start_keyboard", False) and command not in ("/start", "/help")
        if remove_keyboard:
            context.user_data.pop("start_keyboard", None)
        wait = storage.request_wait(uid)
        if wait:
            await msg.reply_text(f"Подождите {wait} сек. Между запросами — 10 секунд.", reply_markup=ReplyKeyboardRemove() if remove_keyboard else None)
            return
        if remove_keyboard:
            await msg.reply_text("Принято.", reply_markup=ReplyKeyboardRemove())
        if msg.photo:
            return
        try:
            if msg.voice:
                if msg.voice.duration > 20:
                    await msg.reply_text("Голосовое должно быть не длиннее 20 секунд. Запишите покороче или пришлите текст.")
                    return
                if not config.openrouter_key:
                    raise ValueError("Голосовой ввод пока не настроен. Пришлите запрос текстом.")
                await msg.reply_text("Распознаю голосовое…")
                audio_file = await context.bot.get_file(msg.voice.file_id)
                text = await api.transcribe(await audio_file.download_as_bytearray())
                await msg.reply_text("Распознано: " + text)
            else:
                text = msg.text.strip()
            if not text:
                return
            command = text.split()[0].split("@")[0]
            if command in ("/start", "/help"):
                await msg.reply_text(HELP, parse_mode="HTML", reply_markup=ReplyKeyboardMarkup(
                    [["Москва — Анталья в одну сторону"], ["Москва — Питер на 7–10 дней"],
                     ["Что посмотреть в Стамбуле?"]], resize_keyboard=True, one_time_keyboard=True))
                context.user_data["start_keyboard"] = True
            elif command == "/cancel":
                with storage.db:
                    storage.clear_pending(uid, cid)
                    storage.clear_edit(uid, cid)
                await msg.reply_text("Ввод отменён.")
            elif command == "/alerts":
                alerts = storage.alerts(uid)
                if not alerts:
                    await msg.reply_text("У вас нет активных подписок. Начните поиск: /start")
                for alert in alerts:
                    search = Search.model_validate_json(alert["params"])
                    await msg.reply_text(
                        f"🔔 {search.origin_name} — {search.destination_name} ({search.trip_type})\n"
                        f"Дешевле {alert['threshold']} ₽\nЗапрос: {search.query}\n"
                        f"Последняя проверка (UTC): {alert['checked_at'] or 'ещё не выполнена'}"
                        + (f"\nОшибка проверки: {alert['last_error']}" if alert['last_error'] else ""),
                        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Удалить", callback_data=f"stop:{alert['id']}")]]))
            elif command.startswith("/delete_alert_id_"):
                aid = int(command.removeprefix("/delete_alert_id_"))
                await msg.reply_text("Отслеживание удалено." if storage.stop(aid, uid) else "Подписка не найдена.")
            elif command == "/history":
                history = storage.history(uid)
                await msg.reply_text("📋 Последние запросы:\n" + "\n".join(
                    Search.model_validate_json(row["params"]).query for row in history) if history else "История пуста.")
            elif command == "/info" and uid == config.admin_id:
                await send_info(api, cid, storage, config.timezone)
            elif text.startswith("/"):
                await msg.reply_text(HELP)
            elif storage.pending(uid, cid) is not None:
                normalized = re.sub(r"[\s\u00a0]", "", text.lower())
                match = re.fullmatch(r"([0-9]+)(?:₽|руб|рублей)?", normalized)
                if not match:
                    raise ValueError("Введите целую цену, например 25000, или /cancel")
                storage.subscribe(storage.pending(uid, cid), uid, cid, int(match[1]))
                await msg.reply_text("Отслеживание создано! Сообщу, когда цена станет ниже указанной.")
            elif storage.pending_edit(uid, cid) is None and is_guide_query(text):
                await send_guide(api, cid, text)
            else:
                await msg.reply_text("Ищу билеты…")
                edit_sid = storage.pending_edit(uid, cid)
                try:
                    if edit_sid is not None:
                        base = storage.get_search(edit_sid, uid, cid)
                        search = await api.edit_search(base, text)
                    else:
                        search = await api.parse(text)
                except Exception as exc:
                    error = str(exc).replace(config.telegram_token, "[REDACTED]") if isinstance(exc, ValueError) else type(exc).__name__
                    storage.save_failed_query(uid, "bot-edit" if edit_sid is not None else "bot", text, error)
                    raise
                results = []
                for variant in search.variants():
                    sid = storage.save_search(uid, cid, variant)
                    flights = await api.search_flights(variant, all_pages=False)
                    results.append((variant, flights, sid))
                await send_search_results(api, cid, results)
                if edit_sid is not None:
                    storage.clear_edit(uid, cid)
        except ValueError as exc:
            await msg.reply_text(str(exc)[:3500])
        except Exception as exc:
            logging.getLogger(__name__).warning("Request failed (%s)", type(exc).__name__)
            await msg.reply_text("Не удалось получить ответ сервиса. Попробуйте позже. Подписки сохранены.")

    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE | filters.PHOTO, message))
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    main()
