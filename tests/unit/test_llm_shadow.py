import json
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from tradingagent.agent.shadow import Ledger, ShadowConfig, ShadowRunner, cost_inr, decide

DAY = date(2026, 10, 5)
CFG = ShadowConfig(prices_usd_per_mtok={"claude-sonnet-5-5": {"input": 2.0, "output": 10.0}}, usd_inr=88.0)
NOW = lambda: datetime(2026, 10, 5, 9, 40)  # noqa: E731


def usage(i=10_000, o=1_000, s=2):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0, cache_read_input_tokens=0,
              server_tool_use=NS(web_search_requests=s))


def resp(blocks, stop="end_turn", u=None):
    return NS(content=blocks, stop_reason=stop, usage=u or usage(), stop_details=None)


SEARCH = NS(type="web_search_tool_result", content=[NS(type="web_search_result", url="https://x.example/a", title="A")])
ANSWER = NS(type="text", text=json.dumps({"decision": "SKIP", "confidence": 0.7, "reasons": ["RBI at 10:00"],
                                          "key_news": ["policy day"]}))


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "shadow.jsonl")


@pytest.fixture
def key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")


def test_cost_by_hand():
    # 10k in × $2/M + 1k out × $10/M + 2 searches × $0.01 = $0.05 → ₹4.40
    assert cost_inr(CFG, {"input_tokens": 10_000, "output_tokens": 1_000, "web_search_requests": 2}) == 4.4


def test_no_key_records_no_decision_without_calling(ledger, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    fc = FakeClient([])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, lambda: fc)
    assert r["decision"] == "NO_DECISION" and "ANTHROPIC_API_KEY" in r["error"] and fc.calls == []
    assert ledger.rows()[0]["called"] is False


def test_budget_cap_blocks_the_call(ledger, key):
    ledger.append({"day": "2026-10-01", "kind": "signal", "called": True, "cost_inr": 500.0})
    fc = FakeClient([])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, lambda: fc)
    assert r["decision"] == "NO_DECISION" and "monthly cap" in r["error"] and fc.calls == []
    ledger.append({"day": "2026-09-30", "kind": "signal", "called": True, "cost_inr": 999.0})  # other month: ignored
    assert ledger.month_spend_inr(DAY) == 500.0


def test_signal_decision_sources_and_cost_recorded(ledger, key):
    fc = FakeClient([resp([NS(type="server_tool_use"), SEARCH, ANSWER])])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, lambda: fc, {"side": "PE"})
    assert r["decision"] == "SKIP" and r["confidence"] == 0.7 and r["reasons"] == ["RBI at 10:00"]
    assert r["sources"] == [{"url": "https://x.example/a", "title": "A"}] and r["cost_inr"] == 4.4
    kw = fc.calls[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["tools"][0]["type"] == "web_search_20260209"
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["extra_body"] == {"fallbacks": "default"}
    assert ledger.rows()[-1]["side"] == "PE"


def test_pause_turn_is_continued_and_usage_summed(ledger, key):
    fc = FakeClient([resp([NS(type="server_tool_use")], stop="pause_turn"), resp([SEARCH, ANSWER])])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, lambda: fc)
    assert r["decision"] == "SKIP" and len(fc.calls) == 2 and r["usage"]["input_tokens"] == 20_000
    assert fc.calls[1]["messages"][1]["role"] == "assistant"          # paused turn sent back, no extra user text


def test_api_failure_never_raises(ledger, key):
    fc = FakeClient([RuntimeError("boom")])
    r = decide("signal", DAY, "G2", "q", CFG, ledger, NOW, lambda: fc)
    assert r["decision"] == "NO_DECISION" and "boom" in r["error"]
    bad = FakeClient([resp([NS(type="text", text="not json")])])
    assert decide("signal", DAY, "G2", "q", CFG, ledger, NOW, lambda: bad)["error"].startswith("bad JSON")


def test_runner_asks_once_per_day_and_per_trade(ledger, key):
    answers = [resp([SEARCH, NS(type="text", text=json.dumps(
        {"day_view": "NORMAL", "confidence": 0.8, "reasons": ["quiet"], "key_news": []}))]),
        resp([SEARCH, ANSWER])]
    fc = FakeClient(answers)
    run = ShadowRunner(CFG, ledger, NOW, lambda: fc, log=lambda m: None, start_thread=lambda fn: fn())
    trade = {"side": "PE", "strike": 24500, "entry_ts": "2026-10-05T09:40:00", "entry_px": 120.0, "stop_px": 60.0}
    state = {"day": str(DAY), "as_of": "2026-10-05T09:40:00", "expiry": "2026-10-06",
             "market": {"index": 24480.0}, "setups": {"G1": {"trade": trade, "checks": {}, "summary": "s"},
                                                       "G2": {"trade": None, "checks": {}, "summary": "s"}}}
    eng = NS(day=DAY, state=lambda: state)
    run.tick(eng)
    run.tick(eng)                                                      # nothing new
    kinds = [(r["kind"], r["setup"], r["decision"]) for r in ledger.rows()]
    assert kinds == [("morning", None, "NORMAL"), ("signal", "G1", "SKIP")] and len(fc.calls) == 2
    fresh = ShadowRunner(CFG, ledger, NOW, lambda: fc, log=lambda m: None, start_thread=lambda fn: fn())
    fresh.tick(eng)                                                    # restart same day: ledger prevents repeats
    assert len(fc.calls) == 2
