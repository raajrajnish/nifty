import json
import subprocess
from datetime import date, datetime
from types import SimpleNamespace as NS

import pytest

from tradingagent.agent import shadow
from tradingagent.agent.shadow import Ledger, ShadowConfig, ShadowRunner, claude_code_backend, decide

DAY = date(2026, 10, 5)
CFG = ShadowConfig(claude_path="", usd_inr=88.0)
NOW = lambda: datetime(2026, 10, 5, 9, 40)  # noqa: E731
SIGNAL = {"decision": "SKIP", "confidence": 0.7, "reason_tags": ["SCHEDULED_EVENT_TODAY"], "news_for_trade": -0.2,
          "event_risk": 0.8, "global_for_trade": 0.1, "volatility_view": 0.3, "reasons": ["RBI at 10:00"],
          "key_news": ["policy day"], "sources": ["https://x.example/a"]}
MORNING = {"day_view": "NORMAL", "confidence": 0.8, "reasons": ["quiet"], "key_news": [], "sources": []}


def fake_backend(answers):
    calls = []

    def b(cfg, system, user, schema):
        calls.append((system, user, schema))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    return b, calls


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "shadow.jsonl")


# ---- the Claude Code CLI backend --------------------------------------------------------------------------------
def cli_json(**over):
    j = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.05,
         "duration_ms": 9000, "modelUsage": {"claude-sonnet-5-5": {"webSearchRequests": 0},
                                             "claude-haiku-4-5-20251001": {"webSearchRequests": 2}},
         "result": json.dumps(SIGNAL), "structured_output": SIGNAL}
    return json.dumps(j | over)


def test_cli_backend_parses_output_and_strips_api_keys(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return NS(stdout=cli_json(), stderr="", returncode=0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shadow, "find_claude", lambda cfg: "claude")
    monkeypatch.setattr(shadow, "WORKDIR", tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-value-not-a-key")
    data, sources, usage, err = claude_code_backend(CFG, "sys", "user prompt", {"type": "object"})
    assert err == "" and data["decision"] == "SKIP" and sources == ["https://x.example/a"]
    assert usage["web_search_requests"] == 2 and usage["equiv_cost_usd"] == 0.05
    cmd = seen["cmd"]
    assert cmd[:2] == ["claude", "-p"] and cmd[cmd.index("--tools") + 1] == "WebSearch"
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5" and "--json-schema" in cmd
    assert seen["kw"]["input"] == "user prompt" and "ANTHROPIC_API_KEY" not in seen["kw"]["env"]  # subscription only


@pytest.mark.parametrize("out,expect", [
    (cli_json(is_error=True, subtype="error_during_execution", result="usage limit reached"), "CLI error"),
    (cli_json(structured_output=None), "no structured output"),
    ("not json at all", "bad CLI output"),
])
def test_cli_backend_failures_are_reported_not_raised(monkeypatch, tmp_path, out, expect):
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: NS(stdout=out, stderr="", returncode=1))
    monkeypatch.setattr(shadow, "find_claude", lambda cfg: "claude")
    monkeypatch.setattr(shadow, "WORKDIR", tmp_path)
    data, _, _, err = claude_code_backend(CFG, "s", "u", {})
    assert data is None and err.startswith(expect)


def test_cli_missing_and_timeout(monkeypatch, tmp_path):
    monkeypatch.setattr(shadow, "find_claude", lambda cfg: None)
    assert claude_code_backend(CFG, "s", "u", {})[3].startswith("claude CLI not found")
    monkeypatch.setattr(shadow, "find_claude", lambda cfg: "claude")
    monkeypatch.setattr(shadow, "WORKDIR", tmp_path)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 240)
    monkeypatch.setattr(subprocess, "run", slow)
    assert claude_code_backend(CFG, "s", "u", {})[3].startswith("timeout")


# ---- decide / ledger ---------------------------------------------------------------------------------------------
def test_signal_decision_with_structured_reasons_recorded(ledger):
    b, calls = fake_backend([(dict(SIGNAL), ["https://x.example/a"], {"equiv_cost_usd": 0.05}, "")])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, b, {"side": "PE"})
    assert r["decision"] == "SKIP" and r["reason_tags"] == ["SCHEDULED_EVENT_TODAY"] and r["event_risk"] == 0.8
    assert r["sources_model_reported"] == ["https://x.example/a"] and r["equiv_cost_inr"] == 4.4
    assert r["backend"] == "claude_code" and ledger.rows()[-1]["side"] == "PE"
    assert calls[0][2]["required"][-1] == "sources"                       # the v2 signal schema was sent


def test_daily_call_limit_protects_plan_usage(ledger):
    for _ in range(20):
        ledger.append({"day": str(DAY), "kind": "signal", "called": True})
    b, calls = fake_backend([])
    r = decide("signal", DAY, "G1", "q", CFG, ledger, NOW, b)
    assert r["decision"] == "NO_DECISION" and "daily call limit" in r["error"] and calls == []


def test_backend_error_records_no_decision(ledger):
    b, _ = fake_backend([(None, [], {}, "CLI error: usage limit reached")])
    r = decide("signal", DAY, "G2", "q", CFG, ledger, NOW, b)
    assert r["decision"] == "NO_DECISION" and "usage limit" in r["error"] and ledger.rows()[-1]["called"] is True


def test_runner_asks_once_per_day_and_per_trade(ledger):
    b, calls = fake_backend([(dict(MORNING), [], {}, ""), (dict(SIGNAL), [], {}, "")])
    run = ShadowRunner(CFG, ledger, NOW, b, log=lambda m: None, start_thread=lambda fn: fn())
    trade = {"side": "PE", "strike": 24500, "entry_ts": "2026-10-05T09:40:00", "entry_px": 120.0, "stop_px": 60.0}
    state = {"day": str(DAY), "as_of": "2026-10-05T09:40:00", "expiry": "2026-10-06",
             "market": {"index": 24480.0}, "setups": {"G1": {"trade": trade, "checks": {}, "summary": "s"},
                                                       "G2": {"trade": None, "checks": {}, "summary": "s"}}}
    eng = NS(day=DAY, state=lambda: state)
    run.tick(eng)
    run.tick(eng)
    kinds = [(r["kind"], r["setup"], r["decision"]) for r in ledger.rows()]
    assert kinds == [("morning", None, "NORMAL"), ("signal", "G1", "SKIP")] and len(calls) == 2
    ShadowRunner(CFG, ledger, NOW, b, log=lambda m: None, start_thread=lambda fn: fn()).tick(eng)
    assert len(calls) == 2                                               # restart: the ledger prevents repeats
