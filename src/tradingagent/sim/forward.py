"""Forward paper test of FROZEN candidate rules (docs/reports/2026-10-01_entry_study.md).

Only trading days strictly after FREEZE_DATE count — data no study has seen. Rules must not change while
being forward-tested; a changed rule gets a new name and starts its own count.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import FILTERS, run_entry_study
from tradingagent.sim.exit_study import metrics

FREEZE_DATE = date(2026, 10, 1)


@dataclass(frozen=True)
class FrozenRule:
    name: str
    entry: str
    exit: str
    filter: str
    backtest_n: int          # from study #2 (Dec 2023 – Sep 2026), for comparison only
    backtest_net_inr: float
    backtest_ex_top5_inr: float


FORWARD_RULES = (
    FrozenRule("F1_orb15_narrow_noprog", "orb15", "no_progress_30m", "narrow_or", 269, 182.6, -109.0),
    FrozenRule("F2_orb15_narrow_hold", "orb15", "hold_1510", "narrow_or", 269, 143.0, -178.3),
    FrozenRule("F3_twap_lowvol_hold", "twap_pullback", "hold_1510", "low_vol", 316, 285.0, -13.1),
)


@dataclass(frozen=True)
class FrozenRuleV2:
    """Frozen after the setup-logic study (2026-10-01 afternoon). Uses the stop-study exits and the F4 filter.
    Counted separately from the morning rules (F1–F3)."""
    name: str
    setup: str               # S1 | S2 in logic_study.SETUPS (S1: opposite-side + −50% stop; S2: hold + −30%)
    open_outside_only: bool
    backtest_n: int
    backtest_net_inr: float
    backtest_ex_top5_inr: float


# Backtest benchmarks = config/setups.yaml `evidence` (re-run 2026-10-02 after the G2 warm-up fix; the
# original 133 trades / +862 for G2 came from that bug). Rules unchanged — only the comparison numbers.
FORWARD_RULES_V2 = (
    FrozenRuleV2("G1_S1_open_outside", "S1", True, 117, 833.1, 137.0),
    FrozenRuleV2("G2_S2_open_outside", "S2", True, 114, 300.4, -211.7),
)


def select(trades: pd.DataFrame, rule: FrozenRule) -> pd.DataFrame:
    if trades.empty:
        return trades
    t = trades[(trades["entry"] == rule.entry) & (trades["exit"] == rule.exit)]
    return t[FILTERS[rule.filter](t).fillna(False).astype(bool)].assign(rule=rule.name)


def select_v2(trades: pd.DataFrame, rule: FrozenRuleV2) -> pd.DataFrame:
    if trades.empty:
        return trades
    t = trades[trades["setup"] == rule.setup]
    if rule.open_outside_only:
        t = t[t["F4_open_outside"] == True]  # noqa: E712
    return t.assign(rule=rule.name)


def run_forward(store: MarketStore, costs: CostModel) -> tuple[pd.DataFrame, pd.DataFrame]:
    from tradingagent.sim.logic_study import build_trades

    start = FREEZE_DATE + timedelta(days=1)
    entries = sorted({r.entry for r in FORWARD_RULES})
    trades, _ = run_entry_study(store, costs, start=start, entries=entries)
    v2 = build_trades(store, costs, start=start)
    parts = ([select(trades, r) for r in FORWARD_RULES] if not trades.empty else []) + \
        ([select_v2(v2, r) for r in FORWARD_RULES_V2] if not v2.empty else [])
    ledger = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    rows = []
    for r in (*FORWARD_RULES, *FORWARD_RULES_V2):
        sub = ledger[ledger["rule"] == r.name] if not ledger.empty else ledger
        m = metrics(sub) if len(sub) else {"n": 0}
        rows.append({"rule": r.name, "forward_n": m["n"], "forward_net_inr": m.get("exp_inr"),
                     "forward_total_inr": m.get("total_inr"), "forward_win": m.get("win_rate"),
                     "backtest_n": r.backtest_n, "backtest_net_inr": r.backtest_net_inr,
                     "backtest_ex_top5": r.backtest_ex_top5_inr})
    return ledger, pd.DataFrame(rows)
