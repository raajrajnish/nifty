from datetime import datetime, timedelta

import pytest

from tradingagent.core.clock import IST, SimClock
from tradingagent.core.events import EventBus, redact


def test_simclock_requires_tz():
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 1, 9, 15))


def test_simclock_never_goes_backwards(clock):
    clock.advance(timedelta(minutes=5))
    assert clock.now() == datetime(2026, 9, 29, 8, 5, tzinfo=IST)
    with pytest.raises(ValueError):
        clock.advance(timedelta(seconds=-1))


async def test_simclock_sleep_until_jumps(clock):
    target = datetime(2026, 9, 29, 9, 15, tzinfo=IST)
    await clock.sleep_until(target)
    assert clock.now() == target


def test_redact_nested():
    out = redact({"api_key": "k", "nested": {"GROWW_API_SECRET": "s", "ok": 1}, "list": [{"token": "t"}]})
    assert out == {"api_key": "***", "nested": {"GROWW_API_SECRET": "***", "ok": 1}, "list": [{"token": "***"}]}


def test_bus_sequence_and_redaction(clock):
    bus = EventBus()
    seen = []
    bus.subscribe(seen.append)
    bus.publish("A", clock.now(), {"secret": "x"})
    bus.publish("B", clock.now())
    assert [e.seq for e in seen] == [1, 2]
    assert seen[0].payload == {"secret": "***"}


def test_slow_queue_drops_oldest_not_blocks(clock):
    bus = EventBus()
    q = bus.open_queue(maxsize=2)
    for i in range(5):
        bus.publish("E", clock.now(), {"i": i})
    assert [q.get_nowait().payload["i"] for _ in range(2)] == [3, 4]
