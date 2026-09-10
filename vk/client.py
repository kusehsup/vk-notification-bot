import logging
import time
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from vk.rate_limit import VKFloodController

logger = logging.getLogger(__name__)

VK_API_URL = "https://api.vk.com/method/"
VK_API_VERSION = "5.199"

AUTH_ERROR_CODES = {5, 17}
FLOOD_ERROR_CODES = {6, 9, 29}


class VKAPIError(Exception):
    def __init__(
        self,
        code: int,
        message: str,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(f"VK API error {code}: {message}")
        self.code = code
        self.message = message
        self.retry_after = retry_after

    @property
    def is_auth(self) -> bool:
        return self.code in AUTH_ERROR_CODES

    @property
    def is_flood(self) -> bool:
        return self.code in FLOOD_ERROR_CODES


def parse_vk_error(err: dict) -> VKAPIError:
    retry_after = err.get("retry_after")
    try:
        retry_after_f = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_after_f = None
    return VKAPIError(
        code=int(err.get("error_code", 0) or 0),
        message=str(err.get("error_msg", "unknown")),
        retry_after=retry_after_f,
    )


SessionUpdatedCallback = Callable[[], Awaitable[None] | None]


class VKClient:
    def __init__(
        self,
        token: str,
        session: aiohttp.ClientSession,
        limiter: Optional[VKFloodController] = None,
        on_session_updated: Optional[SessionUpdatedCallback] = None,
    ) -> None:
        self._token = token
        self._session = session
        self._limiter = limiter
        self._on_session_updated = on_session_updated
        self._cookies: dict[str, str] = {}
        self._vk_app_id: int = 0
        self._token_expires_at: int = 0

    @property
    def token(self) -> str:
        return self._token

    @property
    def limiter(self) -> Optional[VKFloodController]:
        return self._limiter

    @property
    def vk_app_id(self) -> int:
        return self._vk_app_id

    @property
    def token_expires_at(self) -> int:
        return self._token_expires_at

    def cookies_header(self) -> str:
        from vk.web_token import cookies_to_header

        return cookies_to_header(self._cookies)

    def set_web_session(
        self,
        cookies: str | dict[str, str],
        app_id: int = 0,
        expires_at: int = 0,
    ) -> None:
        from vk.web_token import parse_cookie_header

        if isinstance(cookies, str):
            self._cookies = parse_cookie_header(cookies) if cookies else {}
        else:
            self._cookies = dict(cookies)
        self._vk_app_id = int(app_id or 0)
        self._token_expires_at = int(expires_at or 0)

    def can_refresh_web_token(self) -> bool:
        return bool(self._cookies)

    async def refresh_web_token_if_needed(self, force: bool = False) -> bool:
        """Обновить короткоживущий web-токен по cookies. True — токен сменился."""
        from vk.web_token import DEFAULT_WEB_APP_ID, fetch_web_token

        if not self._cookies:
            return False
        now = int(time.time())
        if not force and self._token_expires_at and now < self._token_expires_at - 180:
            return False
        result = await fetch_web_token(
            self._session,
            self._cookies,
            self._vk_app_id or DEFAULT_WEB_APP_ID,
            self._token or None,
        )
        self._cookies.update(result.cookies)
        self._token = result.access_token
        self._token_expires_at = result.expires_at
        if result.app_id:
            self._vk_app_id = result.app_id
        if self._on_session_updated:
            maybe = self._on_session_updated()
            if maybe is not None:
                await maybe
        return True

    async def try_refresh_after_auth_error(self) -> bool:
        from vk.web_token import WebTokenError, WebTokenUnauthorized

        if not self._cookies:
            return False
        try:
            return await self.refresh_web_token_if_needed(force=True)
        except WebTokenUnauthorized:
            return False
        except WebTokenError:
            logger.warning("web_token refresh failed for app_id=%s", self._vk_app_id)
            return False

    async def call(self, method: str, **params: Any) -> Any:
        if self._limiter:
            async with self._limiter.slot(self._token):
                return await self._call_once(method, **params)
        return await self._call_once(method, **params)

    async def _call_once(self, method: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        params["access_token"] = self._token
        params["v"] = VK_API_VERSION
        url = VK_API_URL + method
        async with self._session.post(url, data=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            data = await resp.json()
        if "error" in data:
            exc = parse_vk_error(data["error"] or {})
            if self._limiter and exc.is_flood:
                self._limiter.trip(self._token, exc.code, exc.retry_after)
            raise exc
        if self._limiter:
            self._limiter.note_success(self._token)
        return data.get("response")

    async def users_get(self, user_ids: Optional[str] = None, fields: Optional[str] = None) -> list[dict]:
        return await self.call("users.get", user_ids=user_ids, fields=fields)

    async def groups_get_by_id(self, group_ids: str) -> list[dict]:
        response = await self.call("groups.getById", group_ids=group_ids)
        if isinstance(response, dict) and "groups" in response:
            return response["groups"]
        return response

    async def messages_get_long_poll_server(self) -> dict:
        return await self.call("messages.getLongPollServer", need_pts=0, lp_version=3)

    async def notifications_get(self, count: int = 50, start_time: int = 0) -> dict:
        params: dict[str, Any] = {"count": count}
        if start_time:
            params["start_time"] = start_time
        return await self.call("notifications.get", **params)

    async def messages_get_by_id(self, message_ids: str) -> dict:
        return await self.call("messages.getById", message_ids=message_ids, extended=1)

    async def messages_get_conversations_by_id(self, peer_ids: str) -> dict:
        return await self.call(
            "messages.getConversationsById",
            peer_ids=peer_ids,
            extended=1,
        )

    async def messages_send(
        self,
        peer_id: int,
        message: str = "",
        attachment: str = "",
        random_id: int = 0,
        reply_to: int | None = None,
    ) -> int:
        return await self.call(
            "messages.send",
            peer_id=peer_id,
            message=message or None,
            attachment=attachment or None,
            random_id=random_id,
            reply_to=reply_to,
        )

    async def photos_get_messages_upload_server(self, peer_id: int) -> dict:
        return await self.call("photos.getMessagesUploadServer", peer_id=peer_id)

    async def photos_save_messages_photo(self, photo: str, server: int, hash_: str) -> list[dict]:
        return await self.call(
            "photos.saveMessagesPhoto",
            photo=photo,
            server=server,
            hash=hash_,
        )

    async def docs_get_messages_upload_server(self, peer_id: int, type_: str) -> dict:
        # type_: "doc", "audio_message", "graffiti"
        return await self.call("docs.getMessagesUploadServer", peer_id=peer_id, type=type_)

    async def docs_save(self, file: str, title: str = "") -> dict:
        return await self.call("docs.save", file=file, title=title or None)

    async def video_save(self, name: str = "", description: str = "") -> dict:
        return await self.call("video.save", name=name or None, description=description or None)
