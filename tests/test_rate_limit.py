from __future__ import annotations

import asyncio
from unittest.mock import patch

from vk.rate_limit import FloodPolicy, VKFloodController


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _controller(**kwargs) -> tuple[VKFloodController, FakeClock]:
    clock = FakeClock()
    policy = FloodPolicy(
        min_interval=kwargs.pop("min_interval", 0.5),
        flood_initial=kwargs.pop("flood_initial", 10.0),
        flood_max=kwargs.pop("flood_max", 80.0),
        rate_limit_initial=kwargs.pop("rate_limit_initial", 5.0),
        rate_limit_max=kwargs.pop("rate_limit_max", 20.0),
        global_trip_threshold=kwargs.pop("global_trip_threshold", 3),
        global_trip_window=kwargs.pop("global_trip_window", 30.0),
        global_trip_seconds=kwargs.pop("global_trip_seconds", 50.0),
        jitter=0.0,
    )
    return VKFloodController(policy=policy, clock=clock), clock


def test_flood_error_9_sets_cooldown() -> None:
    ctl, clock = _controller()
    wait = ctl.trip("token-aaaa", 9)
    assert wait == 10.0
    assert ctl.is_cooling("token-aaaa")
    assert ctl.remaining("token-aaaa") == 10.0
    clock.advance(9.9)
    assert ctl.is_cooling("token-aaaa")
    clock.advance(0.2)
    assert not ctl.is_cooling("token-aaaa")


def test_flood_backoff_doubles_until_cap() -> None:
    ctl, _ = _controller(flood_initial=10.0, flood_max=80.0)
    assert ctl.trip("tok", 9) == 10.0
    assert ctl.trip("tok", 9) == 20.0
    assert ctl.trip("tok", 9) == 40.0
    assert ctl.trip("tok", 9) == 80.0
    assert ctl.trip("tok", 9) == 80.0


def test_rate_limit_uses_shorter_window() -> None:
    ctl, clock = _controller()
    wait = ctl.trip("tok", 29)
    assert wait == 5.0
    clock.advance(5.0)
    assert not ctl.is_cooling("tok")


def test_retry_after_overrides_when_longer() -> None:
    ctl, _ = _controller(flood_initial=10.0, flood_max=80.0)
    wait = ctl.trip("tok", 9, retry_after=25)
    assert wait == 25.0


def test_success_resets_streak() -> None:
    ctl, clock = _controller()
    ctl.trip("tok", 9)
    clock.advance(10)
    ctl.note_success("tok")
    assert ctl.trip("tok", 9) == 10.0


def test_three_tokens_trip_global_pause() -> None:
    ctl, clock = _controller(global_trip_threshold=3, global_trip_seconds=50.0)
    ctl.trip("token-aaa", 9)
    ctl.trip("token-bbb", 9)
    assert ctl.global_remaining() == 0.0
    ctl.trip("token-ccc", 9)
    assert ctl.global_remaining() == 50.0
    assert ctl.is_cooling("token-ddd")  # even unseen token
    clock.advance(49)
    assert ctl.is_cooling("token-ddd")
    clock.advance(2)
    assert not ctl.is_cooling("token-ddd")


def test_wait_turn_sleeps_cooldown_then_interval() -> None:
    ctl, clock = _controller(min_interval=0.5, flood_initial=3.0)
    ctl.trip("tok", 9)
    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        clock.advance(delay)

    async def run() -> None:
        with patch("asyncio.sleep", fake_sleep):
            await ctl.wait_turn("tok")
            await ctl.wait_turn("tok")

    asyncio.run(run())
    assert slept[0] == 3.0
    assert slept[1] == 0.5
