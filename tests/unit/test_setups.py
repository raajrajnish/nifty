"""Guard: config/setups.yaml, playbook/03_setups.md and the code that produced the evidence must agree."""

import inspect
from datetime import time
from pathlib import Path

import yaml

from tradingagent.sim import entry_study, exit_study, followthrough_study, forward

REPO = Path(__file__).resolve().parents[2]
S = yaml.safe_load((REPO / "config" / "setups.yaml").read_text(encoding="utf-8"))


def test_stops_match_code():
    assert followthrough_study.SETUPS["S1"][3] == S["setups"]["G1"]["stop_premium_pct"] / 100
    assert followthrough_study.SETUPS["S2"][3] == S["setups"]["G2"]["stop_premium_pct"] / 100


def test_invalidation_rules_match_code():
    from tradingagent.sim.exit_study import rule_none
    from tradingagent.sim.stop_study import rule_or_opposite

    assert followthrough_study.SETUPS["S1"][2] is rule_or_opposite
    assert followthrough_study.SETUPS["S2"][2] is rule_none
    assert S["setups"]["G1"]["invalidation"] == "five_min_close_beyond_opposite_or_side"
    assert S["setups"]["G2"]["invalidation"] == "none"


def test_time_windows_match_code():
    assert time.fromisoformat(S["common"]["time_exit"]) == exit_study.EOD_EXIT
    assert time.fromisoformat(S["setups"]["G1"]["trigger"]["last_bar_end"]) == entry_study.SIGNAL_END
    assert time.fromisoformat(S["setups"]["G1"]["trigger"]["first_bar_end_after"]) == exit_study.SIGNAL_START
    assert S["common"]["strike_step"] == exit_study.STEP


def test_day_filter_parameters_match_code():
    src = inspect.getsource(entry_study.day_features)
    assert "rolling(20, min_periods=10)" in src            # G1 narrow OR: 20-day median, ≥10 days
    assert "rolling(14).mean()" in src                       # G2 ATR14
    assert "rolling(120, min_periods=40)" in src             # G2 120-day median, ≥40 days
    g1 = S["setups"]["G1"]["day_filter"]
    g2 = S["setups"]["G2"]["day_filter"]
    assert (g1["narrow_or_lookback_days"], g1["narrow_or_min_days"]) == (20, 10)
    assert (g2["atr_days"], g2["atr_median_lookback_days"], g2["atr_median_min_days"]) == (14, 120, 40)


def test_g2_trigger_parameters_match_code():
    src = inspect.getsource(entry_study.e_twap_pullback)
    t = S["setups"]["G2"]["trigger"]
    tol = t["touch_tolerance"]
    assert f"{1 + tol:.4f}" in src and f"{1 - tol:.4f}" in src  # 1.0005 (CE) and 0.9995 (PE)
    assert f"minutes={t['slope_lookback_minutes']}" in src
    assert "time(10, 0)" in src and t["first_bar_end"] == "10:00"


def test_forward_rules_track_the_playbook_setups():
    names = {r.name for r in forward.FORWARD_RULES_V2}
    assert names == {"G1_S1_open_outside", "G2_S2_open_outside"}
    assert all(r.open_outside_only for r in forward.FORWARD_RULES_V2) and S["common"]["require_open_outside_prev_range"]


def test_forward_benchmarks_match_setups_evidence():
    """The forward summary compares live results with these numbers; they must be the CORRECTED evidence
    (G2 was 133 trades / +862 before the warm-up fix, now 114 / +300)."""
    by_setup = {r.setup: r for r in forward.FORWARD_RULES_V2}
    for g, s in (("G1", "S1"), ("G2", "S2")):
        ev, r = S["setups"][g]["evidence"], by_setup[s]
        got = (r.backtest_n, r.backtest_net_inr, r.backtest_ex_top5_inr)
        assert got == (ev["trades"], ev["net_per_trade_inr"], ev["ex_top5_inr"]), g


def test_playbook_mentions_every_setup_and_parameter():
    pb = (REPO / "playbook" / "03_setups.md").read_text(encoding="utf-8")
    for needle in ("G1", "G2", "−50%", "−30%", "15:10", "13:30", "TWAP × 1.0005", "previous 20 trading days",
                   "previous 120 days", "FORWARD PAPER ONLY", "HYPERCARE", "REJECTED", "% of the premium paid",
                   "% of current equity"):
        assert needle in pb, needle
