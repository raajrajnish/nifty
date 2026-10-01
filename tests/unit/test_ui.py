import json

import pytest
from fastapi.testclient import TestClient

from tradingagent.broker.auth import GrowwAuth
from tradingagent.core.events import EventBus
from tradingagent.orchestrator.runtime import Runtime
from tradingagent.ui.app import create_app
from tradingagent.ui.auth import SessionStore, set_passphrase

PASS = "correct horse battery"
ENV = {"GROWW_API_KEY": "KEY-abc123", "GROWW_API_SECRET": "SECRET-xyz789"}


def _make_client(cfg, clock, tmp_path, require_login: bool):
    cfg = cfg.model_copy(update={"ui": cfg.ui.model_copy(update={"require_login": require_login})})
    auth = GrowwAuth(clock, env=ENV, fetcher=lambda k, s: "TOKEN-1", verifier=lambda t: None)
    rt = Runtime(cfg, clock, EventBus(), auth, tmp_path / "runtime")
    f = tmp_path / "runtime" / "ui_auth.json"
    set_passphrase(f, PASS)
    return rt, TestClient(create_app(rt, SessionStore(f, 12)))


@pytest.fixture
def rt_client(cfg, clock, tmp_path):
    return _make_client(cfg, clock, tmp_path, require_login=True)


@pytest.fixture
def rt(rt_client):
    return rt_client[0]


@pytest.fixture
def client(rt_client):
    return rt_client[1]


@pytest.fixture
def dev_client(cfg, clock, tmp_path):
    return _make_client(cfg, clock, tmp_path, require_login=False)[1]


def _csrf(html: str) -> str:
    return html.split('name="csrf-token" content="')[1].split('"')[0]


def test_dev_mode_opens_dashboard_without_passphrase(dev_client):
    r = dev_client.get("/")
    assert r.status_code == 200 and "login off" in r.text
    assert dev_client.get("/api/state").status_code == 200
    assert dev_client.get("/login", follow_redirects=False).headers["location"] == "/"


def test_dev_mode_still_enforces_csrf_and_origin(dev_client):
    csrf = _csrf(dev_client.get("/").text)
    assert dev_client.post("/api/kill", json={"confirm": "KILL"}).status_code == 403
    r = dev_client.post("/api/kill", json={"confirm": "KILL"},
                        headers={"X-CSRF-Token": csrf, "Origin": "http://evil.example"})
    assert r.status_code == 403
    assert dev_client.get("/", headers={"host": "evil.example:8750"}).status_code == 400


def login(client) -> str:
    assert client.post("/login", json={"passphrase": PASS}).status_code == 200
    html = client.get("/").text
    return html.split('name="csrf-token" content="')[1].split('"')[0]


def test_dashboard_redirects_to_login(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_api_requires_login(client):
    assert client.get("/api/state").status_code == 401


def test_wrong_passphrase_and_lockout(client):
    for _ in range(5):
        assert client.post("/login", json={"passphrase": "nope-nope-nope"}).status_code == 401
    assert client.post("/login", json={"passphrase": PASS}).status_code == 401  # locked out


def test_post_requires_csrf(client):
    login(client)
    assert client.post("/api/kill", json={"confirm": "KILL"}).status_code == 403
    assert client.post("/api/kill", json={"confirm": "KILL"}, headers={"X-CSRF-Token": "bad"}).status_code == 403


def test_kill_needs_typed_confirmation_then_halts(client, rt):
    csrf = login(client)
    h = {"X-CSRF-Token": csrf}
    assert client.post("/api/kill", json={"confirm": "kill"}, headers=h).status_code == 400
    assert not rt.halted
    r = client.post("/api/kill", json={"confirm": "KILL", "reason": "test"}, headers=h)
    assert r.status_code == 200 and r.json()["halted"] is True
    assert rt.halted


def test_resume_needs_reason(client, rt):
    csrf = login(client)
    h = {"X-CSRF-Token": csrf}
    client.post("/api/kill", json={"confirm": "KILL"}, headers=h)
    assert client.post("/api/resume", json={"reason": ""}, headers=h).status_code == 422
    assert client.post("/api/resume", json={"reason": "all flat, checked"}, headers=h).json()["halted"] is False


def test_connect_groww_never_leaks_secrets(client):
    csrf = login(client)
    r = client.post("/api/auth/groww", json={}, headers={"X-CSRF-Token": csrf})
    assert r.status_code == 200 and r.json()["connected"] is True
    body = r.text + client.get("/api/state").text + client.get("/api/events").text
    for s in ("KEY-abc123", "SECRET-xyz789", "TOKEN-1"):
        assert s not in body


def test_paper_endpoint_reads_engine_state_and_ledger(client, rt, tmp_path, clock):
    login(client)
    r = client.get("/api/paper").json()
    assert r["state"] is None and r["engine_running"] is False and r["trades"] == []
    (tmp_path / "runtime" / "paper_state.json").write_text(json.dumps({
        "day": clock.now().date().isoformat(), "engine_heartbeat": clock.now().replace(tzinfo=None).isoformat(),
        "setups": {"G1": {"status": "WATCHING"}, "G2": {"status": "NOT_TODAY"}}}), encoding="utf-8")
    led = tmp_path / "data" / "paper"
    led.mkdir(parents=True)
    (led / "live_trades.csv").write_text("day,setup,net_inr\n2026-09-28,G1,500\n2026-09-29,G1,-200\n",
                                         encoding="utf-8")
    r = client.get("/api/paper").json()
    assert r["engine_running"] is True and r["state"]["setups"]["G1"]["status"] == "WATCHING"
    assert r["totals"]["G1"]["trades"] == 2 and r["totals"]["G1"]["net_inr"] == 300.0
    assert r["totals"]["G1"]["net_pct_of_start_capital"] == 0.15
    risk = client.get("/api/state").json()["risk"]
    assert risk["equity"] == 200300.0 and risk["basis"] == "equity"
    assert risk["per_trade_risk_inr"] == round(200300 * 0.01)  # 1% of CURRENT equity, not of ₹2,00,000


def test_overview_combines_market_account_setups_and_days(client, rt, tmp_path, clock):
    login(client)
    o = client.get("/api/overview").json()
    assert set(o) >= {"system", "market", "account", "paper", "setups", "trades", "days"}
    assert o["account"]["equity"] == 200000 and o["account"]["sizing"]["G1"]["lots"] is None  # no price yet
    (tmp_path / "runtime" / "paper_state.json").write_text(json.dumps({
        "day": clock.now().date().isoformat(), "engine_heartbeat": clock.now().replace(tzinfo=None).isoformat(),
        "as_of": "x", "setups": {"G1": {"status": "IN_TRADE", "trade": {"pnl_inr": 650.0}}},
        "market": {"index": 22610.0, "lot_size": 65, "atm_strike": 22600,
                   "atm": {"CE": {"ask": 140.0}, "PE": {"ask": 120.0}}}}), encoding="utf-8")
    led = tmp_path / "data" / "paper"
    led.mkdir(parents=True)
    (led / "live_trades.csv").write_text("day,setup,net_inr\n2026-09-28,G1,1000\n2026-09-28,G2,-400\n",
                                         encoding="utf-8")
    o = client.get("/api/overview").json()
    a = o["account"]
    assert a["equity"] == 200600 and a["open_mtm_inr"] == 650.0
    # sizing at ATM premium ₹140, lot 65, 1% risk (₹2,006): G1 risks 140×0.5×65 = ₹4,550 → 0 lots
    assert a["sizing"]["G1"]["lots"] == 0 and a["sizing"]["G1"]["risk_per_lot_inr"] == 4550
    assert o["days"][0] == {"day": "2026-09-28", "trades": 2, "wins": 1, "net_inr": 600.0, "setups": ["G1", "G2"],
                            "net_pct": 0.3, "equity_after": 200600.0}


def test_lots_allowed_respects_risk_outlay_and_max_lots(rt):
    assert rt.lots_allowed(140.0, 0.30, 65, 600000)["lots"] == 2          # 1% = ₹6,000 / ₹2,730 → 2 (also max_lots)
    assert rt.lots_allowed(140.0, 0.30, 65, 300000)["lots"] == 1          # ₹3,000 / ₹2,730 → 1
    assert rt.lots_allowed(400.0, 0.05, 65, 200000)["lots"] == 1          # outlay cap 20% = ₹40,000 / ₹26,000 → 1


def test_bad_host_rejected(client):
    assert client.get("/healthz", headers={"host": "evil.example:8750"}).status_code == 400


def test_cross_origin_post_rejected(client):
    csrf = login(client)
    r = client.post("/api/kill", json={"confirm": "KILL"},
                    headers={"X-CSRF-Token": csrf, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_ui_has_no_config_or_order_write_endpoints(client):
    paths = {r.path for r in client.app.routes}
    assert not any(k in p for p in paths for k in ("config", "order", "stage", "stop", "qty", "playbook"))
