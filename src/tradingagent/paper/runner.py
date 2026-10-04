"""Run the paper engine live (following the recorder's files) or as a replay of a recorded day."""

import csv
import json
import time as _time
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from tradingagent.data.store import MarketStore
from tradingagent.paper.engine import PaperEngine, feed, iter_recording
from tradingagent.sim.costs import CostModel

STREAMS = ("ltp", "quotes", "chain")
LEDGER_FIELDS = ["day", "setup", "symbol", "side", "strike", "expiry", "entry_ts", "entry_px", "entry_price_source",
                 "exit_ts", "exit_px", "reason", "gross_inr", "cost_inr", "net_inr", "premium_paid_inr",
                 "stop_pct_of_premium", "risk_pct_of_equity", "net_pct_of_premium", "net_pct_of_equity",
                 "equity_at_entry"]


def load_history(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    store = MarketStore(db_path, read_only=True)
    try:
        return store.candles("NSE-NIFTY", "1minute"), store.candles("NSE-INDIAVIX", "1day")
    finally:
        store.close()


def expiry_from_recording(day_dir: Path) -> date | None:
    p = day_dir / "chain.jsonl"
    if not p.exists():
        return None
    with p.open(encoding="utf-8") as f:
        first = f.readline()
    return date.fromisoformat(json.loads(first)["expiry"]) if first.strip() else None


HOLIDAYS_FILE = Path(__file__).resolve().parents[3] / "config" / "market_holidays.yaml"


def load_holidays(path: Path = HOLIDAYS_FILE) -> frozenset[date]:
    if not path.exists():
        return frozenset()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return frozenset(d if isinstance(d, date) else date.fromisoformat(str(d)) for d in raw.get("holidays") or [])


def make_engine(day: date, day_dir: Path, db_path: Path, costs: CostModel, equity: float = 200000.0) -> PaperEngine:
    expiry = expiry_from_recording(day_dir)
    if expiry is None:
        raise RuntimeError(f"no recorder chain data in {day_dir} yet")
    hist, vix = load_history(db_path)
    eng = PaperEngine(day, hist, vix, expiry, costs, equity=equity, holidays=load_holidays())
    manifest = day_dir / "master.manifest.json"
    if manifest.exists():  # today's lot size from the Groww instrument master the recorder saved
        sizes = json.loads(manifest.read_text(encoding="utf-8")).get("option_lot_sizes") or []
        if len(sizes) == 1:
            eng.lot_size = int(sizes[0])
    return eng


def write_state(engine: PaperEngine, path: Path, extra: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**engine.state(), **(extra or {})}, default=str, indent=1), encoding="utf-8")
    tmp.replace(path)


def append_ledger(ledger: Path, trades: list[dict[str, Any]]) -> None:
    """Idempotent per (day, setup): a rerun of the same day replaces nothing already written."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    seen: set[tuple[str, str]] = set()
    if ledger.exists():
        with ledger.open(encoding="utf-8") as f:
            seen = {(r["day"], r["setup"]) for r in csv.DictReader(f)}
    new = [t for t in trades if (t["day"], t["setup"]) not in seen]
    if not new:
        return
    write_header = not ledger.exists()
    with ledger.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        w.writerows(new)


def replay(day: date, day_dir: Path, db_path: Path, costs: CostModel, equity: float = 200000.0) -> PaperEngine:
    engine = make_engine(day, day_dir, db_path, costs, equity)
    for ts, stream, r in iter_recording(day_dir):
        feed(engine, ts, stream, r)
    engine.finish_day()               # a trade still open when the recording ends is closed and recorded
    return engine


class Tail:
    """Reads only COMPLETE new lines from files that another process is still appending to."""

    def __init__(self, day_dir: Path) -> None:
        self.day_dir = day_dir
        self.pos = {s: 0 for s in STREAMS}

    def read(self) -> list[tuple[datetime, str, dict[str, Any]]]:
        out = []
        for s in STREAMS:
            p = self.day_dir / f"{s}.jsonl"
            if not p.exists():
                continue
            with p.open("rb") as f:
                f.seek(self.pos[s])
                chunk = f.read()
            if not chunk:
                continue
            end = chunk.rfind(b"\n")
            if end < 0:
                continue
            self.pos[s] += end + 1
            for line in chunk[:end].decode("utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    out.append((datetime.fromisoformat(r["recv_ts"]).replace(tzinfo=None), s, r))
        out.sort(key=lambda e: e[0])
        return out


def _shadow_runner(now: Callable[[], datetime], log: Callable[[str], None]) -> Any:
    """LLM shadow filter for live sessions (config/llm_shadow.yaml). Never used in replay: a replay would read
    today's news about a past day (look-ahead). Returns None if disabled or not importable."""
    try:
        from tradingagent.agent.shadow import Ledger, ShadowConfig, ShadowRunner
        cfg = ShadowConfig.load()
        if not cfg.enabled:
            return None
        log(f"LLM shadow filter ON ({cfg.model} via Claude Code, ≤{cfg.max_calls_per_day} calls/day) — records only.")
        return ShadowRunner(cfg, Ledger(), now, log=log)
    except Exception as e:
        log(f"LLM shadow filter unavailable (ignored): {e}")
        return None


def run_live(day: date, data_root: Path, db_path: Path, costs: CostModel, state_path: Path, ledger: Path,
             now: Callable[[], datetime], log: Callable[[str], None] = print, poll_s: float = 2.0,
             stop_at: time = time(15, 31), equity: float = 200000.0) -> PaperEngine | None:
    day_dir = data_root / f"date={day.isoformat()}"
    while not (day_dir / "chain.jsonl").exists():
        if now().time() >= stop_at:
            log("No recording today — nothing to paper trade.")
            return None
        log("Waiting for the recorder to start writing today's data…")
        _time.sleep(15)
    engine = make_engine(day, day_dir, db_path, costs, equity)
    tail = Tail(day_dir)
    log(f"Paper engine running for {day} (expiry {engine.expiry}). PAPER ONLY — no orders.")
    shadow = _shadow_runner(now, log)                 # LLM take/skip SHADOW filter (records only; live sessions only)
    while True:
        for ts, stream, r in tail.read():
            feed(engine, ts, stream, r)
        if shadow is not None:
            try:
                shadow.tick(engine)
            except Exception as e:  # the shadow filter must never stop paper trading
                log(f"LLM shadow error (ignored): {e}")
        write_state(engine, state_path, {"engine_heartbeat": now().isoformat(timespec="seconds")})
        append_ledger(ledger, engine.closed)
        if now().time() >= stop_at:
            break
        _time.sleep(poll_s)
    engine.finish_day()               # feed stopped with a trade open → close at last mark, write to ledger
    append_ledger(ledger, engine.closed)
    write_state(engine, state_path, {"engine_heartbeat": now().isoformat(timespec="seconds")})
    log(f"Paper engine stopped. Closed trades today: {len(engine.closed)}")
    return engine
