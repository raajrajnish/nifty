"""Phase 1 task 1.3 — READ-ONLY probe of Groww historical candle availability.

Answers: history depth per interval for the NIFTY index, max window per request, futures history
(current + expired), and whether EXPIRED option contracts still return candles.
Output: data/probes/history_probe_<date>.json (+ printed summary). Places no orders.
"""

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
from growwapi import GrowwAPI  # noqa: E402

g = GrowwAPI(os.environ["GROWW_ACCESS_TOKEN"])
TODAY = date.today()
results: dict[str, list[dict[str, object]]] = {}


def fetch(label: str, segment: str, groww_symbol: str, start: datetime, end: datetime, interval: str) -> dict:
    time.sleep(0.35)  # gentle pacing
    rec: dict[str, object] = {"symbol": groww_symbol, "interval": interval, "start": str(start), "end": str(end)}
    try:
        r = g.get_historical_candles(exchange=g.EXCHANGE_NSE, segment=segment, groww_symbol=groww_symbol,
                                     start_time=start.strftime("%Y-%m-%d %H:%M:%S"),
                                     end_time=end.strftime("%Y-%m-%d %H:%M:%S"), candle_interval=interval, timeout=20)
        candles = (r or {}).get("candles") or []
        rec.update(ok=True, n=len(candles), first=candles[0] if candles else None,
                   last=candles[-1] if candles else None, keys=list((r or {}).keys()))
    except Exception as e:  # noqa: BLE001
        rec.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
    results.setdefault(label, []).append(rec)
    status = f"n={rec.get('n')}" if rec.get("ok") else f"ERR {rec.get('error')}"
    print(f"[{label}] {groww_symbol} {interval} {start:%Y-%m-%d}->{end:%Y-%m-%d}: {status}")
    return rec


def session(d: date) -> tuple[datetime, datetime]:
    return datetime(d.year, d.month, d.day, 9, 15), datetime(d.year, d.month, d.day, 15, 30)


def prev_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# --- instrument master: groww symbols ----------------------------------------------------------
inst = g.get_all_instruments()
idx = inst[(inst["trading_symbol"] == "NIFTY") & (inst["segment"] == "CASH")]
INDEX = str(idx.iloc[0]["groww_symbol"]) if len(idx) else "NSE-NIFTY"
print("index groww_symbol:", INDEX, "| instrument_type:", idx.iloc[0]["instrument_type"] if len(idx) else "?")
futs = inst[(inst["underlying_symbol"] == "NIFTY") & (inst["instrument_type"] == "FUT")].sort_values("expiry_date")
CUR_FUT = str(futs.iloc[0]["groww_symbol"])

# --- 1) index depth per interval: one session at increasing lookbacks --------------------------
lookbacks_days = [7, 30, 90, 180, 365, 730, 1095, 1825]
for interval in ("1minute", "5minute", "15minute", "1day"):
    for lb in lookbacks_days:
        d = prev_weekday(TODAY - timedelta(days=lb))
        s, e = session(d)
        if interval == "1day":
            s = s - timedelta(days=10)
        fetch(f"index_depth_{interval}", "CASH", INDEX, s, e, interval)

# --- 2) max window per request (index) ---------------------------------------------------------
for interval, spans in (("1minute", [1, 7, 14, 30, 60]), ("5minute", [7, 30, 60, 90, 180]),
                        ("15minute", [30, 90, 180, 365])):
    for span in spans:
        e = datetime.combine(prev_weekday(TODAY - timedelta(days=1)), datetime.min.time()).replace(hour=15, minute=30)
        fetch(f"index_window_{interval}", "CASH", INDEX, e - timedelta(days=span), e, interval)

# --- 3) futures: current + expired monthly contracts --------------------------------------------
fetch("fut_current", "FNO", CUR_FUT, *session(prev_weekday(TODAY - timedelta(days=1))), "5minute")
for label, sym in (("fut_expired_sep26", "NSE-NIFTY-29Sep26-FUT"), ("fut_expired_aug26", "NSE-NIFTY-25Aug26-FUT"),
                   ("fut_expired_jun26", "NSE-NIFTY-30Jun26-FUT")):
    exp_day = datetime.strptime(sym.split("-")[2], "%d%b%y").date()
    fetch(label, "FNO", sym, *session(prev_weekday(exp_day - timedelta(days=3))), "5minute")

# --- 4) expired options: ATM-ish strike a few days before expiry -------------------------------
# daily closes in <=170-day chunks (1day interval max window is 180 days)
closes: dict[str, float] = {}
chunk_start = date(TODAY.year - 1, 1, 1)
while chunk_start < TODAY:
    chunk_end = min(chunk_start + timedelta(days=170), TODAY)
    time.sleep(0.35)
    r = g.get_historical_candles(exchange=g.EXCHANGE_NSE, segment="CASH", groww_symbol=INDEX,
                                 start_time=f"{chunk_start} 09:15:00", end_time=f"{chunk_end} 15:30:00",
                                 candle_interval="1day", timeout=20)
    for c in r.get("candles") or []:
        closes[str(c[0])[:10]] = float(c[4])  # candle[0] is an ISO timestamp string (verified 2026-09-30)
    chunk_start = chunk_end + timedelta(days=1)


def atm_near(d: date) -> int:
    for k in range(10):
        v = closes.get((d - timedelta(days=k)).isoformat())
        if v:
            return int(round(v / 50) * 50)
    return 0


for exp in ("2026-09-29", "2026-09-22", "2026-09-01", "2026-08-25", "2026-06-30", "2026-03-30", "2025-12-30",
            "2025-10-28"):
    ed = date.fromisoformat(exp)
    strike = atm_near(ed - timedelta(days=2))
    if not strike:
        print("no index close to pick strike for", exp)
        continue
    tag = ed.strftime("%d%b%y")
    for side in ("CE", "PE"):
        fetch(f"opt_expired_{exp}", "FNO", f"NSE-NIFTY-{tag}-{strike}-{side}",
              *session(prev_weekday(ed - timedelta(days=2))), "5minute")

out = Path("data/probes")
out.mkdir(parents=True, exist_ok=True)
path = out / f"history_probe_{TODAY.isoformat()}.json"
path.write_text(json.dumps({"index_symbol": INDEX, "current_future": CUR_FUT, "results": results}, indent=1,
                           default=str), encoding="utf-8")
print("\nsaved", path)
