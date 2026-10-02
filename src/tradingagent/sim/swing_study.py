"""Swing study, Nifty 50 basket (`tradingagent backtest-swing`). Spec: docs/reports/2026-10-02_swing_study.md.
Daily bars; long only; ₹1 lakh per trade; signals on close, fills at next open. Paper research only.
"""

import math
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.features.indicators import rsi, true_range
from tradingagent.sim.stock_study import adjust_splits
from tradingagent.sim.timing_study import bootstrap_ci

NOTIONAL = 100_000.0
SLIP = 0.0005
PERIODS = {"P1": (date(2022, 10, 1), date(2024, 9, 30)), "P2": (date(2024, 10, 1), date(2026, 9, 30))}


@dataclass(frozen=True)
class DeliveryCosts:
    brokerage_pct: float = 0.001
    brokerage_cap: float = 20.0
    stt: float = 0.001                 # buy and sell
    stamp_buy: float = 0.00015
    exchange: float = 0.0000297
    sebi_per_cr: float = 10.0
    gst: float = 0.18
    dp_per_sell: float = 20.0

    def buy(self, value: float) -> float:
        brk = min(self.brokerage_cap, value * self.brokerage_pct)
        exch, sebi = value * self.exchange, value * self.sebi_per_cr / 1e7
        return brk + value * self.stt + value * self.stamp_buy + exch + sebi + (brk + exch + sebi) * self.gst

    def sell(self, value: float) -> float:
        brk = min(self.brokerage_cap, value * self.brokerage_pct)
        exch, sebi = value * self.exchange, value * self.sebi_per_cr / 1e7
        return brk + value * self.stt + exch + sebi + (brk + exch + sebi + self.dp_per_sell) * self.gst \
            + self.dp_per_sell


# ---------------------------------------------------------------------------- data
REBUILD_FROM = date(2025, 1, 1)


def rebuild_from_intraday(daily: pd.DataFrame, intraday: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Groww daily candles are broken from 2025: in 2025 'open' is the previous close (99% of days), and from
    late Oct 2025 it is NULL. From REBUILD_FROM, every day's OHLCV is rebuilt from intraday bars (open = first
    trade). Earlier days keep the daily bar; the check reports how often the earlier daily open matched the
    first intraday trade (it should be ~98–100%)."""
    d = daily.copy()
    day = d["ts"].dt.date
    agg = pd.DataFrame()
    if len(intraday):
        i = intraday.sort_values("ts")
        agg = i.groupby(i["ts"].dt.date).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                             close=("close", "last"), volume=("volume", "sum"))
    late = (day >= REBUILD_FROM).to_numpy()
    have = day.isin(agg.index).to_numpy()
    rb = late & have
    for c in ("open", "high", "low", "close", "volume"):
        d.loc[rb, c] = day[rb].map(agg[c]).to_numpy()
    early = (~late) & have & d["open"].notna().to_numpy()
    diff = (d.loc[early, "open"] / day[early].map(agg["open"]) - 1).abs() if early.any() else pd.Series(dtype=float)
    d.loc[late & ~have, "open"] = np.nan                      # no intraday → no trustworthy open; dropped
    stats = {"rebuilt": int(rb.sum()), "dropped": int((late & ~have).sum()), "checked_pre2025": int(early.sum()),
             "pre2025_open_match_0.05%": round(float((diff < 0.0005).mean() * 100), 1) if len(diff) else None}
    return d.dropna(subset=["open"]), stats


def prepare(daily: pd.DataFrame) -> tuple[pd.DataFrame, set[date]]:
    """Clean ×100 prints, back-adjust splits (prices AND volume), add indicators. Index = trading day."""
    d = daily.sort_values("ts").copy()
    for c in ("open", "high", "low"):
        bad = d[c] > 20 * d["close"]
        d.loc[bad, c] = d.loc[bad, c] / 100
    raw_close = d["close"].to_numpy()
    adj, _events, ex_days = adjust_splits(d)
    adj = adj.set_index("day")
    adj["volume"] = adj["volume"].astype(float) * (raw_close / adj["close"].to_numpy())
    c = adj["close"]
    adj["sma200"], adj["sma5"] = c.rolling(200).mean(), c.rolling(5).mean()
    adj["rsi2"] = rsi(c, 2)
    adj["atr14"] = true_range(adj[["high", "low", "close"]]).rolling(14).mean()
    adj["hh55"] = c.shift(1).rolling(55).max()
    adj["ll20"] = adj["low"].shift(1).rolling(20).min()
    adj["vol20"] = adj["volume"].shift(1).rolling(20).mean()
    return adj, ex_days


def period_of(d: date) -> str | None:
    return next((p for p, (a, b) in PERIODS.items() if a <= d <= b), None)


# ---------------------------------------------------------------------------- SW1 / SW2
def sw1_signal(r: pd.Series) -> bool:
    return bool(r["close"] > r["sma200"] and r["rsi2"] < 10)


def sw2_signal(r: pd.Series) -> bool:
    return bool(r["close"] > r["hh55"] and r["volume"] > 1.5 * r["vol20"] and r["close"] > r["sma200"])


def sw1_exit(r: pd.Series, entry: float, atr: float, held: int) -> str | None:
    if r["close"] > r["sma5"]:
        return "ABOVE_SMA5"
    if r["close"] < entry - 3 * atr:
        return "STOP_3ATR"
    return "TIME_10D" if held >= 10 else None


def sw2_exit(r: pd.Series, entry: float, atr: float, held: int) -> str | None:
    if r["close"] < r["ll20"]:
        return "TRAIL_20D_LOW"
    if r["close"] < entry - 2 * atr:
        return "STOP_2ATR"
    return "TIME_60D" if held >= 60 else None


SETUPS = {"SW1": (sw1_signal, sw1_exit), "SW2": (sw2_signal, sw2_exit)}


def _net_pct(entry_open: float, exit_open: float, costs: DeliveryCosts, mult: float = 1.0) -> float:
    buy_px, sell_px = entry_open * (1 + SLIP * mult), exit_open * (1 - SLIP * mult)
    qty = math.floor(NOTIONAL / buy_px)
    gross = (sell_px - buy_px) * qty
    return (gross - mult * (costs.buy(buy_px * qty) + costs.sell(sell_px * qty))) / NOTIONAL * 100


def run_signal_setup(sym: str, d: pd.DataFrame, ex_days: set[date], name: str,
                     costs: DeliveryCosts) -> list[dict[str, Any]]:
    sig, ex = SETUPS[name]
    days = list(d.index)
    rows, i = [], 0
    need = ["sma200", "sma5", "rsi2", "atr14", "hh55", "ll20", "vol20"]
    while i < len(days) - 1:
        day, r = days[i], d.iloc[i]
        per = period_of(day)
        if per is None or day in ex_days or r[need].isna().any() or not sig(r):
            i += 1
            continue
        e_i = i + 1
        entry, atr = float(d.iloc[e_i]["open"]), float(r["atr14"])
        j, reason = e_i, None
        while j < len(days):
            reason = ex(d.iloc[j], entry, atr, j - e_i + 1)
            if reason or j == len(days) - 1:
                break
            j += 1
        x_i = j + 1 if reason and j + 1 < len(days) else j
        exit_px = float(d.iloc[x_i]["open"]) if x_i > j else float(d.iloc[j]["close"])
        rows.append({"symbol": sym, "setup": name, "period": per, "signal_day": day, "entry_day": days[e_i],
                     "exit_day": days[x_i], "hold": x_i - e_i, "reason": reason or "DATA_END",
                     "net_pct": _net_pct(entry, exit_px, costs), "net2_pct": _net_pct(entry, exit_px, costs, 2.0),
                     "e_idx": e_i})
        i = x_i + 1                                   # one position per stock at a time
    return rows


def matched_random(trades: pd.DataFrame, data: dict[str, pd.DataFrame], costs: DeliveryCosts) -> pd.Series:
    """Same stock, same holding days, random entry day inside the same period (seeded per trade)."""
    out = []
    for k, t in enumerate(trades.itertuples(index=False)):
        d = data[t.symbol]
        a, b = PERIODS[t.period]
        idx = [i for i, day in enumerate(d.index) if a <= day <= b and i + t.hold < len(d)]
        if not idx or t.hold < 1:
            out.append(np.nan)
            continue
        e = idx[int(np.random.default_rng(k * 7919 + 17).integers(len(idx)))]
        out.append(_net_pct(float(d.iloc[e]["open"]), float(d.iloc[e + t.hold]["open"]), costs))
    return pd.Series(out, index=trades.index)


# ---------------------------------------------------------------------------- SW3 momentum rotation
def momentum_rotation(data: dict[str, pd.DataFrame], costs: DeliveryCosts, top: int = 5) -> pd.DataFrame:
    cal = sorted(set().union(*[set(d.index) for d in data.values()]))
    months = pd.Series(cal, index=pd.to_datetime(cal)).groupby(pd.to_datetime(cal).to_period("M")).first().tolist()
    rows: list[dict[str, Any]] = []
    held: set[str] = set()
    rt = (costs.buy(NOTIONAL) + costs.sell(NOTIONAL)) / NOTIONAL + 2 * SLIP     # one full round trip, fraction
    for m0, m1 in zip(months[:-1], months[1:], strict=True):
        per = period_of(m0)
        if per is None:
            held = set()
            continue
        mom, ret = {}, {}
        for s, d in data.items():
            if m0 not in d.index or m1 not in d.index:
                continue
            i = d.index.get_loc(m0)
            if i < 252:
                continue
            mom[s] = float(d["close"].iloc[i - 21] / d["close"].iloc[i - 126] - 1)
            ret[s] = float(d.loc[m1, "open"] / d.loc[m0, "open"] - 1)
        if len(mom) < top * 2:
            continue
        pick = set(sorted(mom, key=lambda k: mom[k], reverse=True)[:top])
        turnover = len(pick - held) / top                            # share of the book replaced
        held = pick
        gross = float(np.mean([ret[s] for s in pick]))
        bench = float(np.mean(list(ret.values())))
        rows.append({"month": str(pd.Timestamp(m0).to_period("M")), "period": per, "picks": ",".join(sorted(pick)),
                     "top5_pct": (gross - turnover * rt) * 100, "top5_2x_pct": (gross - 2 * turnover * rt) * 100,
                     "bench_pct": bench * 100, "turnover": turnover})
    t = pd.DataFrame(rows)
    t["excess_pct"] = t["top5_pct"] - t["bench_pct"]
    t["excess_2x_pct"] = t["top5_2x_pct"] - t["bench_pct"]
    return t


# ---------------------------------------------------------------------------- verdicts
def _halves_ok(df: pd.DataFrame, col: str, key: str) -> bool:
    k = sorted(df[key].unique())
    h = df[key] <= k[len(k) // 2]
    return bool(df[h][col].mean() > 0 and df[~h][col].mean() > 0)


def verdict_signal(t: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (setup, per), g in t.groupby(["setup", "period"]):
        w, lo = g[g["net_pct"] > 0]["net_pct"].sum(), -g[g["net_pct"] <= 0]["net_pct"].sum()
        pf = w / lo if lo > 0 else math.inf
        exc = g["excess_pct"].dropna()
        ci = bootstrap_ci(exc.to_numpy()) if len(exc) >= 10 else (np.nan, np.nan, np.nan)
        ok = bool(len(g) >= 60 and g["net_pct"].mean() > 0 and g["net2_pct"].mean() > 0 and pf >= 1.10
                  and exc.mean() > 0 and _halves_ok(g, "net_pct", "signal_day"))
        out.append({"setup": setup, "period": per, "n": len(g), "win%": round((g["net_pct"] > 0).mean() * 100, 1),
                    "net%/trade": round(g["net_pct"].mean(), 3), "net_2x%": round(g["net2_pct"].mean(), 3),
                    "pf": round(pf, 2), "random_same_hold%": round(g["rand_pct"].mean(), 3),
                    "excess%": round(exc.mean(), 3), "excess_ci95": f"[{ci[0]:+.3f}, {ci[1]:+.3f}]",
                    "median_hold_days": g["hold"].median(), "PASS": ok})
    return pd.DataFrame(out)


def verdict_rotation(t: pd.DataFrame) -> pd.DataFrame:
    out = []
    for per, g in t.groupby("period"):
        ok = bool(g["excess_pct"].mean() > 0 and g["excess_2x_pct"].mean() > 0 and _halves_ok(g, "excess_pct", "month"))
        lo, hi, _ = bootstrap_ci(g["excess_pct"].to_numpy())
        out.append({"setup": "SW3", "period": per, "months": len(g), "top5%/month": round(g["top5_pct"].mean(), 3),
                    "bench%/month": round(g["bench_pct"].mean(), 3), "excess%/month": round(g["excess_pct"].mean(), 3),
                    "excess_ci95": f"[{lo:+.3f}, {hi:+.3f}]", "excess_2x%": round(g["excess_2x_pct"].mean(), 3),
                    "avg_turnover": round(g["turnover"].mean(), 2), "PASS": ok})
    return pd.DataFrame(out)


def max_concurrent(t: pd.DataFrame) -> int:
    ev = pd.concat([pd.Series(1, index=pd.to_datetime(t["entry_day"])),
                    pd.Series(-1, index=pd.to_datetime(t["exit_day"]))]).sort_index()
    return int(ev.groupby(level=0).sum().cumsum().max()) if len(ev) else 0
