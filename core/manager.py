import asyncio
import logging
import random
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiohttp
from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from storage.db import Database
from storage.models import User
from vk.client import VKClient
from vk.longpoll import LongPollWorker
from vk.notifications import NotificationsPoller
from vk.rate_limit import FloodPolicy, VKFloodController
from vk.vkid_client import ActivityItem
from vk.vkid_watcher import VKIDWatcher

logger = logging.getLogger(__name__)


@dataclass
class WorkerHandle:
    longpoll_task: asyncio.Task
    notifications_task: asyncio.Task
    session: aiohttp.ClientSession
    client: VKClient


class WorkerManager:
    def __init__(
        self,
        bot: Bot,
        db: Database,
        notifications_interval: int,
        vkid_owner_tg_id: Optional[int] = None,
        vkid_poll_interval: int = 60,
        flood_policy: Optional[FloodPolicy] = None,
    ) -> None:
        self._bot = bot
        self._db = db
        self._notifications_interval = notifications_interval
        self._workers: dict[int, WorkerHandle] = {}
        self._last_ts_cache: dict[int, int] = {}
        self._lock = asyncio.Lock()
        self._vkid_owner_tg_id = vkid_owner_tg_id
        self._vkid_poll_interval = vkid_poll_interval
        self._vkid_task: Optional[asyncio.Task] = None
        self._limiter = VKFloodController(policy=flood_policy or FloodPolicy())

    async def start_all(self) -> None:
        users = await self._db.list_active_users()
        for i, user in enumerate(users):
            await self.start_user(user)
            if i + 1 < len(users):
                await asyncio.sleep(3)
        logger.info("Started workers for %d users", len(users))
        await self._maybe_notify_kate_reauth(users)
        await self.start_vkid_watcher()

    async def start_vkid_watcher(self) -> None:
        if not self._vkid_owner_tg_id:
            return
        if self._vkid_task and not self._vkid_task.done():
            return
        sess = await self._db.get_vkid_session(self._vkid_owner_tg_id)
        if not sess:
            logger.info("No VK ID session — watcher not started")
            return

        async def on_alert(item: ActivityItem) -> None:
            await self._send_vkid_alert(item)

        async def on_unauthorized(reason: str) -> None:
            with suppress(Exception):
                await self._bot.send_message(
                    self._vkid_owner_tg_id,
                    f"⚠️ VK ID сессия невалидна ({reason}).\n"
                    f"Обнови через /vkid_setup — нужен свежий access_token и cookies.",
                )

        async def on_stall(idle_sec: int) -> None:
            mins = idle_sec // 60
            with suppress(Exception):
                await self._bot.send_message(
                    self._vkid_owner_tg_id,
                    f"⚠️ VK ID watcher молчит уже <b>{mins} мин</b>.\n"
                    f"Что-то сломалось — проверь /vkid_status и логи.",
                    parse_mode=ParseMode.HTML,
                )

        watcher = VKIDWatcher(
            db=self._db,
            tg_id=self._vkid_owner_tg_id,
            alert=on_alert,
            alert_unauthorized=on_unauthorized,
            alert_stall=on_stall,
            poll_interval=self._vkid_poll_interval,
        )
        self._vkid_task = asyncio.create_task(watcher.run(), name="vkid-watcher")
        logger.info("VK ID watcher started for tg_id=%s", self._vkid_owner_tg_id)

    async def _maybe_notify_kate_reauth(self, users: list[User]) -> None:
        """Один раз просим пользователей перевыпустить токен после бана Kate Mobile."""
        flag = Path(self._db._path).parent / "kate_reauth_notice_v1"
        if flag.exists() or not users:
            return
        from bot.oauth import REAUTH_TEXT, auth_keyboard

        sent = 0
        for user in users:
            try:
                await self._bot.send_message(
                    user.tg_id,
                    REAUTH_TEXT,
                    parse_mode=ParseMode.HTML,
                    reply_markup=auth_keyboard(),
                    disable_web_page_preview=True,
                )
                sent += 1
            except TelegramAPIError as e:
                logger.warning("Failed to send Kate reauth notice to tg_id=%s: %s", user.tg_id, e)
        flag.write_text("sent\n")
        logger.info("Sent Kate Mobile reauth notice to %d/%d users", sent, len(users))

    async def shutdown(self) -> None:
        async with self._lock:
            tg_ids = list(self._workers.keys())
        for tg_id in tg_ids:
            await self.stop_user(tg_id)
        if self._vkid_task and not self._vkid_task.done():
            self._vkid_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._vkid_task

    async def start_user(self, user: User) -> None:
        async with self._lock:
            if user.tg_id in self._workers:
                await self._stop_locked(user.tg_id)

            session = aiohttp.ClientSession()
            client = VKClient(user.vk_token, session, limiter=self._limiter)
            self._last_ts_cache[user.tg_id] = user.last_notification_ts

            tg_id = user.tg_id

            async def on_message(text: str, peer_id: int, vk_msg_id: int) -> None:
                u = await self._db.get_user(tg_id)
                if not u or not u.enabled or not u.settings.get("messages", True):
                    return
                await self._send(tg_id, text, vk_peer_id=peer_id, vk_message_id=vk_msg_id)

            async def on_notification(text: str, category: str, ts: int) -> None:
                u = await self._db.get_user(tg_id)
                if not u or not u.enabled:
                    return
                if category and not u.settings.get(category, True):
                    # категория отключена — но ts всё равно двигаем, чтоб не висло
                    if ts > self._last_ts_cache.get(tg_id, 0):
                        self._last_ts_cache[tg_id] = ts
                        await self._db.update_last_notification_ts(tg_id, ts)
                    return
                await self._send(tg_id, text)
                if ts > self._last_ts_cache.get(tg_id, 0):
                    self._last_ts_cache[tg_id] = ts
                    await self._db.update_last_notification_ts(tg_id, ts)

            longpoll = LongPollWorker(client, session, on_message, user.vk_user_id)
            poller = NotificationsPoller(
                client,
                on_notification,
                lambda: self._last_ts_cache.get(tg_id, 0),
                self._notifications_interval,
                user.vk_user_id,
                initial_delay=self._notifications_interval + random.uniform(0, 30),
            )

            lp_task = asyncio.create_task(longpoll.run(), name=f"longpoll-{tg_id}")
            np_task = asyncio.create_task(poller.run(), name=f"notif-{tg_id}")

            self._workers[user.tg_id] = WorkerHandle(lp_task, np_task, session, client)
            logger.info("Started workers for tg_id=%s vk_user_id=%s", user.tg_id, user.vk_user_id)

    async def stop_user(self, tg_id: int) -> None:
        async with self._lock:
            await self._stop_locked(tg_id)

    async def _stop_locked(self, tg_id: int) -> None:
        handle = self._workers.pop(tg_id, None)
        if not handle:
            return
        handle.longpoll_task.cancel()
        handle.notifications_task.cancel()
        for t in (handle.longpoll_task, handle.notifications_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        await handle.session.close()
        self._last_ts_cache.pop(tg_id, None)
        logger.info("Stopped workers for tg_id=%s", tg_id)

    async def _send(
        self,
        tg_id: int,
        text: str,
        vk_peer_id: Optional[int] = None,
        vk_message_id: Optional[int] = None,
    ) -> None:
        try:
            msg = await self._bot.send_message(
                tg_id,
                text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except TelegramAPIError as e:
            logger.warning("Failed to send to tg_id=%s: %s", tg_id, e)
            return
        if vk_peer_id:
            try:
                await self._db.save_message_map(
                    msg.chat.id, msg.message_id, vk_peer_id, vk_message_id,
                )
            except Exception:
                logger.exception("Failed to save message_map")

    def get_client(self, tg_id: int) -> Optional[VKClient]:
        handle = self._workers.get(tg_id)
        return handle.client if handle else None

    def get_session(self, tg_id: int) -> Optional[aiohttp.ClientSession]:
        handle = self._workers.get(tg_id)
        return handle.session if handle else None

    async def _send_vkid_alert(self, item: ActivityItem) -> None:
        if not self._vkid_owner_tg_id:
            return
        tk = item.trust_key()
        trust = await self._db.get_vkid_trust(self._vkid_owner_tg_id, tk) or "unknown"
        header = (
            "🚨 <b>Заход с чужого устройства/подсети</b>"
            if trust == "not_mine"
            else "❓ <b>Новая неизвестная сессия</b>"
        )
        text = (
            f"{header}\n\n"
            f"📱 <b>{item.device_name}</b> · {item.device_os}\n"
            f"🧩 {item.app_name}\n"
            f"📍 {item.city or '—'}\n"
            f"🌐 <code>{item.ip}</code>  <i>(подсеть {item.ip_prefix()}.*)</i>\n"
            f"🕐 {item.created_at}"
        )
        kb = None
        if trust == "unknown":
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            from bot.handlers.vkid import register_key_for_alert
            short = register_key_for_alert(tk)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Это я", callback_data=f"vkid_alert_mine:{short}"),
                    InlineKeyboardButton(text="⚠️ Не я", callback_data=f"vkid_alert_not:{short}"),
                ],
            ])
        with suppress(TelegramAPIError):
            await self._bot.send_message(
                self._vkid_owner_tg_id,
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=kb,
                disable_web_page_preview=True,
            )
