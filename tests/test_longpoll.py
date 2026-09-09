from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from vk.client import VKAPIError, VKClient
from vk.longpoll import LongPollWorker


def test_short_reconnect_does_not_hammer_get_server() -> None:
    client = MagicMock(spec=VKClient)
    client.token = "tok"
    client.limiter = None
    client.messages_get_long_poll_server = AsyncMock(
        side_effect=VKAPIError(9, "Flood control"),
    )
    worker = LongPollWorker(client, MagicMock(), AsyncMock(), vk_user_id=1)

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        if len(slept) >= 2:
            raise asyncio.CancelledError()

    async def run() -> None:
        with patch("asyncio.sleep", fake_sleep):
            try:
                await worker.run()
            except asyncio.CancelledError:
                pass

    asyncio.run(run())
    assert client.messages_get_long_poll_server.await_count >= 2
    assert slept[0] >= 5
    assert slept[1] >= 10
