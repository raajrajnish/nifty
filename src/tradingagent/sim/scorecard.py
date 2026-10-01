"""Trade-quality scorecard (`tradingagent scorecard`): measure each link of a trade, and how links relate.

Links (owner, 2026-10-01): 0 setup logic · 1 entry at the right time · 2 capitalise on profit · 3 right exit.
Measurement only — no rule is changed here. Every number is compared with the random-entry control.

Per trade (from the stop-study trades for the chosen variants; option path uses 1-min closes as % of entry):
  logic    follow_15/30/60/eod — index move in the trade's direction after entry, in units of daily ATR
           (ATR = 14-day average daily range, known before the day starts → no look-ahead)
  entry    heat10 / gain10 — worst / best option move in the first 10 minutes (% of entry premium)
           entry_eff — where our entry sits in the option's low…high range of ±10 minutes (0 = best price)
           heat_before_peak — worst dip before the trade's best point
  capture  mfe_pct — best close reached while in the trade; capture = realised % / mfe % (when mfe > 0)
           t_peak_min — minutes from entry to the best close
  exit     shaken_out — closed by STOP but the option was above entry at 15:10
           won_then_lost — reached ≥ +1R (30% of entry) at some point and still finished ≤ 0
           runner_missed — closed in profit, but the option at 15:10 was ≥ 30% above the exit price
           stuck_min — minutes spent within ±7.5% (¼R) of entry
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd

from tradingagent.data.store import MarketStore
from tradingagent.sim.entry_study import day_features

R_PCT = 30.0


@dataclass(frozen=True)
class Variant:
    name: str
    setup: str
    exit_mode: str
    stop: str


VARIANTS = (
    Variant("S1", "S1b_orb15_narrow_fullfail", "own_rule", "50%"),
    Variant("S2", "S2_twap_lowvol", "hold_1510", "30%"),
    Variant("RANDOM", "ref_random", "hold_1510", "30%"),
)


def option_symbol_row(r: pd.Series) -> str:
    exp = pd.Timestamp(r["expiry"]).strftime("%d%b%y")
    return f"NSE-NIFTY-{exp}-{int(r['strike'])}-{r['side']}"


def trade_metrics(r: pd.Series, opt: pd.DataFrame, idx: pd.DataFrame, atr_pts: float) -> dict[str, Any]:
    """opt/idx: that day's 1-min bars indexed by ts. r: one trade row (entry_ts, exit_ts, entry_px, exit_px …)."""
    e_ts, x_ts = pd.Timestamp(r["entry_ts"]), pd.Timestamp(r["exit_ts"])
    entry = float(r["entry_px"])
    sign = 1.0 if r["side"] == "CE" else -1.0
    path = opt.loc[e_ts:x_ts, "close"] / entry * 100 - 100          # % of entry premium, in trade
    low_path = opt.loc[e_ts:x_ts, "low"] / entry * 100 - 100
    realised = (float(r["exit_px"]) / entry - 1) * 100
    first10 = opt.loc[e_ts:e_ts + timedelta(minutes=10)]
    heat10 = float((first10["low"] / entry * 100 - 100).min()) if len(first10) else np.nan
    gain10 = float((first10["high"] / entry * 100 - 100).max()) if len(first10) else np.nan
    win = opt.loc[e_ts - timedelta(minutes=10):e_ts + timedelta(minutes=10)]
    lo, hi = float(win["low"].min()), float(win["high"].max())
    entry_eff = (entry - lo) / (hi - lo) if hi > lo else np.nan
    mfe = float(path.max()) if len(path) else 0.0
    t_peak = path.idxmax() if len(path) else e_ts
    heat_before_peak = float(low_path.loc[:t_peak].min()) if len(path) else np.nan
    eod = opt.loc[:pd.Timestamp(datetime.combine(e_ts.date(), time(15, 10))), "close"]
    eod_px = float(eod.iloc[-1]) if len(eod) else np.nan
    i0 = float(idx.loc[:e_ts, "close"].iloc[-1])

    def follow(minutes: int | None) -> float:
        t = pd.Timestamp(datetime.combine(e_ts.date(), time(15, 10))) if minutes is None \
            else e_ts + timedelta(minutes=minutes)
        s = idx.loc[:t, "close"]
        return float(sign * (s.iloc[-1] - i0) / atr_pts) if len(s) and atr_pts > 0 else np.nan

    return {
        "follow_15": follow(15), "follow_30": follow(30), "follow_60": follow(60), "follow_eod": follow(None),
        "heat10": heat10, "gain10": gain10, "entry_eff": entry_eff, "heat_before_peak": heat_before_peak,
        "mfe_pct": mfe, "realised_pct": realised, "capture": realised / mfe if mfe > 1 else np.nan,
        "t_peak_min": (t_peak - e_ts).total_seconds() / 60,
        "shaken_out": bool(r["reason"] == "STOP" and eod_px > entry),
        "won_then_lost": bool(mfe >= R_PCT and r["net_inr"] <= 0),
        "runner_missed": bool(r["net_inr"] > 0 and eod_px >= float(r["exit_px"]) * 1.30),
        "stuck_min": int((path.abs() <= R_PCT / 4).sum()),
    }


def build(store: MarketStore, stop_trades: pd.DataFrame) -> pd.DataFrame:
    idx = store.candles("NSE-NIFTY", "1minute")
    idx["day"] = idx["ts"].dt.date
    feats = day_features(idx)
    idx_by_day = {d: g.set_index("ts") for d, g in idx.groupby("day")}
    rows = []
    for v in VARIANTS:
        t = stop_trades[(stop_trades["setup"] == v.setup) & (stop_trades["exit_mode"] == v.exit_mode)
                        & (stop_trades["stop"] == v.stop)]
        for _, r in t.iterrows():
            d = pd.Timestamp(r["day"]).date()
            atr_pct = feats.at[d, "atr14_pct"]
            day_idx = idx_by_day[d]
            atr_pts = float(atr_pct * day_idx["close"].iloc[0]) if pd.notna(atr_pct) else np.nan
            opt = store.candles(option_symbol_row(r), "1minute", datetime.combine(d, time(9, 15)),
                                datetime.combine(d, time(15, 30))).set_index("ts")
            if opt.empty:
                continue
            rows.append({"variant": v.name, "day": d, "side": r["side"], "reason": r["reason"],
                         "net_inr": r["net_inr"], "win": r["net_inr"] > 0,
                         **trade_metrics(r, opt, day_idx, atr_pts)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------- scorecard
def scorecard(m: pd.DataFrame) -> pd.DataFrame:
    out = []
    for v, g in m.groupby("variant"):
        w = g[g["win"]]
        pos = g[g["mfe_pct"] > 1]
        edge_ratio10 = round(float(g["gain10"].mean() / abs(g["heat10"].mean())), 2)
        out.append({
            "variant": v, "n": len(g), "win%": round(g["win"].mean() * 100, 1), "net/trade": round(g["net_inr"].mean()),
            # 0 logic
            "follow15_ATR": round(g["follow_15"].mean(), 3), "follow60_ATR": round(g["follow_60"].mean(), 3),
            "followEOD_ATR": round(g["follow_eod"].mean(), 3),
            "right_dir_60%": round((g["follow_60"] > 0).mean() * 100, 1),
            # 1 entry
            "edge_ratio10": edge_ratio10, "heat10_med%": round(g["heat10"].median(), 1),
            "entry_eff_med": round(g["entry_eff"].median(), 2),
            "winner_heat_med%": round(w["heat_before_peak"].median(), 1),
            # 2 capture
            "mfe_med%": round(g["mfe_pct"].median(), 1), "capture_med": round(pos["capture"].median(), 2),
            "winner_capture_med": round(w["capture"].median(), 2), "t_peak_med_min": round(w["t_peak_min"].median()),
            # 3 exit
            "won_then_lost%": round(g["won_then_lost"].mean() * 100, 1),
            "shaken_out%": round(g["shaken_out"].mean() * 100, 1),
            "runner_missed%": round(g["runner_missed"].mean() * 100, 1),
            "stuck_med_min": round(g["stuck_min"].median()),
        })
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------- relationships
def _tercile_table(g: pd.DataFrame, col: str, labels: tuple[str, str, str]) -> pd.DataFrame:
    x = g.dropna(subset=[col]).copy()
    x["bucket"] = pd.qcut(x[col].rank(method="first"), 3, labels=list(labels))
    return x.groupby("bucket", observed=True).agg(
        n=("net_inr", "size"), win_pct=("win", lambda s: round(s.mean() * 100, 1)),
        net=("net_inr", lambda s: round(s.mean())), mfe_med=("mfe_pct", lambda s: round(s.median(), 1)),
        capture_med=("capture", lambda s: round(s.median(), 2)))


def relationships(m: pd.DataFrame) -> dict[str, pd.DataFrame]:
    out: dict[str, pd.DataFrame] = {}
    for v, g in m.groupby("variant"):
        out[f"{v}: entry heat (first 10 min) → result"] = _tercile_table(
            g, "heat10", ("worst heat", "middle", "least heat"))
        x = g.dropna(subset=["follow_15"]).copy()
        x["follow"] = np.where(x["follow_15"] > 0, "index moved our way in 15 min", "index did NOT")
        out[f"{v}: early follow-through → result"] = x.groupby("follow").agg(
            n=("net_inr", "size"), win_pct=("win", lambda s: round(s.mean() * 100, 1)),
            net=("net_inr", lambda s: round(s.mean())), mfe_med=("mfe_pct", lambda s: round(s.median(), 1)))
        out[f"{v}: size of best move → how much we kept"] = _tercile_table(
            g[g["mfe_pct"] > 1], "mfe_pct", ("small peak", "medium peak", "big peak"))
        out[f"{v}: entry price quality → result"] = _tercile_table(
            g, "entry_eff", ("best entries", "middle", "worst entries"))
        w = g[g["win"]].copy()
        if len(w) >= 9:
            out[f"{v}: winners — time to peak → how much we kept"] = _tercile_table(
                w, "t_peak_min", ("early peak", "middle", "late peak"))
        cols = ["follow_15", "heat10", "entry_eff", "mfe_pct", "capture", "t_peak_min", "net_inr"]
        out[f"{v}: rank correlation"] = g[cols].corr(method="spearman").round(2)
    return out
