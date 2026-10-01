"""Risk study (`tradingagent backtest-risk`): derive loss limits from the setups' own behaviour.

Input: trades from the latest stop study for the chosen setup variants (1 lot each).
Outputs (all ₹, 1 lot per setup, after costs):
  per-setup loss profile · combined daily P&L distribution · daily-loss-cap what-if · losing streaks ·
  Monte-Carlo (day-order reshuffle) drawdown distribution.
Daily cap rule (simulated in time order): a new entry is skipped if REALISED P&L of trades already closed
that day is ≤ −cap. Trades still open at that moment are not counted (we cannot know their result yet).
"""

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SetupChoice:
    name: str
    setup: str
    exit_mode: str
    stop: str


CHOSEN = (
    SetupChoice("S1", "S1b_orb15_narrow_fullfail", "own_rule", "50%"),
    SetupChoice("S2", "S2_twap_lowvol", "hold_1510", "30%"),
)
CAPS = (None, 3000, 4000, 5000, 6000, 8000)


def pick(trades: pd.DataFrame, choices: tuple[SetupChoice, ...] = CHOSEN) -> pd.DataFrame:
    parts = []
    for c in choices:
        t = trades[(trades["setup"] == c.setup) & (trades["exit_mode"] == c.exit_mode) & (trades["stop"] == c.stop)]
        parts.append(t.assign(sname=c.name))
    out = pd.concat(parts, ignore_index=True)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"])
    out["exit_ts"] = pd.to_datetime(out["exit_ts"])
    out["day"] = pd.to_datetime(out["day"]).dt.date
    return out.sort_values("entry_ts").reset_index(drop=True)


def pick_logic(trades: pd.DataFrame, open_outside_only: bool = True) -> pd.DataFrame:
    """G1/G2 trades from the setup-logic study (S1/S2, optionally only open-outside-range days)."""
    t = trades[trades["setup"].isin(["S1", "S2"])].copy()
    if open_outside_only:
        t = t[t["F4_open_outside"] == True]  # noqa: E712
    t["sname"] = t["setup"].map({"S1": "G1", "S2": "G2"})
    t["entry_ts"] = pd.to_datetime(t["entry_ts"])
    t["exit_ts"] = pd.to_datetime(t["exit_ts"])
    t["day"] = pd.to_datetime(t["day"]).dt.date
    return t.sort_values("entry_ts").reset_index(drop=True)


def longest_losing_streak(pnl: "pd.Series[float]") -> int:
    best = cur = 0
    for v in pnl:
        cur = cur + 1 if v <= 0 else 0
        best = max(best, cur)
    return best


def max_drawdown(pnl: np.ndarray) -> float:
    eq = np.cumsum(pnl)
    return float((eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]).min())


def per_setup(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for name, g in t.groupby("sname"):
        losses = g[g["net_inr"] <= 0]["net_inr"]
        rows.append({"setup": name, "trades": len(g), "win": round((g["net_inr"] > 0).mean(), 3),
                     "net_per_trade": round(g["net_inr"].mean(), 1), "avg_loss": round(losses.mean(), 1),
                     "p90_loss": round(losses.quantile(0.10), 1), "worst": round(g["net_inr"].min(), 1),
                     "longest_losing_streak": longest_losing_streak(g["net_inr"]),
                     "max_dd": round(max_drawdown(g["net_inr"].to_numpy())), "total": round(g["net_inr"].sum())})
    return pd.DataFrame(rows)


def apply_cap(t: pd.DataFrame, cap: float | None) -> pd.DataFrame:
    """Return trades actually taken under a realised-loss daily cap."""
    if cap is None:
        return t
    keep = []
    for _, g in t.groupby("day"):
        taken: list[pd.Series] = []
        for _, tr in g.sort_values("entry_ts").iterrows():
            realised = sum(x["net_inr"] for x in taken if x["exit_ts"] <= tr["entry_ts"])
            if realised <= -cap:
                continue
            taken.append(tr)
        keep.extend(taken)
    return pd.DataFrame(keep)


def daily(t: pd.DataFrame) -> "pd.Series[float]":
    return t.groupby("day")["net_inr"].sum()


def cap_table(t: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for cap in CAPS:
        k = apply_cap(t, cap)
        d = daily(k)
        rows.append({"daily_cap": "none" if cap is None else cap, "trades": len(k), "total": round(k["net_inr"].sum()),
                     "net_per_trade": round(k["net_inr"].mean(), 1), "worst_day": round(d.min()),
                     "days_below_-4k": int((d <= -4000).sum()), "days_below_-6k": int((d <= -6000).sum()),
                     "days_below_-8k": int((d <= -8000).sum()), "max_dd": round(max_drawdown(d.to_numpy()))})
    return pd.DataFrame(rows)


def monte_carlo(day_pnl: "pd.Series[float]", runs: int = 10000, seed: int = 7,
                kill_inr: float = 20000.0) -> dict[str, Any]:
    """Reshuffle the order of trading days; kill_inr = risk.yaml drawdown kill (10% of ₹2,00,000)."""
    rng = np.random.default_rng(seed)
    arr = day_pnl.to_numpy()
    dds, streaks = np.empty(runs), np.empty(runs)
    for i in range(runs):
        s = rng.permutation(arr)
        dds[i] = max_drawdown(s)
        streaks[i] = longest_losing_streak(pd.Series(s))
    return {"days": len(arr), "dd_median": round(float(np.median(dds))), "dd_p95": round(float(np.quantile(dds, 0.05))),
            "dd_p99": round(float(np.quantile(dds, 0.01))), "losing_day_streak_median": int(np.median(streaks)),
            "losing_day_streak_p95": int(np.quantile(streaks, 0.95)),
            "share_of_runs_hitting_kill": round(float((dds <= -kill_inr).mean()), 3)}


def day_profile(t: pd.DataFrame) -> dict[str, Any]:
    d = daily(t)
    trades_per_day = t.groupby("day").size()
    return {"trading_days": len(d), "days_2_trades": int((trades_per_day == 2).sum()),
            "win_days": round(float((d > 0).mean()), 3), "avg_day": round(d.mean(), 1),
            "p5_day": round(d.quantile(0.05)), "p1_day": round(d.quantile(0.01)), "worst_day": round(d.min()),
            "best_day": round(d.max()), "longest_losing_day_streak": longest_losing_streak(d)}
