from __future__ import annotations

import asyncio
from typing import Any

from vk.web_token import (
    WebTokenUnauthorized,
    exchange_cookies_for_api,
    fetch_web_token,
)


class FakeMorsel:
    def __init__(self, value: str) -> None:
        self.value = value


class FakeResponse:
    def __init__(self, payload: dict[str, Any], set_cookies: dict[str, str] | None = None) -> None:
        self._payload = payload
        self.cookies = {k: FakeMorsel(v) for k, v in (set_cookies or {}).items()}

    async def json(self, content_type: Any = None) -> dict[str, Any]:
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeSession:
    def __init__(self, handler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append((url, kwargs))
        return self.handler(url, kwargs)


def test_fetch_web_token_ok() -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        assert "act=web_token" in url
        data = kwargs["data"]
        assert data["app_id"] == "6287487"
        assert data["version"] == "1"
        assert "remixsid=sid" in kwargs["headers"]["Cookie"]
        return FakeResponse(
            {
                "type": "okay",
                "data": {
                    "access_token": "vk1.a.fresh",
                    "user_id": 42,
                    "expires": 1_900_000_000,
                },
            },
            set_cookies={"p": "newp"},
        )

    session = FakeSession(handler)

    async def run() -> None:
        result = await fetch_web_token(session, {"remixsid": "sid", "p": "old"})  # type: ignore[arg-type]
        assert result.access_token == "vk1.a.fresh"
        assert result.user_id == 42
        assert result.cookies["p"] == "newp"
        assert result.cookies["remixsid"] == "sid"

    asyncio.run(run())


def test_fetch_web_token_retries_second_host() -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        if "login.vk.ru" in url:
            return FakeResponse({"type": "error", "error_info": "unauthorized"})
        return FakeResponse(
            {
                "type": "okay",
                "data": {"access_token": "vk1.a.from-com", "user_id": 1, "expires": 1_900_000_000},
            }
        )

    session = FakeSession(handler)

    async def run() -> None:
        result = await fetch_web_token(session, {"remixsid": "sid"})  # type: ignore[arg-type]
        assert result.access_token == "vk1.a.from-com"

    asyncio.run(run())
    assert any("login.vk.ru" in url for url, _ in session.calls)
    assert any("login.vk.com" in url for url, _ in session.calls)


def test_fetch_web_token_unauthorized() -> None:
    def handler(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        return FakeResponse({"type": "error", "error_info": "unauthorized"})

    session = FakeSession(handler)

    async def run() -> None:
        try:
            await fetch_web_token(session, {"remixsid": "dead"})  # type: ignore[arg-type]
        except WebTokenUnauthorized:
            return
        raise AssertionError("expected unauthorized")

    asyncio.run(run())


def test_exchange_skips_app_without_messages() -> None:
    state = {"web": 0}

    def handler(url: str, kwargs: dict[str, Any]) -> FakeResponse:
        if "act=web_token" in url:
            state["web"] += 1
            app_id = kwargs["data"]["app_id"]
            return FakeResponse(
                {
                    "type": "okay",
                    "data": {
                        "access_token": f"tok-{app_id}",
                        "user_id": 7,
                        "expires": 2000,
                    },
                }
            )
        if url.endswith("users.get"):
            return FakeResponse({"response": [{"id": 7, "first_name": "A", "last_name": "B"}]})
        if url.endswith("messages.getLongPollServer"):
            token = kwargs["data"]["access_token"]
            if token == "tok-6287487":
                return FakeResponse(
                    {"error": {"error_code": 15, "error_msg": "Access denied"}}
                )
            return FakeResponse({"response": {"server": "x", "key": "k", "ts": 1}})
        raise AssertionError(url)

    session = FakeSession(handler)

    async def run() -> None:
        web = await exchange_cookies_for_api(session, {"remixsid": "sid"})  # type: ignore[arg-type]
        assert web.access_token.startswith("tok-")
        assert web.access_token != "tok-6287487"
        assert web.users[0]["id"] == 7
        assert web.app_id != 6287487

    asyncio.run(run())
    assert state["web"] >= 2
