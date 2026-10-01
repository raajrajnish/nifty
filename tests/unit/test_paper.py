import json
from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from tradingagent.paper.engine import MinuteBars, PaperEngine
from tradingagent.paper.runner import Tail, append_ledger
from tradingagent.sim.costs import CostModel

DAY = date(2026, 3, 18)          # a Wednesday
EXP = date(2026, 3, 24)


def history(days=150, rng_pts=120.0, last_hi=22800.0, last_lo=22700.0):
    """Synthetic past 1-min history: wide-ish opening ranges, yesterday's range = last_lo..last_hi."""
    rows, d = [], DAY - timedelta(days=1)
    n = 0
    while n < days:
        if d.weekday() < 5:
            lo = last_lo if n == 0 else 22000.0
            hi = last_hi if n == 0 else 22000.0 + rng_pts
            for k in range(375):
                px = lo + (hi - lo) * ((k % 30) / 29)
                rows.append({"ts": datetime(d.year, d.month, d.day, 9, 15) + timedelta(minutes=k),
                             "open": px, "high": px, "low": px, "close": px})
            n += 1
        d -= timedelta(days=1)
    return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)


@pytest.fixture
def engine(cfg):
    e = PaperEngine(DAY, history(), pd.DataFrame(columns=["ts", "close"]), EXP, CostModel(cfg.costs))
    e.symbols = {(22900, "CE"): "NIFTY26M2422900CE", (22900, "PE"): "NIFTY26M2422900PE"}
    return e


def run(e, index_path, quotes=None, start=None):
    """index_path: one price per minute from 09:15; quotes: {minute_index: (symbol, bid, ask)}."""
    t0 = start or datetime(DAY.year, DAY.month, DAY.day, 9, 15, 5)
    for k, px in enumerate(index_path):
        ts = t0 + timedelta(minutes=k)
        if quotes and k in quotes:
            sym, bid, ask = quotes[k]
            e.on_quote(ts, sym, bid, ask, (bid + ask) / 2)
        e.on_ltp(ts, px, {})


def test_minute_bars_complete_on_next_minute():
    b = MinuteBars()
    assert b.add(datetime(2026, 3, 18, 9, 15, 5), 100) is None
    b.add(datetime(2026, 3, 18, 9, 15, 30), 103)
    done = b.add(datetime(2026, 3, 18, 9, 16, 1), 101)
    assert done["high"] == 103 and done["close"] == 103 and done["ts"].minute == 15


def test_open_inside_yesterday_range_means_not_today(engine):
    run(engine, [22750.0] * 5)  # opens inside 22700–22800
    assert engine.s["G1"].status == "NOT_TODAY" and engine.s["G2"].status == "NOT_TODAY"
    assert engine.s["G1"].checks["opened outside yesterday's range"] is False
    assert engine.s["G1"].waiting_for == ""  # nothing to wait for once ruled out


def test_chart_bars_show_ist_wall_clock_on_any_machine(engine):
    run(engine, [22750.0] * 3)
    first = engine.market()["bars"][0][0]
    assert datetime.fromtimestamp(first, tz=UTC).strftime("%H:%M") == "09:15"


def test_g1_full_trade_lifecycle_with_real_bid_ask(engine):
    # opens above yesterday's high (outside), narrow 15-min range 22880–22890, breaks up at 09:35, holds
    path = [22880.0 + (k % 2) * 10 for k in range(15)] + [22895.0] * 5 + [22920.0] * 400
    q = {k: ("NIFTY26M2422900CE", 99.5 + k * 0.1, 100.5 + k * 0.1) for k in range(0, 420)}
    run(engine, path, q)
    g1 = engine.s["G1"]
    assert g1.checks["opened outside yesterday's range"] is True
    assert g1.checks["narrow opening range (< 20-day median)"] is True
    assert g1.status == "DONE" and g1.trade["side"] == "CE" and g1.trade["strike"] == 22900
    assert g1.trade["entry_ts"][11:16] == "09:35"                  # same minute as the backtest rule
    assert g1.trade["entry_price_source"] == "quote"                # filled at the recorded ASK
    assert g1.trade["reason"] == "EOD_1510" and g1.trade["net_inr"] > 0
    # everything is also expressed as % of premium paid and % of equity (default ₹2,00,000)
    assert g1.trade["stop_pct_of_premium"] == 50.0
    assert g1.trade["risk_pct_of_equity"] == pytest.approx(g1.trade["risk_inr"] / 200000 * 100, abs=0.01)
    assert g1.trade["net_pct_of_equity"] == pytest.approx(g1.trade["net_inr"] / 200000 * 100, abs=0.01)
    assert g1.trade["net_pct_of_premium"] == pytest.approx(
        g1.trade["net_inr"] / g1.trade["premium_paid_inr"] * 100, abs=0.1)
    # the same synthetic day is also calm + open-outside with a rising TWAP → G2 trades too (from 10:00)
    assert sorted(t["setup"] for t in engine.closed) == ["G1", "G2"]
    g2 = engine.s["G2"].trade
    assert g2["entry_ts"][11:16] >= "10:00" and g2["side"] == "CE"


def test_stop_hits_on_bid(engine):
    path = [22880.0 + (k % 2) * 10 for k in range(15)] + [22895.0] * 5 + [22920.0] * 60
    q = {k: ("NIFTY26M2422900CE", 99.5, 100.5) for k in range(0, 25)}
    q.update({k: ("NIFTY26M2422900CE", 40.0, 41.0) for k in range(25, 80)})  # premium collapses
    run(engine, path, q)
    assert engine.s["G1"].trade["reason"] == "STOP"


def test_late_recording_start_skips_the_day(engine):
    run(engine, [22950.0] * 5, start=datetime(DAY.year, DAY.month, DAY.day, 9, 22, 5))
    assert engine.s["G1"].status == "SKIPPED" and "started late" in engine.s["G1"].log[-1]


def test_expiry_day_is_skipped(cfg):
    e = PaperEngine(EXP, history(), pd.DataFrame(columns=["ts", "close"]), EXP, CostModel(cfg.costs))
    assert e.s["G1"].status == "SKIPPED" and e.s["G2"].status == "SKIPPED"


def test_tail_reads_only_complete_lines(tmp_path):
    p = tmp_path / "ltp.jsonl"
    p.write_text(json.dumps({"recv_ts": "2026-03-18T09:15:05", "index": {}}) + "\n{\"recv_ts\": \"2026-03",
                 encoding="utf-8")
    t = Tail(tmp_path)
    assert len(t.read()) == 1
    with p.open("a", encoding="utf-8") as f:
        f.write("-18T09:15:07\", \"index\": {}}\n")
    assert len(t.read()) == 1  # the half line is picked up once it is complete


def test_ledger_is_idempotent(tmp_path):
    led = tmp_path / "l.csv"
    t = {"day": "2026-03-18", "setup": "G1", "net_inr": 100}
    append_ledger(led, [t])
    append_ledger(led, [t])
    assert led.read_text(encoding="utf-8").count("2026-03-18") == 1
