"""Paper engine for G1/G2 (playbook/03_setups.md v1). PAPER ONLY — no order capability.

Data: the recorder's files (data/raw/date=YYYY-MM-DD/{ltp,quotes,chain}.jsonl), processed in time order.
The SAME signal functions as the backtest are used (sim.entry_study.e_orb / e_twap_pullback), fed only with
1-minute bars that are complete AND only up to the last complete 5-minute boundary, so a half-built 5-minute
bar can never trigger a signal. Fills use the recorded ASK (entry) and BID (exit).
"""

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from tradingagent.sim.costs import CostModel
from tradingagent.sim.entry_study import day_features, e_orb, e_twap_pullback
from tradingagent.sim.exit_study import HALF_SPREAD_PCT, LOT, Entry

EOD_EXIT = time(15, 10)
QUOTE_FRESH_S = 30

SUMMARIES = {
    "G1": ("Narrow-range opening breakout. Trades only if today opened OUTSIDE yesterday's range and the "
           "09:15–09:30 range is narrow. Buys an ATM call/put on the first 5-min close beyond that range "
           "(09:35–13:30). Exit: 5-min close beyond the OTHER side of the range, −50% premium stop, or 15:10."),
    "G2": ("TWAP trend pullback. Trades only if today opened OUTSIDE yesterday's range on a calm day "
           "(low ATR). Buys an ATM call/put when a 5-min bar pulls back to a rising/falling TWAP and closes "
           "back on the trend side (10:00–13:30). Exit: −30% premium stop or 15:10. Winners are held."),
}
STOP_PCT = {"G1": 0.50, "G2": 0.30}


@dataclass
class SetupState:
    name: str
    status: str = "WAITING_FOR_OPEN"      # WAITING_FOR_OPEN | NOT_TODAY | WATCHING | IN_TRADE | DONE | SKIPPED
    summary: str = ""
    checks: dict[str, bool | None] = field(default_factory=dict)
    waiting_for: str = ""
    trade: dict[str, Any] | None = None
    log: list[str] = field(default_factory=list)


class MinuteBars:
    """Builds 1-minute OHLC bars from ticks. A bar is complete once a tick from a later minute arrives."""

    def __init__(self) -> None:
        self.done: list[dict[str, Any]] = []
        self.cur: dict[str, Any] | None = None

    def add(self, ts: datetime, px: float) -> dict[str, Any] | None:
        m = ts.replace(second=0, microsecond=0)
        if self.cur is None or m > self.cur["ts"]:
            finished = self.cur
            self.cur = {"ts": m, "open": px, "high": px, "low": px, "close": px}
            if finished is not None:
                self.done.append(finished)
                return finished
            return None
        if m == self.cur["ts"]:
            self.cur["high"] = max(self.cur["high"], px)
            self.cur["low"] = min(self.cur["low"], px)
            self.cur["close"] = px
        return None

    def frame(self, before: datetime | None = None) -> pd.DataFrame:
        df = pd.DataFrame(self.done, columns=["ts", "open", "high", "low", "close"])
        return df if before is None else df[df["ts"] < before].reset_index(drop=True)


def previous_trading_day(day: date, holidays: frozenset[date] = frozenset()) -> date:
    d = day - timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d -= timedelta(days=1)
    return d


class PaperEngine:
    def __init__(self, day: date, history: pd.DataFrame, vix_daily: pd.DataFrame, expiry: date,
                 costs: CostModel, equity: float = 200000.0, holidays: frozenset[date] = frozenset()) -> None:
        """history: stored NIFTY 1-min candles BEFORE `day`. equity: trading money at the start of the day —
        trade risk and P&L are also reported as % of it (risk.yaml: all limits are percentages).
        holidays: NSE market holidays (config/market_holidays.yaml) — used to know the previous trading day."""
        self.day = day
        self.equity = equity
        self.lot_size = LOT                     # shown on the UI; runner sets it from the day's instrument master
        self.vix: float | None = None
        self.hist = history[history["ts"].dt.date < day].copy()
        self.vix_daily = vix_daily
        self.expiry = expiry
        self.costs = costs
        self.bars = MinuteBars()
        self.quotes: dict[str, dict[str, Any]] = {}       # symbol → {bid, ask, ltp, ts}
        self.symbols: dict[tuple[int, str], str] = {}     # (strike, CE/PE) → trading symbol
        self.index_px: float | None = None
        self.last_ts: datetime | None = None
        self.closed: list[dict[str, Any]] = []
        self.s = {k: SetupState(k, summary=SUMMARIES[k]) for k in ("G1", "G2")}
        self._feats_ready = False
        self._g1_or: tuple[float, float] | None = None
        # History must end on the PREVIOUS TRADING DAY, otherwise "yesterday" (PDH/PDL, OR median, ATR) is
        # silently an older day (independent review 2026-10-02, finding 6). Fails safe: an unlisted holiday
        # makes the engine skip the day with a clear message rather than trade on the wrong "yesterday".
        last_hist_day = self.hist["ts"].dt.date.max() if len(self.hist) else None
        prev_td = previous_trading_day(day, holidays)
        if last_hist_day is None or last_hist_day < prev_td:
            self.history_note = (f"history ends {last_hist_day}, but the previous trading day is {prev_td} — run "
                                 f"End of Day.cmd / fetch-history (if {prev_td} was a market holiday, add it to "
                                 f"config/market_holidays.yaml)")
        else:
            self.history_note = ""
        if day == expiry:
            for st in self.s.values():
                self._set(st, "SKIPPED", "Expiry day — no trades (risk.yaml expiry_day.allowed=false).")
        elif self.history_note:
            for st in self.s.values():
                self._set(st, "SKIPPED", f"Data problem: {self.history_note}.")

    # ---- helpers -------------------------------------------------------------------------------------
    def _log(self, st: SetupState, msg: str) -> None:
        stamp = self.last_ts.strftime("%H:%M:%S") if self.last_ts else "--:--:--"
        st.log.append(f"{stamp} {msg}")

    def _set(self, st: SetupState, status: str, msg: str) -> None:
        st.status = status
        if status in ("NOT_TODAY", "SKIPPED", "DONE"):
            st.waiting_for = ""  # nothing left to wait for
        self._log(st, msg)

    def _today_and_history(self) -> pd.DataFrame:
        today = self.bars.frame()
        full = pd.concat([self.hist[["ts", "open", "high", "low", "close"]], today], ignore_index=True)
        full["day"] = full["ts"].dt.date
        return full

    def _quote(self, symbol: str) -> dict[str, Any] | None:
        return self.quotes.get(symbol)

    def _price(self, symbol: str, side: str) -> tuple[float | None, str]:
        """side='buy' → ask; 'sell' → bid. Falls back to LTP ± half-spread if the quote is stale."""
        q = self._quote(symbol)
        if q is None or self.last_ts is None:
            return None, "no quote"
        fresh = (self.last_ts - q["ts"]).total_seconds() <= QUOTE_FRESH_S
        px = q.get("ask") if side == "buy" else q.get("bid")
        if fresh and px:
            return float(px), "quote"
        if q.get("ltp"):
            ltp = float(q["ltp"])
            return (ltp * (1 + HALF_SPREAD_PCT) if side == "buy" else ltp * (1 - HALF_SPREAD_PCT)), "ltp±half-spread"
        return None, "no price"

    # ---- data input ----------------------------------------------------------------------------------
    def on_chain(self, ts: datetime, strikes: dict[str, Any]) -> None:
        for k, sides in strikes.items():
            for side, v in (sides or {}).items():
                if v and v.get("trading_symbol"):
                    self.symbols[(int(float(k)), side)] = v["trading_symbol"]

    def on_quote(self, ts: datetime, symbol: str, bid: float | None, ask: float | None, ltp: float | None) -> None:
        self.last_ts = ts
        self.quotes[symbol] = {"bid": bid, "ask": ask, "ltp": ltp, "ts": ts}
        self._check_stops()
        self._time_exit()

    def on_ltp(self, ts: datetime, index_px: float | None, fno: dict[str, float], vix: float | None = None) -> None:
        self.last_ts = ts
        if vix:
            self.vix = vix
        for k, v in fno.items():
            sym = k.removeprefix("NSE_")
            q = self.quotes.setdefault(sym, {"bid": None, "ask": None, "ltp": None, "ts": ts})
            q["ltp"] = v
        # pre-open (before 09:15) index prints are not trades — they must not become today's "open"
        if index_px and time(9, 15) <= ts.time() <= time(15, 30):
            self.index_px = index_px
            finished = self.bars.add(ts, index_px)
            if finished is not None:
                self._on_minute(finished)
        self._check_stops()
        self._time_exit()

    def _time_exit(self) -> None:
        """15:10 exit driven by ANY event's clock, not only by completed index minutes: if the index feed
        stops (as on 2025-09-26), quote/option ticks still close open trades (review finding 5)."""
        if self.last_ts is None or self.last_ts.time() < time(15, 10):
            return
        for st in self.s.values():
            if st.status == "IN_TRADE" and st.trade:
                self._exit(st, "EOD_1510")

    def finish_day(self) -> None:
        """Called by the runner when the session/recording ends: any trade still open (no data at all after the
        last tick) is closed at its last mark so it always reaches the ledger."""
        for st in self.s.values():
            if st.status == "IN_TRADE" and st.trade:
                self._exit(st, "EOD_NO_DATA")

    # ---- per completed minute ------------------------------------------------------------------------
    def _on_minute(self, bar: dict[str, Any]) -> None:
        t: datetime = bar["ts"]
        if not self._feats_ready and t.time() >= time(9, 15):
            self._day_checks()
        if t.time() >= time(9, 29):
            self._g1_checks()
        # truncate to the last COMPLETE 5-minute boundary so partial 5-min bars cannot fire a signal
        nxt = t + timedelta(minutes=1)
        cut = nxt - timedelta(minutes=nxt.minute % 5)
        bars = self.bars.frame(before=cut)
        for name in ("G1", "G2"):
            st = self.s[name]
            if st.status == "WATCHING":
                self._look_for_entry(name, bars)
            elif st.status == "IN_TRADE":
                self._manage(name, bar)

    def _day_checks(self) -> None:
        self._feats_ready = True
        if self.bars.done[0]["ts"].time() > time(9, 16):
            for st in self.s.values():
                if st.status != "SKIPPED":
                    self._set(st, "SKIPPED", f"Recording started late ({self.bars.done[0]['ts']:%H:%M}) — "
                              "today's open is unknown, so the day conditions cannot be checked.")
            return
        full = self._today_and_history()
        prev = self.hist[self.hist["ts"].dt.date == self.hist["ts"].dt.date.max()]
        pdh, pdl = float(prev["high"].max()), float(prev["low"].min())
        first_open = float(self.bars.done[0]["open"])
        outside = first_open > pdh or first_open < pdl
        feats = day_features(full)  # same feature code as the studies (past-only)
        low_vol = feats.at[self.day, "high_vol"] == False  # noqa: E712
        where = "above yesterday's high" if first_open > pdh else "below yesterday's low" if first_open < pdl \
            else "inside yesterday's range"
        for name, st in self.s.items():
            if st.status == "SKIPPED":
                continue
            st.checks["not expiry day"] = True
            st.checks["opened outside yesterday's range"] = outside
            if name == "G2":
                st.checks["calm day (ATR14 ≤ 120-day median)"] = bool(low_vol)
            self._log(st, f"Open {first_open:,.2f} is {where} (PDH {pdh:,.2f}, PDL {pdl:,.2f}).")
            if not outside:
                self._set(st, "NOT_TODAY", "Not today: opened inside yesterday's range.")
            elif name == "G2" and not low_vol:
                self._set(st, "NOT_TODAY", "Not today: market not calm (ATR14 above its 120-day median).")
            elif name == "G2":
                st.waiting_for = "From 10:00: a 5-min pullback to TWAP that closes back on the trend side."
                self._set(st, "WATCHING", "Day conditions met — watching for a TWAP pullback from 10:00.")
            else:
                st.waiting_for = "Waiting for the opening range (09:15–09:30) to finish."
                self._set(st, "WATCHING", "Day conditions met so far — building the opening range.")

    def _g1_checks(self) -> None:
        st = self.s["G1"]
        if self._g1_or is not None or st.status != "WATCHING":
            return
        full = self._today_and_history()
        feats = day_features(full)
        o = self.bars.frame()
        o = o[o["ts"].dt.time < time(9, 30)]
        if len(o) < 10:
            return
        hi, lo = float(o["high"].max()), float(o["low"].min())
        self._g1_or = (hi, lo)
        narrow = bool(feats.at[self.day, "narrow_or"])
        st.checks["narrow opening range (< 20-day median)"] = narrow
        if not narrow:
            self._set(st, "NOT_TODAY", f"Not today: opening range {lo:,.2f}–{hi:,.2f} is not narrow.")
            return
        st.waiting_for = (f"A 5-min close above {hi:,.2f} → buy CALL, or below {lo:,.2f} → buy PUT "
                          f"(09:35–13:30).")
        self._log(st, f"Opening range {lo:,.2f}–{hi:,.2f} is narrow — watching for a breakout.")

    def _look_for_entry(self, name: str, bars: pd.DataFrame) -> None:
        if bars.empty:
            return
        ctx = {"day": self.day, "gap_pct": None, "ema5": None}
        if name == "G1":
            if self._g1_or is None:
                return
            e = e_orb(15)(bars, ctx, [self.expiry])
        else:
            e = e_twap_pullback(bars, ctx, [self.expiry])
            if e is None and self.last_ts and self.last_ts.time() >= time(10, 0):
                tw = float(bars["close"].mean())
                self.s[name].waiting_for = (f"TWAP now {tw:,.2f}. Waiting for a 5-min bar to touch it and close back "
                                            f"on the trend side (until 13:30).")
        if e is None:
            if self.last_ts and self.last_ts.time() > time(13, 30):
                self._set(self.s[name], "DONE", "No signal by 13:30 — no trade today.")
                self.s[name].waiting_for = ""
            return
        self._enter(name, e)

    def _enter(self, name: str, e: Entry) -> None:
        st = self.s[name]
        sym = self.symbols.get((e.strike, e.side))
        if sym is None:
            self._set(st, "SKIPPED", f"Signal {e.side} {e.strike} but contract not in the recorder's strike list.")
            return
        px, how = self._price(sym, "buy")
        if px is None:
            self._set(st, "SKIPPED", f"Signal {e.side} {e.strike} but no price for {sym} ({how}).")
            return
        stop = px * (1 - STOP_PCT[name])
        entry_ts = self.last_ts.isoformat() if self.last_ts else None
        st.trade = {"symbol": sym, "side": e.side, "strike": e.strike, "expiry": str(self.expiry),
                    "signal_ts": e.signal_ts.isoformat(), "entry_ts": entry_ts,
                    "entry_px": round(px, 2), "entry_price_source": how, "stop_px": round(stop, 2),
                    "or_high": e.or_high, "or_low": e.or_low, "mark_px": round(px, 2), "pnl_inr": 0.0,
                    "peak_pnl_inr": 0.0, "lots": 1, "qty": LOT,
                    "premium_paid_inr": round(px * LOT, 1), "stop_pct_of_premium": STOP_PCT[name] * 100,
                    "risk_inr": round((px - stop) * LOT, 1),
                    "risk_pct_of_equity": round((px - stop) * LOT / self.equity * 100, 2),
                    "pnl_pct_of_premium": 0.0, "pnl_pct_of_equity": 0.0, "equity_at_entry": self.equity}
        if name == "G1":
            inv = e.or_low if e.side == "CE" else e.or_high
            st.trade["invalidation"] = f"5-min close {'below' if e.side == 'CE' else 'above'} {inv:,.2f}"
        st.waiting_for = ""
        self._set(st, "IN_TRADE", f"ENTERED {sym} at ₹{px:,.2f} ({how}); stop ₹{stop:,.2f} "
                  f"(−{STOP_PCT[name] * 100:.0f}% of premium = {st.trade['risk_pct_of_equity']:.2f}% of equity)"
                  + (f"; exit if {st.trade['invalidation']}" if name == "G1" else "") + ".")

    def _mark(self, st: SetupState) -> None:
        tr = st.trade
        if not tr:
            return
        px, how = self._price(tr["symbol"], "sell")
        if px is None:
            return
        tr["mark_px"] = round(px, 2)
        tr["mark_source"] = how
        tr["pnl_inr"] = round((px - tr["entry_px"]) * LOT, 1)
        tr["peak_pnl_inr"] = max(tr["peak_pnl_inr"], tr["pnl_inr"])
        tr["pnl_pct_of_premium"] = round((px / tr["entry_px"] - 1) * 100, 1)
        tr["pnl_pct_of_equity"] = round(tr["pnl_inr"] / self.equity * 100, 2)
        if self.last_ts and tr.get("entry_ts"):
            tr["minutes_held"] = int((self.last_ts - datetime.fromisoformat(tr["entry_ts"])).total_seconds() // 60)

    def _check_stops(self) -> None:
        for st in self.s.values():
            if st.status != "IN_TRADE" or not st.trade:
                continue
            self._mark(st)
            if st.trade["mark_px"] <= st.trade["stop_px"]:
                self._exit(st, "STOP")

    def _manage(self, name: str, bar: dict[str, Any]) -> None:
        st = self.s[name]
        tr = st.trade
        if not tr:
            return
        t: datetime = bar["ts"]
        if t.time() >= time(15, 9):  # the 15:09 bar completes at 15:10
            self._exit(st, "EOD_1510")
            return
        if name == "G1" and t.minute % 5 == 4:  # completes a 5-min bar
            five = self.bars.frame(before=t + timedelta(minutes=1)).tail(5)
            close5 = float(five["close"].iloc[-1])
            failed = close5 < tr["or_low"] if tr["side"] == "CE" else close5 > tr["or_high"]
            if failed:
                self._exit(st, "OR_OPPOSITE_SIDE")

    def _exit(self, st: SetupState, reason: str) -> None:
        tr = st.trade
        if not tr:
            return
        self._mark(st)
        px = tr["mark_px"]
        c = self.costs.round_trip(tr["entry_px"], px, LOT).total
        gross = (px - tr["entry_px"]) * LOT
        net = gross - c
        result = {**tr, "setup": st.name, "day": str(self.day), "exit_ts": self.last_ts.isoformat() if self.last_ts
                  else None, "exit_px": px, "reason": reason, "gross_inr": round(gross, 1),
                  "cost_inr": round(c, 1), "net_inr": round(net, 1),
                  "net_pct_of_premium": round(net / (tr["entry_px"] * LOT) * 100, 1),
                  "net_pct_of_equity": round(net / self.equity * 100, 2)}
        self.closed.append(result)
        st.trade = result
        self._set(st, "DONE", f"EXITED ({reason}) at ₹{px:,.2f}: net {result['net_pct_of_premium']:+.1f}% of premium "
                  f"= {result['net_pct_of_equity']:+.2f}% of equity (₹{gross - c:,.0f} after ₹{c:,.0f} costs).")

    # ---- output -------------------------------------------------------------------------------------
    def market(self) -> dict[str, Any]:
        """What the market looks like right now — for the dashboard (no decisions are made from this)."""
        prev = self.hist[self.hist["ts"].dt.date == self.hist["ts"].dt.date.max()] if len(self.hist) else self.hist
        prev_close = float(prev["close"].iloc[-1]) if len(prev) else None
        bars = self.bars.done + ([self.bars.cur] if self.bars.cur else [])
        idx = self.index_px
        atm = int(round(idx / 50) * 50) if idx else None
        legs: dict[str, Any] = {}
        for side in ("CE", "PE"):
            sym = self.symbols.get((atm, side)) if atm else None
            q = self.quotes.get(sym) if sym else None
            ask = (q or {}).get("ask") or (q or {}).get("ltp")
            legs[side] = {"symbol": sym, "bid": (q or {}).get("bid"), "ask": (q or {}).get("ask"),
                          "ltp": (q or {}).get("ltp"),
                          "one_lot_cost_inr": round(float(ask) * self.lot_size, 0) if ask else None}
        o = [b for b in self.bars.done if b["ts"].time() < time(9, 30)]
        return {
            "index": idx, "prev_close": prev_close,
            "change_pts": round(idx - prev_close, 2) if idx and prev_close else None,
            "change_pct": round((idx / prev_close - 1) * 100, 2) if idx and prev_close else None,
            "day_open": bars[0]["open"] if bars else None,
            "day_high": max(b["high"] for b in bars) if bars else None,
            "day_low": min(b["low"] for b in bars) if bars else None,
            "pdh": float(prev["high"].max()) if len(prev) else None,
            "pdl": float(prev["low"].min()) if len(prev) else None,
            "or_high": max(b["high"] for b in o) if len(o) >= 15 else None,
            "or_low": min(b["low"] for b in o) if len(o) >= 15 else None,
            "twap": round(sum(b["close"] for b in self.bars.done) / len(self.bars.done), 2) if self.bars.done else None,
            "vix": self.vix, "atm_strike": atm, "atm": legs, "lot_size": self.lot_size, "expiry": str(self.expiry),
            # IST wall-clock encoded as if UTC: chart axes render UTC, so 09:15 shows as 09:15 on any machine
            "bars": [[calendar.timegm(b["ts"].timetuple()), b["open"], b["high"], b["low"], b["close"]] for b in bars],
        }

    def state(self) -> dict[str, Any]:
        return {"day": str(self.day), "as_of": self.last_ts.isoformat() if self.last_ts else None,
                "equity_start_of_day": self.equity,
                "index": self.index_px, "expiry": str(self.expiry), "history_note": self.history_note,
                "mode": "PAPER_ONLY",
                "setups": {k: {"status": v.status, "summary": v.summary, "checks": v.checks,
                               "waiting_for": v.waiting_for, "trade": v.trade, "log": v.log[-30:]}
                           for k, v in self.s.items()},
                "closed_today": self.closed, "market": self.market()}


def iter_recording(day_dir: Any) -> list[tuple[datetime, str, dict[str, Any]]]:
    """All events of a recorded day (ltp, quotes, chain), sorted by receive time."""
    events: list[tuple[datetime, str, dict[str, Any]]] = []
    for stream in ("ltp", "quotes", "chain"):
        p = day_dir / f"{stream}.jsonl"
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    events.append((datetime.fromisoformat(r["recv_ts"]).replace(tzinfo=None), stream, r))
    events.sort(key=lambda e: e[0])
    return events


def feed(engine: PaperEngine, ts: datetime, stream: str, r: dict[str, Any]) -> None:
    if stream == "chain":
        engine.on_chain(ts, r.get("strikes") or {})
    elif stream == "quotes":
        engine.on_quote(ts, r["symbol"], r.get("bid"), r.get("ask"), r.get("ltp"))
    elif stream == "ltp":
        ix = r.get("index") or {}
        engine.on_ltp(ts, ix.get("NSE_NIFTY"), r.get("fno") or {}, ix.get("NSE_INDIAVIX"))
