import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

import aiohttp

from vk.client import VKAPIError, VKClient
from vk.formatters import format_longpoll_message, format_message_event

logger = logging.getLogger(__name__)

# Биты flags из VK Long Poll
FLAG_OUTBOX = 2

EVENT_NEW_MESSAGE = 4

# Если push_settings.disabled_until == -1 → заглушено навсегда
# Иначе — unix timestamp до которого глушить (0 = не заглушено)

PEER_META_TTL = 15 * 60  # сек; дольше — меньше getConversationsById при flood

MessageCallback = Callable[[str, int, int], Awaitable[None]]
# (formatted_text, peer_id, vk_message_id)


@dataclass
class PeerMeta:
    title: Optional[str]
    disabled_forever: bool
    disabled_until: int  # 0 — нет, иначе unix ts до которого заглушено
    no_sound: bool  # «без звука» в клиенте VK — тоже считаем мутом для пушей
    fetched_at: float

    def is_muted(self, now: float) -> bool:
        if self.disabled_forever:
            return True
        if self.disabled_until and self.disabled_until > now:
            return True
        return False

    def is_fresh(self, now: float) -> bool:
        return (now - self.fetched_at) < PEER_META_TTL


class LongPollWorker:
    def __init__(
        self,
        client: VKClient,
        session: aiohttp.ClientSession,
        on_message: MessageCallback,
        vk_user_id: int,
    ) -> None:
        self._client = client
        self._session = session
        self._on_message = on_message
        self._vk_user_id = vk_user_id
        self._peer_meta: dict[int, PeerMeta] = {}

    async def run(self) -> None:
        backoff = 5.0
        while True:
            started = time.monotonic()
            try:
                await self._loop()
            except asyncio.CancelledError:
                raise
            except VKAPIError as e:
                logger.warning("VK API error in longpoll (user=%s): %s", self._vk_user_id, e)
                if e.is_auth:
                    logger.error("Token invalid for user=%s, stopping longpoll", self._vk_user_id)
                    return
                wait = backoff
                if e.is_flood and self._client.limiter:
                    wait = max(wait, self._client.limiter.remaining(self._client.token), 1.0)
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 120)
                continue
            except Exception:
                logger.exception("Longpoll loop crashed (user=%s)", self._vk_user_id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 120)
                continue

            elapsed = time.monotonic() - started
            if elapsed > 60:
                # Сессия жила нормально, ключ просто истек — сразу новый server.
                backoff = 5.0
                continue
            # Короткий цикл (failed=2/3 сразу) — не дёргаем getLongPollServer без паузы.
            logger.info(
                "Longpoll reconnect for user=%s after %.1fs, sleeping %.0fs",
                self._vk_user_id,
                elapsed,
                backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _loop(self) -> None:
        server_info = await self._client.messages_get_long_poll_server()
        server = server_info["server"]
        key = server_info["key"]
        ts = server_info["ts"]
        url = f"https://{server}" if not server.startswith("http") else server

        while True:
            params = {
                "act": "a_check",
                "key": key,
                "ts": ts,
                "wait": 25,
                "mode": 2 | 8 | 64 | 128,
                "version": 3,
            }
            async with self._session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=40)) as resp:
                data = await resp.json()

            if "failed" in data:
                code = data["failed"]
                if code == 1:
                    ts = data["ts"]
                    continue
                return

            ts = data.get("ts", ts)
            for update in data.get("updates", []):
                await self._handle_update(update)

    def _api_cooling(self) -> bool:
        limiter = self._client.limiter
        return bool(limiter and limiter.is_cooling(self._client.token))

    async def _get_peer_meta(self, peer_id: int) -> Optional[PeerMeta]:
        now = time.time()
        cached = self._peer_meta.get(peer_id)
        if cached and cached.is_fresh(now):
            return cached
        if cached and self._api_cooling():
            return cached
        try:
            response = await self._client.messages_get_conversations_by_id(str(peer_id))
        except VKAPIError as e:
            logger.warning("getConversationsById failed for peer=%s: %s", peer_id, e)
            return cached  # отдадим хоть устаревший, чем ничего

        items = response.get("items") if isinstance(response, dict) else None
        if not items:
            return cached

        item = items[0]
        chat_settings = item.get("chat_settings") or {}
        push = item.get("push_settings") or {}
        title = chat_settings.get("title")

        meta = PeerMeta(
            title=title,
            disabled_forever=bool(push.get("disabled_forever", False)),
            disabled_until=int(push.get("disabled_until", 0) or 0),
            no_sound=bool(push.get("no_sound", False)),
            fetched_at=now,
        )
        self._peer_meta[peer_id] = meta
        return meta

    async def _emit_from_longpoll(
        self,
        message_id: int,
        peer_id: int,
        raw_text: str,
        extras: dict,
        meta: Optional[PeerMeta],
    ) -> None:
        text = format_longpoll_message(
            peer_id,
            raw_text,
            extras,
            chat_title=meta.title if meta else None,
        )
        await self._on_message(text, peer_id, message_id)

    async def _handle_update(self, update: list) -> None:
        if not update:
            return
        code = update[0]
        if code != EVENT_NEW_MESSAGE:
            return

        try:
            message_id = update[1]
            flags = update[2]
            peer_id_lp = update[3] if len(update) > 3 else 0
        except (IndexError, TypeError):
            return

        if flags & FLAG_OUTBOX:
            return

        raw_text = update[5] if len(update) > 5 and isinstance(update[5], str) else ""
        extras = update[6] if len(update) > 6 and isinstance(update[6], dict) else {}

        # Сначала — проверка мута по peer'у из самого Long Poll (без API-вызова за сообщением)
        meta = await self._get_peer_meta(peer_id_lp) if peer_id_lp else None
        if meta and meta.is_muted(time.time()):
            return

        if self._api_cooling():
            await self._emit_from_longpoll(message_id, peer_id_lp, raw_text, extras, meta)
            return

        try:
            result = await self._client.messages_get_by_id(str(message_id))
        except VKAPIError as e:
            logger.warning("messages.getById failed for %s: %s", message_id, e)
            await self._emit_from_longpoll(message_id, peer_id_lp, raw_text, extras, meta)
            return

        items = result.get("items", []) if isinstance(result, dict) else []
        if not items:
            await self._emit_from_longpoll(message_id, peer_id_lp, raw_text, extras, meta)
            return
        message = items[0]

        profiles = {p["id"]: p for p in (result.get("profiles") or [])}
        groups = {g["id"]: g for g in (result.get("groups") or [])}

        peer_id = message.get("peer_id", 0) or peer_id_lp
        vk_msg_id = message.get("id", 0) or message_id
        chat_title = meta.title if meta else None
        text = format_message_event(message, profiles, groups, chat_title=chat_title)
        await self._on_message(text, peer_id, vk_msg_id)
