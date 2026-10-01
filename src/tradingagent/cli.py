"""Entry points. Composition root for Phase 0: wires config, clock, bus, logger, auth, runtime, UI."""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from tradingagent.broker.auth import GrowwAuth
from tradingagent.config import load_config
from tradingagent.core.clock import WallClock
from tradingagent.core.errors import ConfigError
from tradingagent.core.events import EventBus
from tradingagent.journal.logger import EventLogger
from tradingagent.orchestrator.runtime import Runtime

ROOT = Path.cwd()
RUNTIME_DIR = ROOT / "runtime"
UI_AUTH_FILE = RUNTIME_DIR / "ui_auth.json"


def build_runtime() -> Runtime:
    load_dotenv(ROOT / ".env")
    cfg = load_config(ROOT / "config")
    clock = WallClock()
    bus = EventBus()
    bus.subscribe(EventLogger(ROOT / "journal" / "events", {
        "mode": cfg.stage.mode.value, "stage": cfg.stage.stage.value, "config_hash": cfg.config_hash}))
    return Runtime(cfg, clock, bus, GrowwAuth(clock), RUNTIME_DIR)


def cmd_ui(args: argparse.Namespace) -> int:
    import uvicorn

    from tradingagent.orchestrator.demo import run_demo_feed
    from tradingagent.ui.app import create_app
    from tradingagent.ui.auth import SessionStore

    rt = build_runtime()
    sessions = SessionStore(UI_AUTH_FILE, rt.cfg.ui.session_hours)
    if rt.cfg.ui.require_login and not sessions.configured:
        print("No dashboard passphrase set. Run: uv run tradingagent ui-set-passphrase")
        return 1
    async def _auto_connect() -> None:  # use today's token from .env without a manual click
        broker = await rt.connect_broker(source="startup")
        print("Groww connected." if broker["connected"] else f"Groww NOT connected: {broker['error']}")

    background = [_auto_connect] + ([lambda: run_demo_feed(rt.bus)] if args.demo else [])
    app = create_app(rt, sessions, background=background)
    (RUNTIME_DIR / "ui.pid").write_text(str(os.getpid()), encoding="utf-8")
    print(f"Dashboard: http://{rt.cfg.ui.host}:{rt.cfg.ui.port}  (stage {rt.cfg.stage.stage}, "
          f"mode {rt.cfg.stage.mode}{', DEMO feed' if args.demo else ''})")
    uvicorn.run(app, host=rt.cfg.ui.host, port=rt.cfg.ui.port, log_level="warning")
    return 0


def cmd_set_passphrase(_: argparse.Namespace) -> int:
    from tradingagent.ui.auth import set_passphrase

    p1 = getpass.getpass("New dashboard passphrase (min 10 chars): ")
    if p1 != getpass.getpass("Repeat: "):
        print("Passphrases do not match.")
        return 1
    try:
        set_passphrase(UI_AUTH_FILE, p1)
    except ValueError as e:
        print(e)
        return 1
    print(f"Saved (hashed) to {UI_AUTH_FILE}")
    return 0


def cmd_auth(_: argparse.Namespace) -> int:
    rt = build_runtime()
    broker = asyncio.run(rt.connect_broker(source="cli"))
    print("Groww connected." if broker["connected"] else f"Groww NOT connected: {broker['error']}")
    return 0 if broker["connected"] else 2


def cmd_check_config(_: argparse.Namespace) -> int:
    try:
        cfg = load_config(ROOT / "config")
    except ConfigError as e:
        print(f"INVALID: {e}")
        return 1
    print(f"OK {cfg.config_hash}  stage={cfg.stage.stage} mode={cfg.stage.mode}")
    print(f"per-trade risk ₹{cfg.risk.per_trade_risk_inr:,.0f}, daily loss limit ₹{cfg.risk.daily_loss_limit_inr:,.0f}")
    if tbd := cfg.tbd_fields():
        print(f"TBD ({len(tbd)}) — PAPER/LIVE will refuse to start until filled:")
        for f in tbd:
            print(f"  - {f}")
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    from tradingagent.broker.groww_adapter import GrowwMarketData
    from tradingagent.data.recorder import Recorder, RecorderConfig

    load_dotenv(ROOT / ".env")
    clock = WallClock()
    auth = GrowwAuth(clock)  # own auth instance: the token never passes through Runtime (which the UI uses)
    auth_st = auth.acquire()
    if not auth_st.connected:
        print(f"Groww NOT connected: {auth_st.error}")
        return 2
    src = GrowwMarketData(auth.token(), max_requests_per_second=args.rps)
    rec = Recorder(src, RecorderConfig(), clock, ROOT / "data" / "raw", RUNTIME_DIR / "recorder_status.json")
    print(f"Recording NIFTY (read-only) until {RecorderConfig().stop:%H:%M}. Ctrl+C to stop.")
    try:
        st = rec.run()
    except KeyboardInterrupt:
        rec.status.running = False
        rec._save_status()  # noqa: SLF001
        st = rec.status
    print(f"Stopped. rows={st.counts} bytes={st.bytes} errors={st.errors}")
    return 0


def cmd_analyze_day(args: argparse.Namespace) -> int:
    import json

    from tradingagent.data.analyze import analyze

    day_dir = ROOT / "data" / "raw" / f"date={args.day}"
    if not day_dir.exists():
        print(f"No recorded data for {args.day} ({day_dir})")
        return 1
    status_file = RUNTIME_DIR / "recorder_status.json"
    status = json.loads(status_file.read_text(encoding="utf-8")) if status_file.exists() else None
    if status and status.get("session_date") != args.day:
        status = None
    out = ROOT / "data" / "reports" / f"date={args.day}"
    m = analyze(day_dir, out, status)
    print(json.dumps(m, indent=2, default=str))
    print(f"\nWritten to {out}")
    return 0


DB_PATH = ROOT / "data" / "market.duckdb"


def cmd_fetch_history(args: argparse.Namespace) -> int:
    from datetime import date, datetime, time, timedelta

    from tradingagent.broker.groww_adapter import GrowwMarketData
    from tradingagent.data.history import FetchAborted, HistoryDownloader
    from tradingagent.data.store import MarketStore

    load_dotenv(ROOT / ".env")
    clock = WallClock()
    auth = GrowwAuth(clock)
    auth_st = auth.acquire()
    if not auth_st.connected:
        print(f"Groww NOT connected: {auth_st.error}")
        return 2
    now = clock.now()
    last_day = now.date() if now.time() >= time(15, 40) else now.date() - timedelta(days=1)
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end) if args.end else last_day
    log_path = ROOT / "data" / "fetch_history.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {msg}"
        print(line, flush=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    store = MarketStore(DB_PATH)
    dl = HistoryDownloader(GrowwMarketData(auth.token(), max_requests_per_second=args.rps), store, last_day, log)
    log(f"fetch-history {args.underlying} {start}..{end} strikes±{args.strikes} → {DB_PATH} (read-only)")
    try:
        dl.download_index(args.underlying, start, end)
        if not args.index_only:
            dl.download_options(args.underlying, start, end, strikes_each_side=args.strikes)
    except KeyboardInterrupt:
        log("interrupted — rerun the same command to resume (stored days are skipped)")
    except FetchAborted as e:
        log(f"STOPPED: {e}")
    finally:
        s = dl.stats
        log(f"done: requests={s.requests} candles_added={s.candles} skipped_days={s.skipped_days} "
            f"errors={s.errors} contracts={s.contracts}")
        print(store.summary().to_string(index=False))
        print(store.coverage_summary().to_string(index=False))
        store.close()
    return 0


def cmd_db_summary(_: argparse.Namespace) -> int:
    from tradingagent.data.store import MarketStore

    if not DB_PATH.exists():
        print("No database yet — run: uv run tradingagent fetch-history")
        return 1
    store = MarketStore(DB_PATH)
    print(store.summary().to_string(index=False))
    print(store.coverage_summary().to_string(index=False))
    print(f"file: {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB)")
    store.close()
    return 0


def cmd_backtest_exits(args: argparse.Namespace) -> int:
    from datetime import datetime

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.exit_study import run_study

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"exits_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        for mult in (1.0, 2.0):
            trades, summary = run_study(store, CostModel(cfg.costs), cost_mult=mult)
            tag = "costs1x" if mult == 1.0 else "costs2x"
            trades.to_csv(out / f"trades_{tag}.csv", index=False)
            summary.to_csv(out / f"summary_{tag}.csv", index=False)
            print(f"\n===== costs × {mult:g} =====")
            print(summary.to_string(index=False, max_colwidth=24))
    finally:
        store.close()
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_entries(_: argparse.Namespace) -> int:
    from datetime import datetime

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.entry_study import run_entry_study

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"entries_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        trades, summary = run_entry_study(store, CostModel(cfg.costs))
    finally:
        store.close()
    trades.to_csv(out / "trades.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    print(summary.head(40).to_string(index=False))
    print(f"\ncells: {len(summary)}  passing: {int(summary['PASS'].sum())}\nWritten to {out}")
    return 0


def cmd_backtest_stops(_: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.stop_study import SETUPS, pick_stop, run_stop_study

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"stops_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        trades, summary, killed = run_stop_study(store, CostModel(cfg.costs))
    finally:
        store.close()
    trades.to_csv(out / "trades.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    killed.to_csv(out / "killed_winners.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 40):
        print("=== killed winners (no-stop runs) ===\n" + killed.to_string(index=False))
        print("\n=== stop sweep ===\n" + summary.to_string(index=False))
        picks = pd.DataFrame([pick_stop(summary, s, x) for s in SETUPS for x in ("own_rule", "hold_1510")])
        print("\n=== stop chosen on DEV, checked on validate/test ===\n" + picks.to_string(index=False))
        picks.to_csv(out / "picks.csv", index=False)
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_risk(args: argparse.Namespace) -> int:
    import glob
    import json

    import pandas as pd

    from tradingagent.sim.risk_study import (
        CHOSEN,
        cap_table,
        daily,
        day_profile,
        monte_carlo,
        per_setup,
        pick,
        pick_logic,
    )

    pattern = "logic_*" if args.g_rules else "stops_*"
    runs = sorted(glob.glob(str(ROOT / "data" / "reports" / "backtests" / pattern)))
    if not runs:
        print(f"Run the study that produces {pattern} first.")
        return 1
    src = Path(runs[-1])
    if args.g_rules:
        t = pick_logic(pd.read_csv(src / "trades.csv"))
        print(f"Source: {src.name} | G1 = S1 on open-outside days, G2 = S2 on open-outside days")
    else:
        t = pick(pd.read_csv(src / "trades.csv"))
        names = ", ".join(f"{c.name}={c.setup}/{c.exit_mode}/{c.stop}" for c in CHOSEN)
        print(f"Source: {src.name} | setups: {names}")
    with pd.option_context("display.width", 220, "display.max_columns", 30):
        print("\n=== per setup (1 lot) ===\n" + per_setup(t).to_string(index=False))
        print("\n=== combined daily profile ===\n" + json.dumps(day_profile(t), indent=1))
        caps = cap_table(t)
        print("\n=== daily loss cap what-if ===\n" + caps.to_string(index=False))
        mc = monte_carlo(daily(t))
        print("\n=== Monte Carlo (10,000 reshuffles of day order) ===\n" + json.dumps(mc, indent=1))
    out = src / "risk"
    out.mkdir(exist_ok=True)
    per_setup(t).to_csv(out / "per_setup.csv", index=False)
    caps.to_csv(out / "caps.csv", index=False)
    (out / "summary.json").write_text(json.dumps({"day_profile": day_profile(t), "monte_carlo": mc}, indent=1,
                                                 default=str), encoding="utf-8")
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_timing(_: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.timing_study import run_timing_study, verdict

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"timing_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        trades, summary = run_timing_study(store, CostModel(cfg.costs))
    finally:
        store.close()
    v = verdict(summary)
    trades.to_csv(out / "trades.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    v.to_csv(out / "verdict.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 30):
        print(summary.to_string(index=False))
        print("\n=== pre-declared verdict (vs current rule A) ===\n" + v.to_string(index=False))
    print(f"\nWritten to {out}")
    return 0


def cmd_scorecard(_: argparse.Namespace) -> int:
    import glob

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.scorecard import build, relationships, scorecard

    runs = sorted(glob.glob(str(ROOT / "data" / "reports" / "backtests" / "stops_*")))
    if not runs:
        print("Run `tradingagent backtest-stops` first.")
        return 1
    src = Path(runs[-1])
    store = MarketStore(DB_PATH)
    try:
        m = build(store, pd.read_csv(src / "trades.csv"))
    finally:
        store.close()
    out = src / "scorecard"
    out.mkdir(exist_ok=True)
    m.to_csv(out / "trade_metrics.csv", index=False)
    sc = scorecard(m)
    sc.to_csv(out / "scorecard.csv", index=False)
    rel = relationships(m)
    with pd.option_context("display.width", 260, "display.max_columns", 40):
        print("=== SCORECARD (rows = setup; RANDOM = no-skill yardstick) ===")
        print(sc.set_index("variant").T.to_string())
        for title, table in rel.items():
            print(f"\n--- {title} ---\n{table.to_string()}")
            table.to_csv(out / (title.replace(":", "").replace(" ", "_").replace("→", "to")[:80] + ".csv"))
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_followthrough(_: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.followthrough_study import cut_analysis, run_followthrough, verdict_ft

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"followthrough_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        trades, summary = run_followthrough(store, CostModel(cfg.costs))
    finally:
        store.close()
    cuts, v = cut_analysis(trades), verdict_ft(summary)
    trades.to_csv(out / "trades.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    cuts.to_csv(out / "cuts.csv", index=False)
    v.to_csv(out / "verdict.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 30):
        print(summary.drop(columns=["median_delay_min"]).to_string(index=False))
        print("\n=== cuts ===\n" + cuts.to_string(index=False))
        print("\n=== pre-declared verdict ===\n" + v.to_string(index=False))
        print(f"\nADOPT FT-15: {v.attrs['ADOPT_FT15']}")
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_logic(_: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.logic_study import build_trades, decide, feature_table

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    out = ROOT / "data" / "reports" / "backtests" / f"logic_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    try:
        trades = build_trades(store, CostModel(cfg.costs))
    finally:
        store.close()
    table, verdict = feature_table(trades), None
    verdict = decide(table)
    trades.to_csv(out / "trades.csv", index=False)
    table.to_csv(out / "features.csv", index=False)
    verdict.to_csv(out / "verdict.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 30, "display.max_rows", 200):
        print(table.to_string(index=False))
        print("\n=== pre-declared verdict ===\n" + verdict.to_string(index=False))
    print(f"\nWritten to {out}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    import json
    from datetime import date

    from tradingagent.paper.runner import append_ledger, replay, run_live, write_state
    from tradingagent.sim.costs import CostModel

    cfg = load_config(ROOT / "config")
    costs = CostModel(cfg.costs)
    clock = WallClock()
    day = date.fromisoformat(args.day) if args.day else clock.now().date()
    from tradingagent.paper.account import equity_from_ledger

    data_root = ROOT / "data" / "raw"
    ledger = ROOT / "data" / "paper" / "live_trades.csv"
    eq = equity_from_ledger(cfg.risk.capital_inr, ledger, day.isoformat())
    start_equity = cfg.risk.base(eq.start_of_day)
    print(f"Equity at start of {day}: ₹{start_equity:,.0f} (start capital ₹{cfg.risk.capital_inr:,.0f}, "
          f"realised so far ₹{eq.start_of_day - cfg.risk.capital_inr:,.0f}; basis={cfg.risk.capital_basis})")
    if args.replay:
        eng = replay(day, data_root / f"date={day.isoformat()}", DB_PATH, costs, start_equity)
        out = ROOT / "data" / "paper" / f"replay_{day.isoformat()}.json"
        write_state(eng, out, {"replay": True})
        if args.record:
            append_ledger(ledger, eng.closed)
        st = eng.state()
        for name, s in st["setups"].items():
            print(f"\n=== {name}: {s['status']} ===")
            print("checks:", json.dumps(s["checks"]))
            for line in s["log"]:
                print("  " + line)
        print(f"\nClosed trades: {len(eng.closed)}  → {out}")
        return 0
    run_live(day, data_root, DB_PATH, costs, RUNTIME_DIR / "paper_state.json", ledger,
             now=lambda: clock.now().replace(tzinfo=None), equity=start_equity)
    return 0


def cmd_forward_test(_: argparse.Namespace) -> int:
    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.forward import FREEZE_DATE, run_forward

    cfg = load_config(ROOT / "config")
    store = MarketStore(DB_PATH)
    try:
        ledger, summary = run_forward(store, CostModel(cfg.costs))
    finally:
        store.close()
    out = ROOT / "data" / "paper"
    out.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(out / "forward_ledger.csv", index=False)
    summary.to_csv(out / "forward_summary.csv", index=False)
    print(f"Forward paper test — frozen {FREEZE_DATE}, counting days after it only (no real orders).")
    print(summary.to_string(index=False))
    if not ledger.empty:
        cols = ["rule", "day", "side", "strike", "entry_ts", "exit_ts", "reason", "net_inr"]
        print("\nLatest trades:\n" + ledger.sort_values("entry_ts").tail(9)[cols].to_string(index=False))
    return 0


def cmd_kill(args: argparse.Namespace) -> int:
    build_runtime().halt(args.reason, source="cli")
    print("HALTED.")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    build_runtime().resume(args.reason, source="cli")
    print("Resumed → BOOT (checks will re-run).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tradingagent")
    sub = p.add_subparsers(dest="cmd", required=True)
    ui = sub.add_parser("ui", help="run the local dashboard")
    ui.add_argument("--demo", action="store_true", help="stream synthetic candles (clearly labelled)")
    ui.set_defaults(fn=cmd_ui)
    sub.add_parser("ui-set-passphrase", help="set the dashboard passphrase").set_defaults(fn=cmd_set_passphrase)
    sub.add_parser("auth", help="daily Groww connect (after approving the key)").set_defaults(fn=cmd_auth)
    sub.add_parser("check-config", help="validate config/*.yaml").set_defaults(fn=cmd_check_config)
    rec = sub.add_parser("record", help="record NIFTY market data for today (read-only)")
    rec.add_argument("--rps", type=float, default=4.0, help="max Groww requests per second")
    rec.set_defaults(fn=cmd_record)
    an = sub.add_parser("analyze-day", help="analyse a recorded day (data quality, spreads, entry test)")
    an.add_argument("day", help="YYYY-MM-DD")
    an.set_defaults(fn=cmd_analyze_day)
    fh = sub.add_parser("fetch-history", help="download history into data/market.duckdb (resumable, read-only)")
    fh.add_argument("--start", default="2023-12-01")
    fh.add_argument("--end", default=None)
    fh.add_argument("--underlying", default="NIFTY")
    fh.add_argument("--strikes", type=int, default=5, help="strikes beyond the week's ATM range, each side")
    fh.add_argument("--rps", type=float, default=4.0)
    fh.add_argument("--index-only", action="store_true")
    fh.set_defaults(fn=cmd_fetch_history)
    sub.add_parser("db-summary", help="show what is stored in data/market.duckdb").set_defaults(fn=cmd_db_summary)
    sub.add_parser("backtest-exits", help="compare exit rules on stored history (ORB entry)").set_defaults(
        fn=cmd_backtest_exits)
    sub.add_parser("backtest-entries", help="compare entries and filters with a fixed exit").set_defaults(
        fn=cmd_backtest_entries)
    rk = sub.add_parser("backtest-risk", help="daily loss caps, streaks, drawdowns for chosen setups")
    rk.add_argument("--g-rules", action="store_true", help="use G1/G2 (open-outside filter) from the logic study")
    rk.set_defaults(fn=cmd_backtest_risk)
    sub.add_parser("scorecard", help="trade-quality scorecard: logic / entry / capture / exit + relationships"
                   ).set_defaults(fn=cmd_scorecard)
    pp = sub.add_parser("paper", help="live paper trading of G1/G2 from the recorder's data (no orders)")
    pp.add_argument("--day", default=None, help="YYYY-MM-DD (default today)")
    pp.add_argument("--replay", action="store_true", help="replay a recorded day instead of running live")
    pp.add_argument("--record", action="store_true", help="with --replay: also add the trades to the ledger")
    pp.set_defaults(fn=cmd_paper)
    sub.add_parser("backtest-logic", help="setup-logic feature study (pre-declared)").set_defaults(
        fn=cmd_backtest_logic)
    sub.add_parser("backtest-followthrough", help="15-min follow-through exit study (pre-declared)").set_defaults(
        fn=cmd_backtest_followthrough)
    sub.add_parser("backtest-timing", help="entry-timing variants for S1/S2 (pre-declared)").set_defaults(
        fn=cmd_backtest_timing)
    sub.add_parser("backtest-stops", help="stop sweep + killed-winners per setup").set_defaults(fn=cmd_backtest_stops)
    sub.add_parser("forward-test", help="evaluate frozen rules on days after the freeze date").set_defaults(
        fn=cmd_forward_test)
    k = sub.add_parser("kill", help="halt trading")
    k.add_argument("--reason", default="manual kill from CLI")
    k.set_defaults(fn=cmd_kill)
    r = sub.add_parser("resume", help="clear HALT (reason required)")
    r.add_argument("--reason", required=True)
    r.set_defaults(fn=cmd_resume)
    args = p.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
