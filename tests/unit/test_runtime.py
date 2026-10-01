import pytest

from tradingagent.broker.auth import GrowwAuth
from tradingagent.core.events import EventBus
from tradingagent.core.modes import DayState
from tradingagent.orchestrator.runtime import Runtime


@pytest.fixture
def make_rt(cfg, clock, tmp_path):
    def _make(bus=None):
        return Runtime(cfg, clock, bus or EventBus(), GrowwAuth(clock, env={}), tmp_path / "runtime")
    return _make


def test_halt_is_sticky_and_survives_restart(make_rt):
    rt = make_rt()
    rt.halt("test", source="unit")
    assert rt.halted and rt.day_state is DayState.HALTED
    with pytest.raises(RuntimeError, match="sticky"):
        rt.transition(DayState.ACTIVE_HUNT, "try")
    rt2 = make_rt()  # new process
    assert rt2.halted and rt2.day_state is DayState.HALTED


def test_resume_requires_reason_and_returns_to_boot(make_rt):
    rt = make_rt()
    rt.halt("test", source="unit")
    with pytest.raises(ValueError):
        rt.resume("   ", source="unit")
    rt.resume("checked positions, all flat", source="unit")
    assert not rt.halted and rt.day_state is DayState.BOOT


def test_events_published(make_rt):
    bus = EventBus()
    seen = []
    bus.subscribe(seen.append)
    rt = make_rt(bus)
    rt.transition(DayState.PRE_MARKET, "boot ok")
    rt.halt("x", source="unit")
    assert [e.type for e in seen] == ["STATE_TRANSITION", "HALT"]


async def test_connect_broker_reports_failure(make_rt):
    broker = await make_rt().connect_broker(source="unit")
    assert broker["connected"] is False and "GROWW_ACCESS_TOKEN" in broker["error"]
