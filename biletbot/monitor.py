import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden

from .messages import ticket_text
from .models import Search

logger = logging.getLogger(__name__)


class Monitor:
    def __init__(self, storage, api, bot, config):
        self.storage, self.api, self.bot, self.config = storage, api, bot, config
        self.lock = asyncio.Lock()

    async def check_once(self):
        async with self.lock:
            cache = {}
            for alert in self.storage.alerts():
                aid = alert["id"]
                try:
                    search = Search.model_validate_json(alert["params"])
                    if search.last_departure() < self.api.today():
                        self.storage.stop(aid, alert["user_id"])
                        continue
                    key = search.model_dump_json()
                    if key not in cache:
                        cache[key] = await self.api.search_flights(search) if hasattr(self.api, "search_flights") else await self.api.flights(search)
                    tickets = cache[key]
                    price = float(tickets[0]["value"]) if tickets else None
                    self.storage.record_check(aid, price)
                    # Re-read after network I/O: a user may have stopped/changed the alert.
                    current = next((a for a in self.storage.alerts(alert["user_id"]) if a["id"] == aid), None)
                    if current is None or price is None or price >= current["threshold"]:
                        continue
                    if current["last_notified"] is not None and price >= current["last_notified"]:
                        continue
                    await self.bot.send_message(chat_id=current["chat_id"],
                        text=f"📉 Цена ниже {current['threshold']} ₽!\n\n" + ticket_text(search, tickets[0], self.config.marker),
                        parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("Остановить отслеживание", callback_data=f"stop:{aid}")]]))
                    # Mark only after successful delivery; failed sends are retried next cycle.
                    self.storage.record_notification(aid, price)
                except Forbidden:
                    self.storage.stop(aid, alert["user_id"])
                except Exception as exc:
                    self.storage.record_error(aid, type(exc).__name__)
                    logger.warning("Price check failed for alert %s (%s)", aid, type(exc).__name__)

    async def run(self):
        while True:
            try:
                await self.check_once()
            except Exception as exc:
                logger.warning("Monitor cycle failed (%s)", type(exc).__name__)
            await asyncio.sleep(self.config.interval)
