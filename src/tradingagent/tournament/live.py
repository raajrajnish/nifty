"""Live signal watcher for the intraday tournament candidates (P4, FIB71, CPR, HL1, BSE, R6).

Runs as its own process (`tradingagent tournament-live`), separate from the paper engine. It tails the recorder's
ltp.jsonl, builds 1-min bars for NIFTY / BANKNIFTY / HDFCBANK / ICICIBANK / BSE, and after every completed 5-min
bar calls each candidate's FROZEN signal function (the study code) on history + today's bars so far. A signal is
accepted only if its time is not in the future (a bar is complete). Each new signal is logged and the LLM shadow
filter is asked TAKE/SKIP at that moment (before the outcome is known). G1/G2 are handled by the paper engine's
own shadow hook. The official result of every candidate is computed after the close (tournament-eod).
"""

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, cast

import pandas as pd

from tradingagent.agent.shadow import Ledger, ShadowConfig, ShadowRunner, candidate_prompt, decide, load_events
from tradingagent.data.store import MarketStore
from tradingagent.paper.engine import MinuteBars
from tradingagent.paper.runner import Tail
from tradingagent.sim import bn_heavy, internet_study, popular_study
from tradingagent.sim import stock_study as ss
from tradingagent.sim.phase3 import close_before, p4_rel, p4_signals
from tradingagent.tournament.candidates import BY_ID

LIVE_SYMBOLS = {"NSE_NIFTY": "NSE-NIFTY", "NSE_BANKNIFTY": "NSE-BANKNIFTY", "NSE_HDFCBANK": "NSE-HDFCBANK",
                "NSE_ICICIBANK": "NSE-ICICIBANK", "NSE_BSE": "NSE-BSE"}
SIGNALS_LOG = Path(__file__).resolve().parents[3] / "data" / "paper" / "tournament_live_signals.jsonl"
HISTORY_DAYS = 420


class MemStore:
    """Minimal store for the study code: history (loaded once) + today's live bars. candles() only."""

    def __init__(self, history: dict[tuple[str, str], pd.DataFrame]) -> None:
        self.history = history
        self.today: dict[str, pd.DataFrame] = {}

    def candles(self, symbol: str, interval: str, start: datetime | None = None,
                end: datetime | None = None) -> pd.DataFrame:
        h = self.history.get((symbol, interval), pd.DataFrame(columns=["ts", "open", "high", "low", "close"]))
        t = self.today.get(symbol) if interval == "1minute" else None
        df = pd.concat([h, t], ignore_index=True) if t is not None and len(t) else h.copy()
        if start is not None:
            df = df[df["ts"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["ts"] <= pd.Timestamp(end)]
        return df.reset_index(drop=True)


def load_history(db: Path, day: date) -> dict[tuple[str, str], pd.DataFrame]:
    s = MarketStore(db, read_only=True)
    try:
        since = datetime.combine(day - timedelta(days=HISTORY_DAYS), time(0, 0))
        until = datetime.combine(day, time(0, 0))
        out = {(sym, "1minute"): s.candles(sym, "1minute", since, until) for sym in LIVE_SYMBOLS.values()}
        out[("NSE-INDIAVIX", "1day")] = s.candles("NSE-INDIAVIX", "1day")
        return out
    finally:
        s.close()


def bn_expiries(db: Path) -> list[date]:
    s = MarketStore(db, read_only=True)
    try:
        return [r[0] for r in s.con.execute("SELECT DISTINCT expiry FROM contracts WHERE kind='CE' AND "
                                            "underlying='BANKNIFTY' ORDER BY expiry").fetchall()]
    finally:
        s.close()


# ---------------------------------------------------------------------------- per-candidate live checks
Check = Callable[["Watcher", datetime], tuple[datetime, str] | None]


def _today(w: "Watcher", sym: str) -> pd.DataFrame:
    return w.mem.today.get(sym, pd.DataFrame(columns=["ts", "open", "high", "low", "close"]))


def chk_fib71(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    for _d, g, c in internet_study.contexts(w.store(), w.nifty_exps, w.day, w.day):
        e = internet_study.p5_fib71(g, c)
        return (e.signal_ts, e.side) if e is not None else None
    return None


def chk_cpr(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    for _d, g, c in popular_study.contexts(w.store(), w.nifty_exps, w.day, w.day):
        e = popular_study.k1_cpr(g, c)
        return (e.signal_ts, e.side) if e is not None else None
    return None


def chk_p4(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    if w.day in set(w.nifty_exps):        # official P4 skips Nifty expiry days
        return None
    n_t, b_t = _today(w, "NSE-NIFTY"), _today(w, "NSE-BANKNIFTY")
    if n_t.empty or b_t.empty:
        return None
    if w.p4_hist is None:                 # past days' rel rows never change during the day: compute once
        n_all = w.mem.history.get(("NSE-NIFTY", "1minute"), pd.DataFrame())
        b_all = w.mem.history.get(("NSE-BANKNIFTY", "1minute"), pd.DataFrame())
        n_by = {d: g.reset_index(drop=True) for d, g in n_all.groupby(n_all["ts"].dt.date)} if len(n_all) else {}
        b_by = {d: g.reset_index(drop=True) for d, g in b_all.groupby(b_all["ts"].dt.date)} if len(b_all) else {}
        days = [d for d in sorted(n_by) if d in b_by and (w.day - d).days <= 150]
        w.p4_hist = pd.DataFrame({d: p4_rel(n_by[d], b_by[d]) for d in days}).T.sort_index()
    rel = pd.concat([w.p4_hist, pd.DataFrame({w.day: p4_rel(n_t, b_t)}).T])
    sig = p4_signals(rel).get(w.day)
    if sig is None:
        return None
    lab, s, _ = sig
    return (datetime.combine(w.day, lab), "CE" if s > 0 else "PE") if close_before(n_t, lab) else None


def chk_hl1(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    if w.day in set(w.bn_exps):           # official HL1 skips Bank Nifty expiry days
        return None
    exp = next((e for e in w.bn_exps if e > w.day), None)
    bn, h, i = _today(w, "NSE-BANKNIFTY"), _today(w, "NSE-HDFCBANK"), _today(w, "NSE-ICICIBANK")
    if exp is None or bn.empty or h.empty or i.empty:
        return None
    e = bn_heavy.heavy_signal(w.day, bn, [h, i], exp)
    return (e.signal_ts, e.side) if e is not None else None


def chk_bse(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    m1 = w.mem.candles("NSE-BSE", "1minute")
    g = _today(w, "NSE-BSE")
    if g.empty or m1.empty:
        return None
    adj, _ev, _ex = ss.adjust_splits(ss.clean_bad_prints(m1)[0])
    rows = ss.day_table(adj)
    if w.day not in rows.index:
        return None
    g_adj = adj[adj["day"] == w.day].drop(columns="day").reset_index(drop=True)
    sig = ss.st1_orb_with_nifty(g_adj, rows.loc[w.day], _today(w, "NSE-NIFTY"))
    return (sig.ts, "LONG" if sig.side > 0 else "SHORT") if sig is not None else None


def chk_r6(w: "Watcher", now: datetime) -> tuple[datetime, str] | None:
    t = datetime.combine(w.day, time(13, 30))
    return (t, "SHORT_STRADDLE") if w.day in set(w.nifty_exps) and now >= t else None


CHECKS: dict[str, Check] = {"P4": chk_p4, "FIB71": chk_fib71, "CPR": chk_cpr, "HL1": chk_hl1, "BSE": chk_bse,
                            "R6": chk_r6}


# ---------------------------------------------------------------------------- watcher
class Watcher:
    def __init__(self, day: date, history: dict[tuple[str, str], pd.DataFrame], nifty_exps: list[date],
                 bn_exps: list[date], cfg: ShadowConfig, ledger: Ledger, now: Callable[[], datetime],
                 log: Callable[[str], None] = print, client_factory: Callable[[], Any] | None = None,
                 start_thread: Callable[[Callable[[], None]], None] | None = None,
                 signals_log: Path = SIGNALS_LOG) -> None:
        self.day, self.mem, self.nifty_exps, self.bn_exps = day, MemStore(history), nifty_exps, bn_exps
        self.cfg, self.ledger, self.now, self.log, self.signals_log = cfg, ledger, now, log, signals_log
        self.bars = {sym: MinuteBars() for sym in LIVE_SYMBOLS.values()}
        self.vix: float | None = None
        self.fired: set[str] = set()
        self.last_eval: datetime | None = None
        self.p4_hist: pd.DataFrame | None = None
        self.runner = ShadowRunner(cfg, ledger, now, client_factory, log, start_thread)

    def store(self) -> MarketStore:
        """The study code expects a MarketStore; MemStore provides the only method it uses (candles)."""
        return cast(MarketStore, self.mem)

    def on_ltp(self, ts: datetime, index: dict[str, float]) -> None:
        if index.get("NSE_INDIAVIX"):
            self.vix = float(index["NSE_INDIAVIX"])
        if not (time(9, 15) <= ts.time() <= time(15, 30)):
            return
        completed = False
        for key, sym in LIVE_SYMBOLS.items():
            px = index.get(key)
            if px and self.bars[sym].add(ts, float(px)) is not None:
                completed = True
                self.mem.today[sym] = self.bars[sym].frame()
        if completed and ts.minute % 5 == 0 and ts.replace(second=0, microsecond=0) != self.last_eval:
            self.last_eval = ts.replace(second=0, microsecond=0)
            self.evaluate(self.last_eval)

    def evaluate(self, now: datetime) -> None:
        for cid, chk in CHECKS.items():
            if cid in self.fired:
                continue
            try:
                res = chk(self, now)
            except Exception as e:  # one candidate's error must not stop the others
                self.log(f"tournament {cid} check error (ignored): {type(e).__name__}: {e}")
                continue
            if res is None or res[0] > now:
                continue
            self.fired.add(cid)
            self.signal(cid, res[0], res[1], now)

    def facts(self, cid: str, ts: datetime, side: str) -> dict[str, Any]:
        def snap(sym: str) -> dict[str, Any]:
            t = _today(self, sym)
            h = self.mem.history.get((sym, "1minute"))
            prev = float(h["close"].iloc[-1]) if h is not None and len(h) else None
            if t.empty:
                return {}
            last = float(t["close"].iloc[-1])
            return {"last": last, "open": float(t["open"].iloc[0]), "high": float(t["high"].max()),
                    "low": float(t["low"].min()), "prev_close": prev,
                    "change_pct": round((last / prev - 1) * 100, 2) if prev else None}
        f = {"candidate": cid, "date": str(self.day), "signal_time": ts.strftime("%H:%M"), "side": side,
             "instrument": BY_ID[cid].instrument, "nifty": snap("NSE-NIFTY"), "india_vix": self.vix,
             "nifty_next_expiry": str(next((e for e in self.nifty_exps if e >= self.day), ""))}
        if cid in ("HL1", "P4"):
            f |= {"banknifty": snap("NSE-BANKNIFTY"), "hdfcbank": snap("NSE-HDFCBANK"),
                  "icicibank": snap("NSE-ICICIBANK")}
        if cid == "BSE":
            f["bse_stock"] = snap("NSE-BSE")
        return f

    def signal(self, cid: str, ts: datetime, side: str, now: datetime) -> None:
        rec = {"cand": cid, "day": str(self.day), "signal_ts": ts.isoformat(), "side": side,
               "detected_at": now.isoformat()}
        self.signals_log.parent.mkdir(parents=True, exist_ok=True)
        with self.signals_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self.log(f"TOURNAMENT {cid}: {side} at {ts:%H:%M} (paper; asking the LLM — shadow only)")
        if not self.cfg.enabled or self.ledger.has(self.day, "signal", cid):
            return
        c = BY_ID[cid]
        user = candidate_prompt(cid, c.name, c.description, c.weakness, self.facts(cid, ts, side),
                                load_events(self.day))
        extra = {"signal_ts": ts.isoformat(), "side": side, "instrument": c.instrument}
        self.runner._spawn(lambda: decide("signal", self.day, cid, user, self.cfg, self.ledger, self.now,  # noqa: SLF001
                                          self.runner.client_factory, extra))


def run(day: date, data_root: Path, db: Path, nifty_exps: list[date], now: Callable[[], datetime],
        log: Callable[[str], None] = print, stop_at: time = time(15, 31), poll_s: float = 2.0) -> Watcher | None:
    import time as _time
    day_dir = data_root / f"date={day.isoformat()}"
    while not (day_dir / "ltp.jsonl").exists():
        if now().time() >= stop_at:
            log("No recording today — tournament watcher not started.")
            return None
        _time.sleep(15)
    w = Watcher(day, load_history(db, day), nifty_exps, bn_expiries(db), ShadowConfig.load(), Ledger(), now, log)
    log(f"Tournament watcher running for {day}: {', '.join(CHECKS)} (G1/G2 via the paper engine). PAPER ONLY.")
    tail = Tail(day_dir)
    while now().time() < stop_at:
        for ts, stream, r in tail.read():
            if stream == "ltp":
                w.on_ltp(ts, r.get("index") or {})
        _time.sleep(poll_s)
    log(f"Tournament watcher stopped. Live signals today: {sorted(w.fired) or 'none'}")
    return w
