"""Обмен web-cookies vk.com на access_token через login.vk.com/?act=web_token.

OAuth standalone-приложений с правом messages (Kate, VK Admin, Android)
закрыт: «application is blocked» / «Unavailable for apps with direct auth».
Сайт vk.com по-прежнему выдаёт короткоживущий токен приложения 6287487
по cookie `remixsid` — тем же запросом, что и открытая вкладка ВК.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import aiohttp

from vk.client import VKAPIError, VKClient
from vk.rate_limit import VKFloodController

logger = logging.getLogger(__name__)

DEFAULT_WEB_APP_ID = 6287487  # vk.com / vk.ru

# Если у 6287487 нет messages.getLongPollServer — пробуем другие web-приложения.
WEB_APP_CANDIDATES: tuple[int, ...] = (
    6287487,  # vk.com
    7793118,  # VK Calls
    7556576,  # Sferum
    7497650,  # VK Connect
    7799655,  # VK Mail
    4083558,  # VFeed
)

WEB_TOKEN_ENDPOINTS: tuple[tuple[str, str, str], ...] = (
    ("https://login.vk.com/?act=web_token", "https://vk.com", "https://vk.com/"),
    ("https://login.vk.ru/?act=web_token", "https://vk.ru", "https://vk.ru/"),
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

NO_MESSAGES_CODES = {7, 15, 20, 21, 27, 28}

_REMIXSID_RE = re.compile(r"remixsid", re.IGNORECASE)
_CURL_COOKIE_RE = re.compile(
    r"""(?:^|[\s'"\\])(?:[Cc]ookie):\s*([^\n"'\\]+)""",
)


class WebTokenError(Exception):
    def __init__(self, message: str, unauthorized: bool = False) -> None:
        super().__init__(message)
        self.unauthorized = unauthorized


class WebTokenUnauthorized(WebTokenError):
    def __init__(self, message: str = "web_token: unauthorized") -> None:
        super().__init__(message, unauthorized=True)


@dataclass
class WebTokenResult:
    access_token: str
    cookies: dict[str, str]
    expires_at: int
    app_id: int
    user_id: int = 0


@dataclass
class WebSession:
    access_token: str
    cookies: dict[str, str]
    expires_at: int
    app_id: int
    users: list[dict[str, Any]] = field(default_factory=list)


def cookies_to_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items() if k and v)


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        name = k.strip()
        if not name:
            continue
        out[name] = v.strip()
    return out


def looks_like_cookies(text: str) -> bool:
    return bool(text and _REMIXSID_RE.search(text))


def parse_cookie_blob(text: str) -> Optional[dict[str, str]]:
    """Разобрать Cookie header, JSON, Netscape dump или curl -H 'Cookie: ...'."""
    if not text or not text.strip():
        return None
    raw = text.strip()
    if raw.startswith("\ufeff"):
        raw = raw.lstrip("\ufeff")

    curl = _CURL_COOKIE_RE.search(raw)
    if curl:
        parsed = parse_cookie_header(curl.group(1).strip().strip("'").strip('"'))
        if _has_remixsid(parsed):
            return parsed

    if raw[:1] in "{[":
        parsed = _parse_cookie_json(raw)
        if parsed and _has_remixsid(parsed):
            return parsed

    if "\t" in raw and _looks_like_netscape(raw):
        parsed = _parse_netscape(raw)
        if parsed and _has_remixsid(parsed):
            return parsed

    parsed = _parse_devtool_table(raw)
    if parsed and _has_remixsid(parsed):
        return parsed

    # Обычный заголовок Cookie: remixsid=...; p=...
    header = raw
    if header.lower().startswith("cookie:"):
        header = header.split(":", 1)[1].strip()
    parsed = parse_cookie_header(header)
    if parsed and _has_remixsid(parsed):
        return parsed
    return None


def _has_remixsid(cookies: dict[str, str]) -> bool:
    return any(k.lower().startswith("remixsid") for k in cookies)


def _parse_cookie_json(raw: str) -> Optional[dict[str, str]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    out: dict[str, str] = {}
    if isinstance(data, dict):
        # { "remixsid": "...", "p": "..." } или Cookie-Editor {cookies: [...]}
        if "cookies" in data and isinstance(data["cookies"], list):
            data = data["cookies"]
        else:
            for k, v in data.items():
                if isinstance(v, (str, int)):
                    out[str(k)] = str(v)
                elif isinstance(v, dict) and "value" in v:
                    out[str(v.get("name") or k)] = str(v["value"])
            return out or None
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("Name")
            value = item.get("value") or item.get("Value")
            if name and value is not None:
                out[str(name)] = str(value)
        return out or None
    return None


def _looks_like_netscape(raw: str) -> bool:
    if "# Netscape" in raw or "# HTTP Cookie File" in raw:
        return True
    for line in raw.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            return True
    return False


def _parse_netscape(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        name, value = parts[5], parts[6]
        if name:
            out[name] = value
    return out


def _parse_devtool_table(raw: str) -> dict[str, str]:
    """Chrome Application → Cookies: name [tab/spaces] value [tab] domain."""
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            parts = line.split()
        if len(parts) < 2:
            continue
        name, value = parts[0], parts[1]
        if name.lower() in {"name", "cookie", "host", "domain"}:
            continue
        if re.match(r"^[A-Za-z0-9_.-]+$", name) and value:
            out[name] = value
    return out


def _parse_expires(data: dict[str, Any]) -> int:
    raw = data.get("expires")
    if raw is None:
        raw = data.get("expired_at") or data.get("expires_at")
    try:
        expires = int(raw or 0)
    except (TypeError, ValueError):
        expires = 0
    now = int(time.time())
    if expires <= 0:
        return now + 24 * 60
    if expires < 10_000_000:
        return now + expires
    return expires


def _merge_response_cookies(existing: dict[str, str], resp: aiohttp.ClientResponse) -> dict[str, str]:
    out = dict(existing)
    for name, morsel in resp.cookies.items():
        value = morsel.value
        if value == "DELETED":
            out.pop(name, None)
            continue
        out[name] = value
    return out


def _is_unauthorized(info: Any) -> bool:
    text = str(info).lower()
    return info in ("unauthorized", "invalid_token") or "unauthorized" in text


async def fetch_web_token(
    http: aiohttp.ClientSession,
    cookies: dict[str, str],
    app_id: int = DEFAULT_WEB_APP_ID,
    access_token: Optional[str] = None,
) -> WebTokenResult:
    """POST login.vk.com/?act=web_token. Токен живёт ~24 минуты."""
    if not _has_remixsid(cookies):
        raise WebTokenError("В cookies нет remixsid — это не сессия vk.com")

    last_err: Optional[Exception] = None
    for url, origin, referer in WEB_TOKEN_ENDPOINTS:
        headers = {
            "Origin": origin,
            "Referer": referer,
            "User-Agent": DEFAULT_UA,
            "Cookie": cookies_to_header(cookies),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data: dict[str, str] = {
            "version": "1",
            "app_id": str(app_id),
        }
        if access_token:
            data["access_token"] = access_token
        try:
            async with http.post(
                url,
                data=data,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                body = await resp.json(content_type=None)
                merged = _merge_response_cookies(cookies, resp)
        except Exception as e:
            last_err = e
            logger.warning("web_token %s failed: %s", url, e)
            continue

        if body.get("type") != "okay":
            info = body.get("error_info") or body.get("error_msg") or body
            if _is_unauthorized(info):
                raise WebTokenUnauthorized(f"web_token: {info}")
            last_err = WebTokenError(f"web_token failed: {info}")
            continue

        payload = body.get("data") or {}
        token = payload.get("access_token")
        if not token:
            last_err = WebTokenError(f"web_token: нет access_token ({body})")
            continue
        user_id = 0
        try:
            user_id = int(payload.get("user_id") or 0)
        except (TypeError, ValueError):
            user_id = 0
        return WebTokenResult(
            access_token=str(token),
            cookies=merged,
            expires_at=_parse_expires(payload),
            app_id=app_id,
            user_id=user_id,
        )

    if isinstance(last_err, WebTokenError):
        raise last_err
    raise WebTokenError(f"web_token недоступен: {last_err}")


async def exchange_cookies_for_api(
    http: aiohttp.ClientSession,
    cookies: dict[str, str],
    limiter: Optional[VKFloodController] = None,
    extra_token: Optional[str] = None,
) -> WebSession:
    """Получить токен, у которого работают users.get и messages.getLongPollServer."""
    last_err: Optional[Exception] = None
    merged = dict(cookies)
    token_hint = extra_token
    for app_id in WEB_APP_CANDIDATES:
        try:
            result = await fetch_web_token(http, merged, app_id, token_hint)
        except WebTokenUnauthorized:
            raise
        except WebTokenError as e:
            logger.info("web_token app_id=%s: %s", app_id, e)
            last_err = e
            continue
        merged.update(result.cookies)
        token_hint = result.access_token
        client = VKClient(result.access_token, http, limiter=limiter)
        try:
            users = await client.users_get()
            await client.messages_get_long_poll_server()
        except VKAPIError as e:
            last_err = e
            if e.is_flood:
                raise
            logger.info(
                "app_id=%s token rejected by API: %s",
                app_id,
                e,
            )
            if e.is_auth or e.code in NO_MESSAGES_CODES:
                continue
            continue
        return WebSession(
            access_token=result.access_token,
            cookies=merged,
            expires_at=result.expires_at,
            app_id=app_id,
            users=list(users or []),
        )
    if last_err:
        raise last_err
    raise WebTokenError("Не удалось получить токен с доступом к сообщениям ВК")
