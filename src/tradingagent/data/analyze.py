"""End-of-day analysis of recorder output (`tradingagent analyze-day YYYY-MM-DD`).

Pure functions over DataFrames + a small loader/report writer. Outputs go to data/reports/date=YYYY-MM-DD/.
Descriptive only: one day calibrates costs/liquidity; it cannot validate a strategy.
"""

import json
from dataclasses import dataclass
from datetime import time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOT = 65          # verified live 2026-09-30 from the Groww instrument master (see master.manifest.json)
STEP = 50
TIME_BUCKETS = [(time(9, 15), time(9, 30)), (time(9, 30), time(11, 0)), (time(11, 0), time(13, 0)),
                (time(13, 0), time(14, 0)), (time(14, 0), time(15, 30))]


# ---------------------------------------------------------------------------- loading
@dataclass
class DayData:
    ltp: pd.DataFrame      # ts, nifty, vix, fut
    quotes: pd.DataFrame   # ts, symbol, bid, ask, bid_qty, ask_qty, ltp, oi, volume, last_trade_time
    chain: pd.DataFrame    # ts, strike, type, ltp, iv, oi, volume, delta, symbol, underlying
    lot: int


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_day(day_dir: Path) -> DayData:
    rows = _read_jsonl(day_dir / "ltp.jsonl")
    ltp = pd.DataFrame({
        # ISO8601: Python omits ".ffffff" when microseconds are exactly 0, so formats are mixed (bug 2026-10-01)
        "ts": pd.to_datetime([r["recv_ts"] for r in rows], format="ISO8601"),
        "nifty": [r["index"].get("NSE_NIFTY") for r in rows],
        "vix": [r["index"].get("NSE_INDIAVIX") for r in rows],
        "fut": [next((v for k, v in r["fno"].items() if k.endswith("FUT")), None) for r in rows],
    })
    cols = ("recv_ts", "symbol", "bid", "ask", "bid_qty", "ask_qty", "ltp", "oi", "volume", "last_trade_time")
    q = pd.DataFrame([{k: r.get(k) for k in cols} for r in _read_jsonl(day_dir / "quotes.jsonl")])
    q["ts"] = pd.to_datetime(q.pop("recv_ts"), format="ISO8601")
    chain_rows = []
    for r in _read_jsonl(day_dir / "chain.jsonl"):
        ts = pd.Timestamp(r["recv_ts"])
        for k, sides in r["strikes"].items():
            for side, v in (sides or {}).items():
                g = v.get("greeks") or {}
                chain_rows.append({"ts": ts, "strike": float(k), "type": side, "ltp": v.get("ltp"), "iv": g.get("iv"),
                                   "delta": g.get("delta"), "oi": v.get("open_interest"), "volume": v.get("volume"),
                                   "symbol": v.get("trading_symbol"), "underlying": r.get("underlying_ltp")})
    chain = pd.DataFrame(chain_rows)
    lot = LOT
    manifest = day_dir / "master.manifest.json"
    if manifest.exists():
        sizes = json.loads(manifest.read_text(encoding="utf-8")).get("option_lot_sizes") or []
        if len(sizes) == 1:
            lot = int(sizes[0])
    return DayData(ltp.sort_values("ts"), q.sort_values("ts"), chain, lot)


def symbol_map(chain: pd.DataFrame) -> pd.DataFrame:
    return chain.dropna(subset=["symbol"]).drop_duplicates("symbol")[["symbol", "strike", "type"]]


# ---------------------------------------------------------------------------- data quality
def cadence(ts: pd.Series, expected_s: float) -> dict[str, Any]:
    d = ts.sort_values().diff().dt.total_seconds().dropna()
    big = d[d > 3 * expected_s]
    return {"rows": int(len(ts)), "first": str(ts.min()), "last": str(ts.max()),
            "median_gap_s": round(float(d.median()), 2) if len(d) else None,
            "p95_gap_s": round(float(d.quantile(0.95)), 2) if len(d) else None,
            "max_gap_s": round(float(d.max()), 1) if len(d) else None,
            "gaps_over_3x": int(len(big)), "gap_seconds_lost": round(float((big - expected_s).sum()), 1)}


def quote_quality(q: pd.DataFrame) -> dict[str, Any]:
    raw = q.dropna(subset=["bid", "ask"])
    both = raw[(raw["bid"] > 0) & (raw["ask"] > 0)]  # 0/0 = empty pre-open book, not a crossed market
    ltt = pd.to_datetime(q["last_trade_time"], unit="s", utc=True, errors="coerce")
    lag = (q["ts"].dt.tz_convert("UTC") - ltt).dt.total_seconds()
    return {"quotes": int(len(q)), "missing_bid_or_ask": int(len(q) - len(raw)),
            "empty_book": int(len(raw) - len(both)),
            "crossed_or_locked": int((both["bid"] >= both["ask"]).sum()),
            "per_symbol_min": int(q.groupby("symbol").size().min()), "symbols": int(q["symbol"].nunique()),
            "last_trade_age_s_median": round(float(lag.median()), 1),
            "last_trade_age_s_p95": round(float(lag.quantile(0.95)), 1)}


def frozen_index_episodes(ltp: pd.DataFrame, window_s: int = 60, fut_move_pts: float = 5.0) -> int:
    """L6 check: index unchanged for a whole window while the future moved."""
    s = ltp.set_index("ts")[["nifty", "fut"]].dropna()
    r = s.rolling(f"{window_s}s")
    idx_flat = (r["nifty"].max() - r["nifty"].min()) == 0
    fut_move = (r["fut"].max() - r["fut"].min()) >= fut_move_pts
    elapsed = (s.index.to_series() - s.index[0]).dt.total_seconds() >= window_s
    flag = (idx_flat & fut_move & elapsed).astype(int)
    return int((flag.diff() == 1).sum())


def index_anomalies(ltp: pd.DataFrame, jump_pts: float = 15.0, fut_quiet_pts: float = 5.0) -> dict[str, Any]:
    """L6 check (confirmed on 2026-09-30): index jumps while the future is quiet = bad index print."""
    x = ltp.dropna(subset=["nifty", "fut"])
    di, df = x["nifty"].diff().abs(), x["fut"].diff().abs()
    bad = x[(di > jump_pts) & (df < fut_quiet_pts)]
    return {"bad_index_ticks": int(len(bad)), "times": bad["ts"].dt.strftime("%H:%M:%S").tolist()[:20]}


def clean_index(ltp: pd.DataFrame, until: time = time(15, 15), jump_pts: float = 15.0,
                fut_quiet_pts: float = 5.0) -> pd.DataFrame:
    """Index rows safe for statistics: before `until` and without bad-print ticks."""
    x = ltp.dropna(subset=["nifty"])
    x = x[x["ts"].dt.time < until]
    di, df = x["nifty"].diff().abs(), x["fut"].diff().abs()
    return x[~((di > jump_pts) & (df < fut_quiet_pts))]


# ---------------------------------------------------------------------------- market
def market_summary(ltp: pd.DataFrame) -> dict[str, Any]:
    """Pass clean_index(ltp) — raw index prints near the close can be garbage."""
    n = ltp.dropna(subset=["nifty"])
    basis = (ltp["fut"] - ltp["nifty"]).dropna()
    return {"nifty_open_recorded": float(n["nifty"].iloc[0]), "nifty_close_recorded": float(n["nifty"].iloc[-1]),
            "nifty_high": float(n["nifty"].max()), "nifty_low": float(n["nifty"].min()),
            "range_pts": round(float(n["nifty"].max() - n["nifty"].min()), 2),
            "vix_first": float(ltp["vix"].dropna().iloc[0]), "vix_last": float(ltp["vix"].dropna().iloc[-1]),
            "fut_basis_median": round(float(basis.median()), 2)}


def candles(ltp: pd.DataFrame, rule: str = "1min") -> pd.DataFrame:
    s = ltp.set_index("ts")["nifty"].dropna()
    return s.resample(rule).ohlc().dropna()


def straddle_vs_realized(chain: pd.DataFrame, ltp: pd.DataFrame, at: time = time(9, 30)) -> dict[str, Any]:
    snaps = chain[chain["ts"].dt.time >= at]
    if snaps.empty:
        return {}
    t0 = snaps["ts"].min()
    s = snaps[snaps["ts"] == t0]
    atm = round(float(s["underlying"].iloc[0]) / STEP) * STEP
    legs = s[s["strike"] == atm].set_index("type")["ltp"]
    straddle = float(legs.get("CE", np.nan) + legs.get("PE", np.nan))
    after = ltp[ltp["ts"] >= t0].dropna(subset=["nifty"])
    return {"at": str(t0), "atm": atm, "straddle_pts": round(straddle, 2),
            "atm_iv": float(s[(s["strike"] == atm)]["iv"].mean()),
            "realized_range_after_pts": round(float(after["nifty"].max() - after["nifty"].min()), 2),
            "realized_close_move_pts": round(float(after["nifty"].iloc[-1] - after["nifty"].iloc[0]), 2)}


# ---------------------------------------------------------------------------- spreads & depth
def _attach_moneyness(q: pd.DataFrame, ltp: pd.DataFrame, smap: pd.DataFrame) -> pd.DataFrame:
    x = q.merge(smap, on="symbol", how="inner").sort_values("ts")
    x = pd.merge_asof(x, ltp[["ts", "nifty"]].dropna().sort_values("ts"), on="ts", direction="backward")
    x["atm"] = (x["nifty"] / STEP).round() * STEP
    x["steps_from_atm"] = ((x["strike"] - x["atm"]) / STEP).round().astype("Int64")
    # moneyness sign: positive = OTM for both calls and puts
    x["otm_steps"] = np.where(x["type"] == "CE", x["steps_from_atm"], -x["steps_from_atm"])
    return x


def _bucket(t: time) -> str:
    for a, b in TIME_BUCKETS:
        if a <= t < b:
            return f"{a:%H:%M}-{b:%H:%M}"
    return "other"


def spread_table(q: pd.DataFrame, ltp: pd.DataFrame, chain: pd.DataFrame, lot: int) -> dict[str, Any]:
    x = _attach_moneyness(q.dropna(subset=["bid", "ask"]), ltp, symbol_map(chain))
    x = x[(x["bid"] > 0) & (x["ask"] > x["bid"])]
    x["mid"] = (x["bid"] + x["ask"]) / 2
    x["spread_pct"] = (x["ask"] - x["bid"]) / x["mid"] * 100
    x["spread_inr_lot"] = (x["ask"] - x["bid"]) * lot
    x["bucket"] = x["ts"].dt.time.map(_bucket)
    near = x[x["otm_steps"].abs() <= 1]
    by_money = x.groupby("otm_steps")["spread_pct"].agg(["median", lambda s: s.quantile(0.9), "count"])
    by_money.columns = ["median_pct", "p90_pct", "n"]
    by_time = near.groupby("bucket")["spread_pct"].agg(["median", lambda s: s.quantile(0.9), "count"])
    by_time.columns = ["median_pct", "p90_pct", "n"]
    atm = x[x["otm_steps"] == 0]
    return {
        "atm_spread_pct_median": round(float(atm["spread_pct"].median()), 3),
        "atm_spread_pct_p90": round(float(atm["spread_pct"].quantile(0.9)), 3),
        "atm_spread_inr_per_lot_median": round(float(atm["spread_inr_lot"].median()), 1),
        "atm_premium_median": round(float(atm["mid"].median()), 2),
        "atm_top_bid_lots_median": round(float((atm["bid_qty"] / lot).median()), 1),
        "atm_top_ask_lots_median": round(float((atm["ask_qty"] / lot).median()), 1),
        "share_near_atm_over_3pct": round(float((near["spread_pct"] > 3).mean()), 4),
        "by_otm_steps": by_money.round(3).reset_index().to_dict("records"),
        "near_atm_by_time": by_time.round(3).reset_index().to_dict("records"),
    }


def liquidity(chain: pd.DataFrame) -> dict[str, Any]:
    last = chain[chain["ts"] == chain["ts"].max()]
    atm = round(float(last["underlying"].iloc[0]) / STEP) * STEP
    near = last[(last["strike"] - atm).abs() <= 5 * STEP]
    return {"eod_atm": atm, "eod_volume_near_atm_min": int(near["volume"].min()),
            "eod_volume_near_atm_median": int(near["volume"].median()),
            "eod_oi_near_atm_median": int(near["oi"].median())}


# ---------------------------------------------------------------------------- entry test (lesson L4)
def entry_test(q: pd.DataFrame, ltp: pd.DataFrame, chain: pd.DataFrame, lot: int,
               start: time = time(9, 30), end: time = time(14, 0), every_min: int = 5,
               horizons: tuple[int, ...] = (10, 25, 60)) -> pd.DataFrame:
    """Buy the ATM CE and PE at the real ASK every N minutes; track the real BID afterwards.
    mfe_h  = best bid within h minutes − entry ask   (upper bound: perfect exit)
    exit_h = bid at t+h − entry ask                  (mechanical time exit)
    ₹ per lot, BEFORE brokerage/taxes (costs.yaml still TBD)."""
    smap = symbol_map(chain)
    x = q.dropna(subset=["bid", "ask"]).merge(smap, on="symbol").sort_values("ts")
    x = x[(x["bid"] > 0) & (x["ask"] > 0)]
    idx = ltp[["ts", "nifty"]].dropna().sort_values("ts")
    day = x["ts"].dt.normalize().iloc[0]
    t = day + timedelta(hours=start.hour, minutes=start.minute)
    t_end = day + timedelta(hours=end.hour, minutes=end.minute)
    out = []
    while t <= t_end:
        spot = idx[idx["ts"] <= t]
        if spot.empty:
            t += timedelta(minutes=every_min)
            continue
        atm = round(float(spot["nifty"].iloc[-1]) / STEP) * STEP
        for side in ("CE", "PE"):
            c = x[(x["strike"] == atm) & (x["type"] == side)]
            first = c[(c["ts"] >= t) & (c["ts"] < t + timedelta(seconds=30))]
            if first.empty:
                continue
            e = first.iloc[0]
            row: dict[str, Any] = {"t": t, "side": side, "strike": atm, "entry_ask": e["ask"],
                                   "spread_inr": (e["ask"] - e["bid"]) * lot}
            for h in horizons:
                w = c[(c["ts"] > e["ts"]) & (c["ts"] <= e["ts"] + timedelta(minutes=h))]
                if w.empty:
                    continue
                row[f"mfe_{h}"] = (w["bid"].max() - e["ask"]) * lot
                row[f"mae_{h}"] = (w["bid"].min() - e["ask"]) * lot
                row[f"exit_{h}"] = (w["bid"].iloc[-1] - e["ask"]) * lot
            out.append(row)
        t += timedelta(minutes=every_min)
    return pd.DataFrame(out)


def summarize_entries(e: pd.DataFrame, charge_scenarios: tuple[int, ...] = (50, 100)) -> dict[str, Any]:
    res: dict[str, Any] = {"entries": int(len(e)),
                           "median_spread_inr_per_lot": round(float(e["spread_inr"].median()), 1)}
    for h in (10, 25, 60):
        if f"mfe_{h}" not in e:
            continue
        m, ex = e[f"mfe_{h}"].dropna(), e[f"exit_{h}"].dropna()
        d: dict[str, Any] = {
            "mfe_median": round(float(m.median()), 1), "mfe_p75": round(float(m.quantile(0.75)), 1),
            "mae_median": round(float(e[f"mae_{h}"].median()), 1),
            "exit_median": round(float(ex.median()), 1), "exit_mean": round(float(ex.mean()), 1),
            "share_mfe_never_positive": round(float((m <= 0).mean()), 3),
        }
        for c in charge_scenarios:
            d[f"share_mfe_below_charges_{c}"] = round(float((m <= c).mean()), 3)
        best = e.groupby("t")[f"mfe_{h}"].max().dropna()
        d["hindsight_best_side_mfe_median"] = round(float(best.median()), 1)
        res[f"h{h}"] = d
    return res


# ---------------------------------------------------------------------------- report
def analyze(day_dir: Path, out_dir: Path, recorder_status: dict[str, Any] | None = None) -> dict[str, Any]:
    dd = load_day(day_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    entries = entry_test(dd.quotes, dd.ltp, dd.chain, dd.lot)
    entries.to_csv(out_dir / "entry_test.csv", index=False)
    candles(dd.ltp, "1min").to_csv(out_dir / "nifty_1m.csv")
    candles(dd.ltp, "5min").to_csv(out_dir / "nifty_5m.csv")
    clean = clean_index(dd.ltp)
    metrics = {
        "day": day_dir.name.removeprefix("date="), "lot_size": dd.lot, "recorder": recorder_status,
        "quality": {"ltp": cadence(dd.ltp["ts"], 2.0), "chain": cadence(dd.chain.drop_duplicates("ts")["ts"], 60.0),
                    "quotes": quote_quality(dd.quotes), "frozen_index_episodes": frozen_index_episodes(dd.ltp),
                    "index_anomalies": index_anomalies(dd.ltp)},
        "market": {**market_summary(clean), "note": "index stats use data before 15:15 without bad-print ticks"},
        "straddle": straddle_vs_realized(dd.chain, clean),
        "spreads": spread_table(dd.quotes, dd.ltp, dd.chain, dd.lot),
        "liquidity": liquidity(dd.chain),
        "entry_test": summarize_entries(entries) if len(entries) else {},
    }
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return metrics
