import asyncio
import logging
import re
from contextlib import suppress

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from .api import API
from .config import Config
from .messages import price_keyboard
from .boarding_pass import boarding_pass
from .models import Search
from .monitor import Monitor
from .storage import Storage
from .rich_messages import send_search_results

HELP = """🎫 Помогу найти авиабилеты и отследить снижение цены.
Напишите откуда, куда и когда, например:
Москва Сочи завтра
Москва Питер в декабре прямой 7–9 дней
Москва Бангкок в начале ноября с багажом до 80000

Можно прислать голосовое сообщение до 20 секунд.

Под результатами нажмите «Отслеживать цену» и выберите порог.
/alerts — подписки
/history — последние запросы
/cancel — отменить ввод своей цены

Цены из кэша Travelpayouts: окончательную стоимость проверяйте по ссылке."""


def main():
    config = Config.load()
    storage = Storage(config.database)
    api = API(config)
    monitor = None
    worker = None

    async def startup(app):
        nonlocal monitor, worker
        monitor = Monitor(storage, api, app.bot, config)
        worker = asyncio.create_task(monitor.run())

    async def shutdown(app):
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
            storage.get_search(sid, uid, cid)
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
                await msg.reply_text(HELP)
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
                searches = storage.db.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM searches").fetchone()
                await msg.reply_text(f"Запросов: {searches[0]}\nПользователей: {searches[1]}\nАктивных подписок: {len(storage.alerts())}")
            elif text.startswith("/"):
                await msg.reply_text(HELP)
            elif storage.pending(uid, cid) is not None:
                normalized = re.sub(r"[\s\u00a0]", "", text.lower())
                match = re.fullmatch(r"([0-9]+)(?:₽|руб|рублей)?", normalized)
                if not match:
                    raise ValueError("Введите целую цену, например 25000, или /cancel")
                storage.subscribe(storage.pending(uid, cid), uid, cid, int(match[1]))
                await msg.reply_text("Отслеживание создано! Сообщу, когда цена станет ниже указанной.")
            elif storage.pending_edit(uid, cid) is None and re.match(r"^(что посмотреть|куда сходить|чем заняться|что поесть|составь маршрут|что попробовать|посоветуй отель)", text.lower()):
                answer = await api.llm("Ты дружелюбный тревел-гид. Отвечай только на туристические вопросы, до 1000 символов, без Markdown. В конце предложи помощь с билетами.", text)
                await msg.reply_text(answer[:3500])
            else:
                await msg.reply_text("Ищу билеты…")
                edit_sid = storage.pending_edit(uid, cid)
                if edit_sid is not None:
                    base = storage.get_search(edit_sid, uid, cid)
                    search = await api.edit_search(base, text)
                else:
                    search = await api.parse(text)
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
    app.add_handler(MessageHandler(filters.TEXT | filters.VOICE, message))
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    main()
