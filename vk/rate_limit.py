"""Ограничение частоты запросов к VK API и пауза после Flood control.

С 8–9 сентября 2026 VK ужесточил лимиты для сторонних приложений (Kate Mobile и др.):
error 9 (Flood control) и 29 (Rate limit reached) приходят даже при умеренном RPS.
Повтор каждые 5–25 секунд только продлевает блокировку, поэтому после этих ошибок
нужна длинная пауза и не больше одного method-вызова одновременно.
"""
from __future__ import annotations

import asyncio
import logging
import random
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import AsyncIterator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FloodPolicy:
    min_interval: float = 0.7
    flood_initial: float = 900.0
    flood_max: float = 3600.0
    rate_limit_initial: float = 180.0
    rate_limit_max: float = 900.0
    global_trip_threshold: int = 2
    global_trip_window: float = 180.0
    global_trip_seconds: float = 1800.0
    jitter: float = 0.2
    startup_cooldown: float = 0.0


class VKFloodController:
    """Общий на процесс лимитер: один in-flight method-вызов + cooldown по токену/IP."""

    def __init__(
        self,
        policy: FloodPolicy | None = None,
        clock=time.monotonic,
    ) -> None:
        self.policy = policy or FloodPolicy()
        self._clock = clock
        self._lock = threading.Lock()
        self._aio_lock: asyncio.Lock | None = None
        self._last_call_at: float = 0.0
        self._token_until: dict[str, float] = {}
        self._token_streak: dict[str, int] = {}
        self._recent_trips: list[tuple[float, str]] = []
        self._global_until: float = 0.0
        if self.policy.startup_cooldown > 0:
            self._global_until = self._clock() + self.policy.startup_cooldown
            logger.info(
                "VK API startup cooldown %.0fs — no method calls until it elapses",
                self.policy.startup_cooldown,
            )

    @staticmethod
    def token_key(token: str) -> str:
        return token[-12:] if len(token) > 12 else token

    def is_cooling(self, token: str) -> bool:
        now = self._clock()
        with self._lock:
            until = max(self._global_until, self._token_until.get(self.token_key(token), 0.0))
        return until > now

    def remaining(self, token: str) -> float:
        now = self._clock()
        with self._lock:
            until = max(self._global_until, self._token_until.get(self.token_key(token), 0.0))
        return max(0.0, until - now)

    def global_remaining(self) -> float:
        now = self._clock()
        with self._lock:
            return max(0.0, self._global_until - now)

    def _ensure_aio_lock(self) -> asyncio.Lock:
        if self._aio_lock is None:
            self._aio_lock = asyncio.Lock()
        return self._aio_lock

    def _next_delay(self, token: str) -> float:
        key = self.token_key(token)
        now = self._clock()
        with self._lock:
            until = max(self._global_until, self._token_until.get(key, 0.0))
            cool = until - now
            if cool > 0:
                return cool
            gap = self.policy.min_interval - (now - self._last_call_at)
            return max(0.0, gap)

    @asynccontextmanager
    async def slot(self, token: str) -> AsyncIterator[None]:
        """Эксклюзивный слот на один method-вызов. Держится, пока запрос не завершится."""
        key = self.token_key(token)
        while True:
            delay = self._next_delay(token)
            if delay > 0:
                if delay >= 5:
                    logger.info("VK API paused for %.0fs (token=...%s)", delay, key)
                await asyncio.sleep(delay)
                continue
            await self._ensure_aio_lock().acquire()
            delay = self._next_delay(token)
            if delay > 0:
                self._ensure_aio_lock().release()
                continue
            with self._lock:
                self._last_call_at = self._clock()
            break
        try:
            yield
        finally:
            with self._lock:
                self._last_call_at = self._clock()
            self._ensure_aio_lock().release()

    def trip(self, token: str, error_code: int, retry_after: float | None = None) -> float:
        """Зафиксировать flood/rate-limit. Возвращает секунды паузы для этого токена."""
        key = self.token_key(token)
        now = self._clock()
        with self._lock:
            streak = self._token_streak.get(key, 0) + 1
            self._token_streak[key] = streak

            if error_code == 9:
                base = self.policy.flood_initial
                cap = self.policy.flood_max
            else:
                base = self.policy.rate_limit_initial
                cap = self.policy.rate_limit_max

            wait = min(base * (2 ** (streak - 1)), cap)
            if retry_after and retry_after > wait:
                wait = min(float(retry_after), cap)
            if self.policy.jitter:
                wait *= 1 + random.uniform(-self.policy.jitter, self.policy.jitter)

            prev = self._token_until.get(key, 0.0)
            self._token_until[key] = max(prev, now + wait)

            self._recent_trips.append((now, key))
            cutoff = now - self.policy.global_trip_window
            self._recent_trips = [(t, k) for t, k in self._recent_trips if t >= cutoff]
            unique = {k for _, k in self._recent_trips}
            global_wait = 0.0
            if len(unique) >= self.policy.global_trip_threshold:
                self._global_until = max(
                    self._global_until,
                    now + self.policy.global_trip_seconds,
                )
                global_wait = self._global_until - now
                logger.warning(
                    "VK flood looks IP-wide (%d tokens in %.0fs) — pausing all API calls for %.0fs",
                    len(unique),
                    self.policy.global_trip_window,
                    global_wait,
                )

            logger.warning(
                "VK flood trip token=...%s code=%s streak=%d wait=%.0fs global_in=%.0fs",
                key,
                error_code,
                streak,
                wait,
                global_wait,
            )
            return wait

    def note_success(self, token: str) -> None:
        key = self.token_key(token)
        with self._lock:
            self._token_streak.pop(key, None)
            self._token_until.pop(key, None)
