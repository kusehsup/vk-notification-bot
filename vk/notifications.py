import asyncio
import logging
from typing import Awaitable, Callable

from vk.client import VKAPIError, VKClient
from vk.formatters import format_notification, notification_category

logger = logging.getLogger(__name__)


NotificationCallback = Callable[[str, str, int], Awaitable[None]]
# (formatted_text, category, item_ts)


class NotificationsPoller:
    def __init__(
        self,
        client: VKClient,
        on_notification: NotificationCallback,
        get_last_ts: Callable[[], int],
        interval: int,
        vk_user_id: int,
        initial_delay: float = 0,
    ) -> None:
        self._client = client
        self._on_notification = on_notification
        self._get_last_ts = get_last_ts
        self._interval = interval
        self._vk_user_id = vk_user_id
        self._initial_delay = initial_delay

    async def run(self) -> None:
        if self._initial_delay:
            await asyncio.sleep(self._initial_delay)
        backoff = float(self._interval)
        while True:
            try:
                await self._tick()
                await asyncio.sleep(self._interval)
                backoff = float(self._interval)
            except asyncio.CancelledError:
                raise
            except VKAPIError as e:
                logger.warning("VK API error in notifications (user=%s): %s", self._vk_user_id, e)
                if e.is_auth:
                    logger.error("Token invalid for user=%s, stopping notifications", self._vk_user_id)
                    return
                wait = backoff
                if e.is_flood and self._client.limiter:
                    wait = max(wait, self._client.limiter.remaining(self._client.token), 1.0)
                await asyncio.sleep(wait)
                backoff = min(backoff * 2, 1800)
            except Exception:
                logger.exception("Notifications poller crashed (user=%s)", self._vk_user_id)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 1800)

    async def _tick(self) -> None:
        last_ts = self._get_last_ts()
        start_time = last_ts + 1 if last_ts else 0
        response = await self._client.notifications_get(count=50, start_time=start_time)
        if not response:
            return

        items = response.get("items") or []
        profiles = {p["id"]: p for p in (response.get("profiles") or [])}
        groups = {g["id"]: g for g in (response.get("groups") or [])}

        # items приходят от свежих к старым — отправляем в обратном порядке
        new_items = [it for it in items if it.get("date", 0) > last_ts]
        new_items.sort(key=lambda x: x.get("date", 0))

        for item in new_items:
            ntype = item.get("type", "")
            category = notification_category(ntype)
            text = format_notification(item, profiles, groups)
            ts = item.get("date", 0)
            await self._on_notification(text, category, ts)
