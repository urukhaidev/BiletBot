import asyncio
import logging
from datetime import timedelta

from telegram.error import BadRequest, Forbidden, RetryAfter, TelegramError


class Broadcast:
    def __init__(self, storage, admin_id):
        self.storage = storage
        self.admin_id = admin_id
        self.waiting = False
        self.task = None

    async def handle(self, update, context):
        message = update.effective_message
        text = message.text or ""
        command = text.split()[0].split("@")[0] if text.startswith("/") else ""
        if update.effective_user.id != self.admin_id or update.effective_chat.id != self.admin_id:
            if command == "/admin":
                await message.reply_text("Команда доступна только администратору в личном чате.")
                return True
            return False
        if command == "/admin":
            if self.task and not self.task.done():
                await message.reply_text("Рассылка уже выполняется. Дождитесь итогового сообщения.")
                return True
            total = self.storage.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            self.waiting = True
            await message.reply_text(f"Людей в базе: {total}\nДоступны для рассылки: {len(self.storage.broadcast_users())}\n\nПришлите сообщение для рассылки: текст или фото с подписью. После отправки начнётся рассылка. Отмена: /cancel")
            return True
        if command == "/cancel" and self.waiting:
            self.waiting = False
            await message.reply_text("Рассылка отменена.")
            return True
        if not self.waiting:
            return False
        if command:
            await message.reply_text("Пришлите текст или фото с подписью. Отмена: /cancel")
            return True
        if not message.text and not message.photo:
            await message.reply_text("Для рассылки нужен текст или фото с подписью.")
            return True
        if message.media_group_id:
            await message.reply_text("Пришлите одно фото с подписью, без альбома.")
            return True
        self.waiting = False
        recipients = self.storage.broadcast_users()
        await message.reply_text(f"Рассылка началась. Получателей: {len(recipients)}.")
        self.task = asyncio.create_task(self.send(context.bot, message.chat_id, message.message_id, recipients))
        return True

    async def send(self, bot, chat_id, message_id, recipients):
        sent = failed = blocked = 0
        try:
            for uid in recipients:
                for attempt in range(4):
                    try:
                        await bot.copy_message(chat_id=uid, from_chat_id=chat_id, message_id=message_id)
                        sent += 1
                        break
                    except RetryAfter as exc:
                        if attempt == 3:
                            failed += 1
                            break
                        delay = exc.retry_after.total_seconds() if isinstance(exc.retry_after, timedelta) else exc.retry_after
                        await asyncio.sleep(delay + 1)
                    except Forbidden:
                        self.storage.deactivate_user(uid)
                        blocked += 1
                        break
                    except BadRequest as exc:
                        if "chat not found" in str(exc).lower():
                            self.storage.deactivate_user(uid)
                        failed += 1
                        break
                    except TelegramError:
                        if attempt == 3:
                            failed += 1
                            break
                        await asyncio.sleep(2 ** attempt)
                await asyncio.sleep(.06)
            await bot.send_message(chat_id, f"Рассылка завершена.\nДоставлено: {sent}\nБот заблокирован: {blocked}\nОшибок: {failed}")
        except TelegramError:
            logging.warning("Broadcast report delivery failed")
