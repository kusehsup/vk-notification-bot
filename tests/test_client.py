from __future__ import annotations

import asyncio
from typing import Any

from vk.client import VKAPIError, VKClient
from vk.rate_limit import FloodPolicy, VKFloodController


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeSession:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls = 0

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls += 1
        return FakeResponse(self.payload)


def test_client_trips_limiter_on_flood() -> None:
    session = FakeSession({"error": {"error_code": 9, "error_msg": "Flood control"}})
    limiter = VKFloodController(
        policy=FloodPolicy(min_interval=0, flood_initial=15, jitter=0),
    )
    client = VKClient("secret-token", session, limiter=limiter)  # type: ignore[arg-type]

    async def run() -> None:
        try:
            await client.users_get()
        except VKAPIError as e:
            assert e.is_flood
        else:
            raise AssertionError("expected VKAPIError")

    asyncio.run(run())
    assert session.calls == 1
    assert limiter.is_cooling("secret-token")
    assert limiter.remaining("secret-token") >= 14


def test_client_success_clears_streak() -> None:
    session = FakeSession({"response": [{"id": 1}]})
    limiter = VKFloodController(
        policy=FloodPolicy(min_interval=0, flood_initial=15, jitter=0),
    )
    limiter.trip("secret-token", 9)
    # expire cooldown so the call actually goes out
    limiter._token_until.clear()  # noqa: SLF001
    client = VKClient("secret-token", session, limiter=limiter)  # type: ignore[arg-type]

    async def run() -> None:
        result = await client.users_get()
        assert result == [{"id": 1}]

    asyncio.run(run())
    assert not limiter.is_cooling("secret-token")
