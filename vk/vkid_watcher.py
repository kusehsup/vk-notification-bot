"""Фоновый воркер, следит за новыми сессиями VK ID.

Раз в POLL_INTERVAL сек:
- если нужно — обновляет access_token через web_token
- получает список сессий через accountPersonal.getActivityHistoryGroup
- сравнивает с БД (по fingerprint), новые из не-«моих» устройств → уведомление в TG
- обновляет device_id / last_seen в БД
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

import aiohttp

from storage.db import Database
from vk.vkid_client import (
    KATE_APP_ID,
    VKID_APP_ID,
    ActivityItem,
    VKIDClient,
    VKIDError,
    VKIDSession,
    VKIDUnauthorized,
)

logger = logging.getLogger(__name__)


AlertCallback = Callable[[ActivityItem], Awaitable[None]]


STALL_THRESHOLD = 30 * 60  # 30 минут без успешного тика = алерт


class VKIDWatcher:
    def __init__(
        self,
        db: Database,
        tg_id: int,
        alert: AlertCallback,
        alert_unauthorized: Callable[[str], Awaitable[None]],
        alert_stall: Callable[[int], Awaitable[None]],
        poll_interval: int = 60,
    ) -> None:
        self._db = db
        self._tg_id = tg_id
        self._alert = alert
        self._alert_unauthorized = alert_unauthorized
        self._alert_stall = alert_stall
        self._poll_interval = poll_interval

    async def run(self) -> None:
        backoff = self._poll_interval
        while True:
            try:
                await self._tick()
                await self._db.mark_vkid_tick_success(self._tg_id)
                await asyncio.sleep(self._poll_interval)
                backoff = self._poll_interval
            except asyncio.CancelledError:
                raise
            except VKIDUnauthorized as e:
                logger.warning("VK ID unauthorized: %s", e)
                await self._alert_unauthorized(str(e))
                return
            except Exception:
                logger.exception("VK ID watcher tick failed")
                await self._maybe_alert_stall()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 1800)

    async def _maybe_alert_stall(self) -> None:
        sess = await self._db.get_vkid_session(self._tg_id)
        if not sess:
            return
        now = int(time.time())
        last_ok = sess.get("last_success_at") or 0
        alert_sent = sess.get("stall_alert_sent_at") or 0
        if last_ok == 0:
            return  # ещё ни разу не успевали — не алертим (может быть первый запуск)
        idle = now - last_ok
        if idle < STALL_THRESHOLD:
            return
        if alert_sent > last_ok:
            return  # уже алертнули после последнего успеха
        try:
            await self._alert_stall(idle)
            await self._db.mark_vkid_stall_alert_sent(self._tg_id)
        except Exception:
            logger.exception("stall alert callback failed")

    async def _tick(self) -> None:
        sess = await self._db.get_vkid_session(self._tg_id)
        if not sess:
            raise VKIDUnauthorized("no vkid session in db")

        vkid = VKIDClient(VKIDSession(
            access_token=sess["access_token"],
            cookies=sess["cookies"],
            expires_at=sess["expires_at"],
            logout_hash=sess["logout_hash"],
        ))

        async with aiohttp.ClientSession() as http:
            if vkid.token_needs_refresh():
                await vkid.refresh_token(http)
                await self._db.upsert_vkid_session(
                    tg_id=self._tg_id,
                    access_token=vkid.session.access_token,
                    cookies=vkid.session.cookies,
                    expires_at=vkid.session.expires_at,
                    logout_hash=vkid.session.logout_hash,
                )

            items = await vkid.get_activity(http)

        for item in items:
            # игнорируем шум от нас самих
            if item.app_id == KATE_APP_ID:
                continue
            if item.app_id == VKID_APP_ID and item.device_name == "Python aiohttp":
                continue

            fp = item.fingerprint()
            already_seen = await self._db.has_seen_vkid_session(self._tg_id, fp)
            if already_seen:
                # обновляем last_seen в trust-записи
                await self._db.upsert_vkid_trust(
                    tg_id=self._tg_id,
                    trust_key=item.trust_key(),
                    device_name=item.device_name,
                    device_os=item.device_os,
                    app_name=item.app_name,
                    city=item.city,
                    ip=item.ip,
                    trust=None,
                )
                continue

            # новая сессия
            await self._db.mark_seen_vkid_session(self._tg_id, fp)

            tk = item.trust_key()
            trust = await self._db.get_vkid_trust(self._tg_id, tk)
            if trust is None:
                await self._db.upsert_vkid_trust(
                    tg_id=self._tg_id,
                    trust_key=tk,
                    device_name=item.device_name,
                    device_os=item.device_os,
                    app_name=item.app_name,
                    city=item.city,
                    ip=item.ip,
                    trust="unknown",
                )
                trust = "unknown"
            else:
                await self._db.upsert_vkid_trust(
                    tg_id=self._tg_id,
                    trust_key=tk,
                    device_name=item.device_name,
                    device_os=item.device_os,
                    app_name=item.app_name,
                    city=item.city,
                    ip=item.ip,
                    trust=None,
                )

            # уведомляем только про not_mine и unknown; mine и ignore — молча
            if trust in ("not_mine", "unknown"):
                try:
                    await self._alert(item)
                except Exception:
                    logger.exception("VK ID alert callback failed")
