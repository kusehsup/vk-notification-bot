"""Клиент для скрытого VK ID API.

Умеет:
- обновлять access_token через login.vk.com/?act=web_token (нужен старый токен + web-cookies)
- получать список активных/недавних сессий через api.vk.com/method/accountPersonal.getActivityHistoryGroup

Токен живёт ~24 минуты. Обновляем заранее.
Cookies (`remixsid` + `p`) живут долго, обновляются VK через Set-Cookie при вызовах.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


VKID_APP_ID = 7344294  # "Личный кабинет VK ID"
KATE_APP_ID = 2685278
API_VERSION = "5.190"

WEB_TOKEN_URL = "https://login.vk.com/?act=web_token"
ACTIVITY_URL = "https://api.vk.com/method/accountPersonal.getActivityHistoryGroup"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0"
)


class VKIDError(Exception):
    pass


class VKIDUnauthorized(VKIDError):
    """Cookies или токен протухли — нужно переустановить сессию через /vkid_setup."""


@dataclass
class VKIDSession:
    access_token: str
    cookies: str  # cookie header string
    expires_at: int
    logout_hash: Optional[str] = None


@dataclass
class ActivityItem:
    device_id: str
    device_name: str
    device_os: str
    app_name: str
    app_id: int
    city: str
    ip: str
    created_at: str
    updated_at: str
    map_hash: str
    is_inactive: bool
    is_current_week: bool
    is_back_to_back: bool
    app_icon: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ActivityItem":
        return cls(
            device_id=d.get("device_id", ""),
            device_name=d.get("device_name", ""),
            device_os=d.get("device_os", ""),
            app_name=d.get("app_name", ""),
            app_id=int(d.get("app_id", 0)),
            city=d.get("city", ""),
            ip=d.get("ip", ""),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            map_hash=d.get("map_hash", ""),
            is_inactive=bool(d.get("is_inactive", False)),
            is_current_week=bool(d.get("is_current_week", False)),
            is_back_to_back=bool(d.get("is_back_to_back", False)),
            app_icon=d.get("app_icon", ""),
        )

    def ip_prefix(self) -> str:
        """Первые два октета IP — определяет подсеть провайдера."""
        parts = (self.ip or "").split(".")
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return self.ip or ""

    def trust_key(self) -> str:
        """Ключ для меток trust — идентифицирует «класс» сессии, а не отдельный вход.

        Различает: устройство + подсеть + приложение. Смена IP внутри подсети — та же сущность.
        """
        return f"{self.device_id}|{self.ip_prefix()}|{self.app_id}"

    def fingerprint(self) -> str:
        """Уникальный ключ для дедупликации отдельного захода (для watcher)."""
        return f"{self.device_id}|{self.app_id}|{self.ip}|{self.created_at}"


def _parse_cookie_header(cookie_header: str) -> dict[str, str]:
    """cookie1=v1; cookie2=v2 → {cookie1: v1, cookie2: v2}."""
    out: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def _cookies_to_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


class VKIDClient:
    def __init__(self, session: VKIDSession) -> None:
        self.session = session
        self._cookies = _parse_cookie_header(session.cookies)

    def cookies_header(self) -> str:
        return _cookies_to_header(self._cookies)

    def _merge_response_cookies(self, resp: aiohttp.ClientResponse) -> None:
        """Обновляем локальные cookies из Set-Cookie."""
        for name, morsel in resp.cookies.items():
            v = morsel.value
            # VK шлёт "DELETED" при инвалидации отдельных cookie — пропускаем
            if v == "DELETED":
                self._cookies.pop(name, None)
                continue
            if name in {"remixsid", "p", "remixnsid", "remixstid", "remixstlid"}:
                self._cookies[name] = v
        # обновляем строковую версию в session
        self.session.cookies = self.cookies_header()

    async def refresh_token(self, http: aiohttp.ClientSession) -> None:
        """Получить свежий access_token. Раз в ~24 минуты или заранее."""
        headers = {
            "Origin": "https://id.vk.com",
            "Referer": "https://id.vk.com/",
            "User-Agent": DEFAULT_UA,
            "Cookie": self.cookies_header(),
        }
        data = {
            "version": "1",
            "app_id": str(VKID_APP_ID),
            "access_token": self.session.access_token,
        }
        async with http.post(WEB_TOKEN_URL, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = await resp.json(content_type=None)
            self._merge_response_cookies(resp)

        if body.get("type") != "okay":
            info = body.get("error_info") or body.get("error_msg") or body
            if info in ("unauthorized", "invalid_token") or "unauthorized" in str(info):
                raise VKIDUnauthorized(f"web_token: {info}")
            raise VKIDError(f"web_token failed: {body}")

        d = body["data"]
        self.session.access_token = d["access_token"]
        self.session.expires_at = int(d.get("expires", 0))
        self.session.logout_hash = d.get("logout_hash") or self.session.logout_hash

    async def get_activity(self, http: aiohttp.ClientSession) -> list[ActivityItem]:
        """Получить список сессий."""
        headers = {
            "Origin": "https://id.vk.com",
            "Referer": "https://id.vk.com/",
            "User-Agent": DEFAULT_UA,
        }
        data = {
            "lang": "0",
            "v": API_VERSION,
            "access_token": self.session.access_token,
            "vkui": "1",
        }
        async with http.post(ACTIVITY_URL, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            body = await resp.json(content_type=None)

        if "error" in body:
            err = body["error"]
            code = err.get("error_code")
            msg = err.get("error_msg", "")
            if code in (5, 15):
                raise VKIDUnauthorized(f"activity: {code} {msg}")
            raise VKIDError(f"activity error {code}: {msg}")

        items = body.get("response") or []
        return [ActivityItem.from_dict(x) for x in items]

    def token_needs_refresh(self, safety_margin: int = 120) -> bool:
        return self.session.expires_at - safety_margin < int(time.time())
