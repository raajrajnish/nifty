"""Stock pilot: pick the frozen 10-stock universe by the pre-declared rule, then download its history.
Spec: docs/reports/2026-10-02_stock_pilot_study.md (section 1). READ-ONLY market data; resumable.

  uv run python scripts/fetch_stock_universe.py rank      # daily candles for all 50 → ranking → frozen CSV
  uv run python scripts/fetch_stock_universe.py minutes   # 1-min Oct 2021 – Sep 2026 for the frozen 10

Rule: Nifty 50 (NSE list fetched 2026-10-02) → average daily traded value (close × volume) over
1 Jul – 30 Sep 2026 → top 10, skipping stocks with < 4 years of Groww daily history (first candle after
2022-09-30). The CSV is written once; rerunning `rank` refuses to overwrite it.
"""

import csv
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, "src")
from tradingagent.broker.auth import GrowwAuth  # noqa: E402
from tradingagent.broker.groww_adapter import GrowwMarketData  # noqa: E402
from tradingagent.core.clock import WallClock  # noqa: E402
from tradingagent.data.history import FetchAborted, HistoryDownloader  # noqa: E402
from tradingagent.data.store import MarketStore  # noqa: E402

ROOT = Path(".")
LIST = ROOT / "data" / "universe" / "ind_nifty50list.csv"
FROZEN = ROOT / "config" / "stock_universe_2026-09-30.csv"
HIST_START, HIST_END = date(2021, 10, 1), date(2026, 9, 30)
RANK_START, RANK_END = date(2026, 7, 1), date(2026, 9, 30)
MIN_FIRST_DAY = date(2022, 9, 30)
TOP_N = 10


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    with (ROOT / "data" / "fetch_history.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def downloader(store: MarketStore) -> HistoryDownloader:
    load_dotenv(ROOT / ".env")
    auth = GrowwAuth(WallClock())
    st = auth.acquire()
    if not st.connected:
        sys.exit(f"Groww NOT connected: {st.error}")
    return HistoryDownloader(GrowwMarketData(auth.token(), max_requests_per_second=4.0), store, HIST_END, log)


def rank() -> None:
    if FROZEN.exists():
        sys.exit(f"{FROZEN} already exists — the universe is frozen; not re-ranking.")
    names = list(csv.DictReader(LIST.open(encoding="utf-8")))
    store = MarketStore(ROOT / "data" / "market.duckdb")
    try:
        dl = downloader(store)
        rows = []
        for r in names:
            sym = f"NSE-{r['Symbol']}"
            store.upsert_contract(sym, r["Symbol"], "EQ", None, None)
            dl.download_range("CASH", sym, "1day", HIST_START, HIST_END)
            d = store.candles(sym, "1day")
            if d.empty:
                rows.append({"symbol": r["Symbol"], "company": r["Company Name"], "industry": r["Industry"],
                             "first_day": None, "avg_traded_value_cr": None})
                continue
            d["day"] = d["ts"].dt.date
            q = d[(d["day"] >= RANK_START) & (d["day"] <= RANK_END)]
            val = float((q["close"] * q["volume"].astype(float)).mean() / 1e7) if len(q) else None
            rows.append({"symbol": r["Symbol"], "company": r["Company Name"], "industry": r["Industry"],
                         "first_day": d["day"].min(), "avg_traded_value_cr": round(val, 1) if val else None,
                         "rank_days": len(q)})
            log(f"  {r['Symbol']}: first {d['day'].min()}, avg traded value ₹{val or 0:,.0f} cr")
    except FetchAborted as e:
        sys.exit(f"STOPPED: {e} — rerun to resume")
    finally:
        store.close()
    t = pd.DataFrame(rows).sort_values("avg_traded_value_cr", ascending=False, na_position="last")
    t["rank"] = range(1, len(t) + 1)
    t["eligible"] = t["first_day"].notna() & (pd.to_datetime(t["first_day"]).dt.date <= MIN_FIRST_DAY)
    t["selected"] = False
    t.loc[t[t["eligible"]].head(TOP_N).index, "selected"] = True
    (ROOT / "data" / "universe").mkdir(exist_ok=True)
    t.to_csv(ROOT / "data" / "universe" / "nifty50_ranking_2026Q3.csv", index=False)
    t[t["selected"]].to_csv(FROZEN, index=False)
    print(t.to_string(index=False))
    print(f"\nFrozen universe written to {FROZEN}")


def minutes() -> None:
    syms = [r["symbol"] for r in csv.DictReader(FROZEN.open(encoding="utf-8"))]
    store = MarketStore(ROOT / "data" / "market.duckdb")
    try:
        dl = downloader(store)
        for s in syms:
            n = dl.download_range("CASH", f"NSE-{s}", "1minute", HIST_START, HIST_END)
            log(f"  {s}: +{n} 1-minute candles")
    except FetchAborted as e:
        sys.exit(f"STOPPED: {e} — rerun to resume")
    finally:
        s = dl.stats
        log(f"done: requests={s.requests} candles_added={s.candles} skipped_days={s.skipped_days} errors={s.errors}")
        store.close()


def opens15() -> None:
    """Groww daily candles have open = NULL from late Oct 2025 (and 2025-01-01). For stocks without 1-min data,
    download 15-min candles from 2024-12-01 so each day's open can be rebuilt from its first bar
    (and checked against the daily open where both exist)."""
    names = [r["Symbol"] for r in csv.DictReader(LIST.open(encoding="utf-8"))]
    store = MarketStore(ROOT / "data" / "market.duckdb")
    try:
        dl = downloader(store)
        for s in names:
            if not store.candles(f"NSE-{s}", "1minute", datetime(2025, 1, 1), datetime(2025, 1, 2)).empty:
                continue                                  # has 1-min data already
            n = dl.download_range("CASH", f"NSE-{s}", "15minute", date(2024, 12, 1), HIST_END)
            log(f"  {s}: +{n} 15-minute candles")
    except FetchAborted as e:
        sys.exit(f"STOPPED: {e} — rerun to resume")
    finally:
        store.close()


if __name__ == "__main__":
    {"rank": rank, "minutes": minutes, "opens15": opens15}[sys.argv[1]]()
