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
            dl.download_options(args.underlying, start, end, strikes_each_side=args.strikes, step=args.step)
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
    load_dotenv(ROOT / ".env")              # live only: ANTHROPIC_API_KEY for the LLM shadow filter (never printed)
    run_live(day, data_root, DB_PATH, costs, RUNTIME_DIR / "paper_state.json", ledger,
             now=lambda: clock.now().replace(tzinfo=None), equity=start_equity)
    return 0


def cmd_llm_shadow_check(_: argparse.Namespace) -> int:
    """One real 'risk of the day' call to check the API key, web search and budget plumbing (costs ~₹1–3).
    Recorded with kind='check' so it never counts in the forward evaluation."""
    from datetime import datetime as _dt

    from tradingagent.agent.shadow import Ledger, ShadowConfig, decide, load_events, morning_prompt

    load_dotenv(ROOT / ".env")
    cfg, ledger = ShadowConfig.load(), Ledger()
    today = _dt.now().date()
    print(f"model {cfg.model}; spent this month ₹{ledger.month_spend_inr(today):.2f} of ₹{cfg.monthly_cap_inr:.0f}")
    rec = decide("check", today, None, morning_prompt(today, load_events(today)), cfg, ledger, _dt.now)
    print(f"decision: {rec.get('decision')}  confidence: {rec.get('confidence')}  cost ₹{rec.get('cost_inr')}  "
          f"latency {rec.get('latency_s')}s  searches {(rec.get('usage') or {}).get('web_search_requests')}")
    for r in rec.get("reasons") or []:
        print("  -", r)
    print("sources:", [s["url"] for s in (rec.get("sources") or [])][:5])
    if rec.get("error"):
        print("error:", rec["error"])
    return 0 if rec.get("decision") not in (None, "NO_DECISION") else 1


def cmd_backtest_discovery(args: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.discovery_study import (
        STAGE_A,
        STAGE_B,
        load_expiries,
        stage_a,
        stage_b,
        summarize_a,
        summarize_b,
    )

    expiries = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    out = ROOT / "data" / "reports" / "backtests" / f"discovery_{args.stage}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    try:
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            if args.stage == "A":
                a = stage_a(store, expiries, *STAGE_A)
                a.to_csv(out / "signals_untouched.csv", index=False)
                sa = summarize_a(a)
                sa.to_csv(out / "stage_a_untouched.csv", index=False)
                print(f"=== STAGE A — UNTOUCHED index data {STAGE_A[0]} → {STAGE_A[1]} (decides) ===")
                print(sa.to_string(index=False))
                a2 = stage_a(store, expiries, *STAGE_B)
                sa2 = summarize_a(a2)
                sa2.to_csv(out / "stage_a_seen_era.csv", index=False)
                print(f"\n=== for information: same measures on {STAGE_B[0]} → {STAGE_B[1]} (already-studied era) ===")
                print(sa2.drop(columns=["PASS_A"]).to_string(index=False))
            else:
                setups = [s for s in args.setups.split(",") if s]
                t = stage_b(store, CostModel(load_config(ROOT / "config").costs), expiries, setups)
                t.to_csv(out / "trades.csv", index=False)
                sb = summarize_b(t)
                sb.to_csv(out / "stage_b.csv", index=False)
                print(sb.drop(columns=["median_delay_min"]).to_string(index=False))
    finally:
        store.close()
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_magnitude(_: argparse.Namespace) -> int:
    from datetime import date, datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.discovery_study import load_expiries
    from tradingagent.sim.magnitude_study import combined_score, day_table, evaluate, load

    expiries = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    store = MarketStore(DB_PATH, read_only=True)
    try:
        idx, vix1, vixd = load(store)
    finally:
        store.close()
    tbl = day_table(idx, vix1, vixd, expiries)
    tbl = tbl[~tbl["expiry_day"]]
    untouched = tbl[(tbl.index >= date(2021, 11, 1)) & (tbl.index <= date(2023, 11, 30))]  # 1 month ATR warm-up
    seen = tbl[(tbl.index >= date(2023, 12, 1)) & (tbl.index <= date(2026, 9, 30))]
    out = ROOT / "data" / "reports" / "backtests" / f"magnitude_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    tbl.to_csv(out / "days.csv")
    res = evaluate(untouched, seen)
    res.to_csv(out / "predictors.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 20, "display.max_colwidth", 60):
        print(f"days: untouched {len(untouched)} (2021-11 → 2023-11), 2023-26 {len(seen)}; expiry days excluded")
        print(f"big-day cut (top third, untouched): range after 09:30 ≥ "
              f"{untouched['range_after_atr'].quantile(2 / 3):.2f} × ATR14\n")
        print(res.to_string(index=False))
    passing = res[res["PASS"]]["predictor"].tolist()
    if len(passing) >= 2:
        signs = dict(zip(res["predictor"], res["rho_untouched"], strict=True))
        cs = combined_score(untouched, seen, passing, signs)
        print(f"\nCombined score of {passing} on 2023-26 only: {cs}")
    else:
        print(f"\nPassing predictors: {passing or 'none'} — fewer than 2, so no combined score (pre-declared).")
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_swing(args: argparse.Namespace) -> int:
    import csv
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import swing_study as sw

    syms = [r["Symbol"] for r in csv.DictReader((ROOT / "data" / "universe" / "ind_nifty50list.csv").open())]
    out = ROOT / "data" / "reports" / "backtests" / f"swing_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    costs = sw.DeliveryCosts()
    store = MarketStore(DB_PATH, read_only=True)
    data, rows, fills = {}, [], []
    try:
        for s in syms:
            raw = store.candles(f"NSE-{s}", "1day")
            if raw.empty:
                print(f"{s}: no daily data")
                continue
            intra = store.candles(f"NSE-{s}", "1minute")
            if intra.empty:
                intra = store.candles(f"NSE-{s}", "15minute")
            raw, fill = sw.rebuild_from_intraday(raw, intra)
            fills.append({"symbol": s, **fill})
            d, ex = sw.prepare(raw)
            data[s] = d
            for name in sw.SETUPS:
                rows += sw.run_signal_setup(s, d, ex, name, costs)
    finally:
        store.close()
    t = pd.DataFrame(rows)
    t["rand_pct"] = sw.matched_random(t, data, costs)
    t["excess_pct"] = t["net_pct"] - t["rand_pct"]
    t.to_csv(out / "trades.csv", index=False)
    rot = sw.momentum_rotation(data, costs)
    rot.to_csv(out / "rotation.csv", index=False)
    with pd.option_context("display.width", 260, "display.max_columns", 30):
        f = pd.DataFrame(fills)
        m = f["pre2025_open_match_0.05%"].dropna()
        print("=== data check: 2025+ daily bars rebuilt from intraday (Groww daily open broken from 2025) ===")
        print(f"rebuilt {int(f['rebuilt'].sum())} stock-days, dropped {int(f['dropped'].sum())}; pre-2025 daily open "
              f"= first intraday trade (±0.05%) on {m.min()}–{m.max()}% of {int(f['checked_pre2025'].sum())} days")
        print(f"\n=== Swing study, Nifty 50 basket ({len(data)} stocks), net % per trade on ₹1 lakh ===")
        print(sw.verdict_signal(t).to_string(index=False))
        for name, g in t.groupby("setup"):
            exits = g["reason"].value_counts().to_dict()
            print(f"{name}: max concurrent positions {sw.max_concurrent(g)}; exits {exits}")
        print("\n=== SW3 momentum rotation (top 5 vs equal-weight all) ===")
        print(sw.verdict_rotation(rot).to_string(index=False))
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_stocks(args: argparse.Namespace) -> int:
    import csv
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import stock_study as ss

    syms = [r["symbol"] for r in csv.DictReader((ROOT / "config" / "stock_universe_2026-09-30.csv").open())]
    out = ROOT / "data" / "reports" / "backtests" / f"stocks_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    parts, events, drift = [], [], []
    try:
        nifty = store.candles("NSE-NIFTY", "1minute")
        for s in syms:
            m1 = store.candles(f"NSE-{s}", "1minute")
            if m1.empty:
                print(f"{s}: no 1-minute data")
                continue
            t, ev = ss.run_stock(s, m1, nifty, ss.EquityIntradayCosts())
            parts.append(t)
            events += [{"symbol": s, **e} for e in ev]
            adj = ss.adjust_splits(ss.clean_bad_prints(m1)[0])[0]
            dly = adj.groupby("day")["close"].last()
            for p, (a, b) in ss.PERIODS.items():
                w = dly[(dly.index >= a) & (dly.index <= b)]
                drift.append({"symbol": s, "period": p, "buy_hold_%": round((w.iloc[-1] / w.iloc[0] - 1) * 100, 1)})
            print(f"{s}: {len(t)} trades, ex-dates {[(str(e['day']), e['ratio']) for e in ev]}", flush=True)
    finally:
        store.close()
    trades = pd.concat(parts, ignore_index=True)
    trades.to_csv(out / "trades.csv", index=False)
    v = ss.verdicts(trades)
    v.to_csv(out / "verdicts.csv", index=False)
    with pd.option_context("display.width", 300, "display.max_columns", 40, "display.max_rows", 100):
        print("\n=== split/bonus ex-dates found (excluded; earlier prices back-adjusted) ===")
        print(pd.DataFrame(events).to_string(index=False) if events else "none")
        print("\n=== stock drift (buy & hold, info) ===")
        print(pd.DataFrame(drift).pivot(index="symbol", columns="period", values="buy_hold_%").to_string())
        cols = ["symbol", "setup", "P1_n", "P1_net%", "P1_ci95%", "P1_pf", "P1_PASS",
                "P2_n", "P2_net%", "P2_ci95%", "P2_pf", "P2_PASS", "PASS_both", "ROBUST"]
        print("\n=== per stock × setup: P1 = Oct 2021–Sep 2024, P2 = Oct 2024–Sep 2026 (net % per trade on ₹1L) ===")
        print(v[cols].to_string(index=False))
        rnd = trades[trades["setup"] == "RANDOM"].groupby(["symbol", "period"])["net"].mean().div(ss.NOTIONAL / 100)
        print("\nRANDOM control net % per trade:\n" + rnd.round(3).unstack().to_string())
        print(f"\nPASS both periods: {int(v['PASS_both'].sum())} of {len(v)} | ROBUST: {int(v['ROBUST'].sum())}"
              f"  (expected by luck ≈ 0.1)")
    print(f"\nWritten to {out}")
    return 0


def cmd_bn_behaviour(_: argparse.Namespace) -> int:
    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import bn_behaviour as bb
    from tradingagent.sim.costs import CostModel

    store = MarketStore(DB_PATH, read_only=True)
    try:
        r = bb.run(store, CostModel(load_config(ROOT / "config").costs))
    finally:
        store.close()
    with pd.option_context("display.width", 220, "display.max_columns", 20, "display.max_colwidth", 60):
        print(f"=== Bank Nifty behaviour, search window only ({r['days']} days) ===")
        tod = r["tod"]
        print("\n1a. When the day's HIGH / LOW is made (30-min slot):")
        print(pd.concat([tod["high_slot"], tod["low_slot"], tod["abs_move"]], axis=1).to_string())
        print("\n1b. Does a 30-min move carry on into the next 30 min? (random = 50%, 0)")
        print(tod["persistence"].to_string(index=False))
        print("\n2a. First hour (09:15→10:15) → rest of day (10:15→15:10), ATR units, 95% CI:")
        print(r["opening"]["first_hour"].to_string(index=False))
        print("\n2b. Gaps: filled by close / continued to 15:10:")
        print(r["opening"]["gaps"].to_string())
        print("\n3. Trend days (|close−open| ≥ 0.6 × range) by condition known by 10:15:")
        print(r["day_types"].to_string(index=False))
        print("\n4. Bank Nifty vs Nifty relative strength at 10:15 → Bank Nifty move to 15:10:")
        print(r["relative"].to_string(index=False))
        print("\n5. ATM option bought 10:00, sold 15:10 — what index move is needed to break even:")
        print(r["options"].to_string(index=False))
    return 0


def cmd_bn_search(args: argparse.Namespace) -> int:
    from datetime import datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import banknifty_search as bs
    from tradingagent.sim.costs import CostModel

    out = ROOT / "data" / "reports" / "backtests" / f"bn_search_{args.step}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    if args.step == "heavy":
        from tradingagent.sim import bn_heavy as bh
        from tradingagent.sim.discovery_study import summarize_a
        from tradingagent.sim.inside_day_study import resplit
        from tradingagent.sim.timing_study import summarize_timing
        try:
            bs.check_window(bs.SEARCH_START, bs.SEARCH_END)
            a, t = bh.run(store, CostModel(load_config(ROOT / "config").costs), bs.SEARCH_START, bs.SEARCH_END)
        finally:
            store.close()
        a.to_csv(out / "direction.csv", index=False)
        t = resplit(t)
        t.to_csv(out / "trades.csv", index=False)
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            print(f"=== Bank Nifty heavyweight lead (B5), search window {bs.SEARCH_START} → {bs.SEARCH_END} ===")
            print("direction (HEAVY = follow HDFCBANK+ICICIBANK when D ≥ 0.25%):")
            print(summarize_a(a).to_string(index=False))
            print(f"\noption P&L (lot {bs.LOT}); HL1 = hold to 15:10, HL2 = exit after 60 min:")
            print(summarize_timing(t, 60).drop(columns=["median_delay_min"]).to_string(index=False))
            print("\nby options era (net ₹/trade, n):")
            print(t.pivot_table(index="variant", columns="era", values="net_inr", aggfunc=["mean", "size"])
                  .round(1).to_string())
        print(f"\nWritten to {out}")
        return 0
    if args.step == "gapfill":
        from tradingagent.sim import bn_gapfill as gf
        from tradingagent.sim.inside_day_study import resplit
        from tradingagent.sim.timing_study import summarize_timing
        try:
            bs.check_window(bs.SEARCH_START, bs.SEARCH_END)
            t = resplit(gf.run(store, CostModel(load_config(ROOT / "config").costs), bs.SEARCH_START, bs.SEARCH_END))
        finally:
            store.close()
        t.to_csv(out / "trades.csv", index=False)
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            print(f"=== Bank Nifty gap-fill (B3), search window {bs.SEARCH_START} → {bs.SEARCH_END}, lot {bs.LOT} ===")
            print(summarize_timing(t, 60).drop(columns=["median_delay_min"]).to_string(index=False))
            print("\nby options era (net ₹/trade, n):")
            print(t.pivot_table(index="variant", columns="era", values="net_inr", aggfunc=["mean", "size"])
                  .round(1).to_string())
            print("\nexit reasons:\n" + pd.crosstab(t["variant"], t["reason"]).to_string())
            print("\nmedian minutes held:\n" + t.groupby("variant")["hold_min"].median().to_string())
        print(f"\nWritten to {out}")
        return 0
    try:
        trades, summary = bs.run_entry_study(store, CostModel(load_config(ROOT / "config").costs))
    finally:
        store.close()
    trades.to_csv(out / "trades.csv", index=False)
    summary.to_csv(out / "summary.csv", index=False)
    traded = trades.dropna(subset=["net_inr"])
    miss = int(trades["net_inr"].isna().sum())
    print(f"=== Bank Nifty search, step 1 (entries), {bs.SEARCH_START} → {bs.SEARCH_END}, ₹ at lot {bs.LOT} ===")
    print(f"trades: {len(traded)} | signals without option data: {miss}")
    cols = ["entry", "exit", "filter", "n", "win", "net", "net_2x", "pf", "dev", "val", "test", "H1", "H2",
            "CE", "PE", "ex_top5", "PASS", "ROBUST"]
    with pd.option_context("display.width", 260, "display.max_columns", 30, "display.max_rows", 300):
        print("\n--- unfiltered, by entry and exit ---")
        print(summary[summary["filter"] == "all"][cols].to_string(index=False))
        print("\n--- top 25 cells with n >= 100 ---")
        print(summary[summary["n"] >= 100].head(25)[cols].to_string(index=False))
        print(f"\nPASS cells: {int(summary['PASS'].sum())} | ROBUST cells: {int(summary['ROBUST'].sum())} "
              f"(of {len(summary)}; ~5% would pass by chance)")
        print(summary[summary["PASS"]][cols].to_string(index=False))
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_inside(args: argparse.Namespace) -> int:
    from datetime import date, datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import inside_day_study as ins
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.discovery_study import load_expiries, summarize_a
    from tradingagent.sim.timing_study import summarize_timing

    nf_exp = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    bn_exp = load_expiries(ROOT / "data" / "expiries" / "BANKNIFTY.csv")
    out = ROOT / "data" / "reports" / "backtests" / f"inside_{args.stage}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    try:
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            und = args.underlying
            exp, step = (nf_exp, 50) if und == "NIFTY" else (bn_exp, 100)
            if args.stage == "A":
                for tag, s, e in (("DECIDES — untouched", date(2021, 11, 1), date(2023, 11, 30)),
                                  ("info only", date(2023, 12, 1), date(2026, 9, 30))):
                    a = ins.stage_a(store, und, exp, s, e, step)
                    a.to_csv(out / f"stage_a_{und}_{s:%Y}.csv", index=False)
                    print(f"=== {und} Stage A ({tag}): {s} → {e} (inside-open days; RANDOM = same days) ===")
                    sa = summarize_a(a)
                    print((sa if tag.startswith("DECIDES") else sa.drop(columns=["PASS_A"])).to_string(index=False))
                    print()
            else:
                setups = [s for s in args.setups.split(",") if s]
                lot = 65 if und == "NIFTY" else 30
                costs = CostModel(load_config(ROOT / "config").costs)
                windows = ([("DECIDES", date(2023, 12, 1), date(2026, 9, 30))] if und == "NIFTY" else
                           [("DECIDES — monthly options", date(2024, 12, 1), date(2026, 9, 30)),
                            ("info — weekly options", date(2023, 12, 1), date(2024, 11, 20))])
                for tag, s, e in windows:
                    t = ins.stage_b(store, costs, und, exp, setups, s, e, step, lot)
                    t.to_csv(out / f"trades_{und}_{s:%Y%m}.csv", index=False)
                    if t.empty:
                        print(f"=== {und} Stage B ({tag}): no trades ===")
                        continue
                    min_n = 60 if (und == "BANKNIFTY" and tag.startswith("DECIDES")) else 100
                    print(f"=== {und} Stage B ({tag}): {s} → {e}, ₹ at lot {lot}, PASS needs n ≥ {min_n} ===")
                    print(summarize_timing(t, min_n).drop(columns=["median_delay_min"]).to_string(index=False) + "\n")
    finally:
        store.close()
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_g_banknifty(args: argparse.Namespace) -> int:
    from datetime import date, datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim import banknifty_validation as bv
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.discovery_study import load_expiries, summarize_a
    from tradingagent.sim.inside_day_study import resplit
    from tradingagent.sim.timing_study import summarize_timing

    bn_exp = load_expiries(ROOT / "data" / "expiries" / "BANKNIFTY.csv")
    nf_exp = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    out = ROOT / "data" / "reports" / "backtests" / f"g_banknifty_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    clean, overlap_era = (date(2021, 10, 1), date(2023, 11, 30)), (date(2023, 12, 1), date(2026, 9, 30))
    try:
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            for label, (s, e) in (("CLEAN 2021-23 (never used for anything)", clean),
                                  ("2023-26 (overlaps the Nifty build period)", overlap_era)):
                a = bv.stage_a(store, "BANKNIFTY", bn_exp, s, e, bv.BN_STEP)
                a.to_csv(out / f"stage_a_{s:%Y}.csv", index=False)
                print(f"=== STAGE A — Bank Nifty direction {label}: {s} → {e} ===")
                print(summarize_a(a).to_string(index=False))
                nf = bv.stage_a(store, "NIFTY", nf_exp, s, e, 50)
                print("overlap with Nifty G-signals:\n" + bv.overlap(a, nf).to_string(index=False) + "\n")
            if not args.skip_options:
                t = bv.stage_b(store, CostModel(load_config(ROOT / "config").costs), "BANKNIFTY", bn_exp,
                               *overlap_era, bv.BN_STEP, bv.BN_LOT)
                t.to_csv(out / "trades.csv", index=False)
                traded = t.dropna(subset=["net_inr"])
                miss = int(t["net_inr"].isna().sum())
                print(f"=== STAGE B — Bank Nifty options {overlap_era[0]} → {overlap_era[1]} "
                      f"(₹ at lot {bv.BN_LOT}; {miss} signals had no option data) ===")
                print(summarize_timing(traded).drop(columns=["median_delay_min"]).to_string(index=False))
                print("\nR and % of premium per trade:")
                print(traded.groupby("variant")[["r_net", "pct_prem"]].agg(["mean", "median"]).round(3).to_string())
                for era, tag in (("monthly", "DECIDES BN-G1/BN-G2 (n ≥ 60 bar, smaller sample)"),
                                 ("weekly", "info only")):
                    sub = resplit(traded[traded["era"] == era])
                    if len(sub):
                        print(f"\n=== {era}-options era — {tag} (dev/val/test split within this era) ===")
                        min_n = 60 if era == "monthly" else 100
                        print(summarize_timing(sub, min_n).drop(columns=["median_delay_min"]).to_string(index=False))
                        print(sub.groupby("variant")[["r_net", "pct_prem"]].mean().round(3).to_string())
    finally:
        store.close()
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_internet(args: argparse.Namespace) -> int:
    from datetime import date, datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.discovery_study import load_expiries, summarize_a
    from tradingagent.sim.internet_study import claims, stage_a, stage_b, summarize_b

    expiries = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    out = ROOT / "data" / "reports" / "backtests" / f"internet_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    decide, old, full = ((date(2024, 10, 1), date(2026, 9, 30)), (date(2021, 11, 1), date(2023, 11, 30)),
                         (date(2021, 10, 1), date(2026, 9, 30)))
    try:
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            t = stage_b(store, CostModel(load_config(ROOT / "config").costs), expiries, *decide)
            t.to_csv(out / "trades.csv", index=False)
            r = summarize_b(t)
            r.to_csv(out / "stage_b.csv", index=False)
            print(f"=== DECIDES: option P&L {decide[0]} → {decide[1]} ===")
            print(r.drop(columns=["median_delay_min"]).to_string(index=False))
            print("\nexit reasons:\n" + pd.crosstab(t["variant"], t["reason"]).to_string())
            a = summarize_a(stage_a(store, expiries, *old))
            a.to_csv(out / "stage_a_old.csv", index=False)
            print(f"\n=== info: direction {old[0]} → {old[1]} ===")
            print(a.drop(columns=["PASS_A"]).to_string(index=False))
            cl = claims(store, expiries, *full)
            cl.to_csv(out / "claims.csv", index=False)
            months = cl["month"].nunique() if len(cl) else 0
            print(f"\n=== info: claim checks {full[0]} → {full[1]} (index only, {months} months with signals) ===")
            n_months = (full[1].year - full[0].year) * 12 + full[1].month - full[0].month + 1
            print((cl.groupby("setup").size() / n_months).round(1).rename("signals_per_month").to_string())
            for col in ("T1", "T2", "T3"):
                if col in cl:
                    print(f"\n{col} reached before stop (by 15:10):")
                    print(cl.dropna(subset=[col]).groupby("setup")[col].value_counts(normalize=True)
                          .mul(100).round(1).unstack().to_string())
    finally:
        store.close()
    print(f"\nWritten to {out}")
    return 0


def cmd_backtest_popular(args: argparse.Namespace) -> int:
    from datetime import date, datetime

    import pandas as pd

    from tradingagent.data.store import MarketStore
    from tradingagent.sim.costs import CostModel
    from tradingagent.sim.discovery_study import load_expiries, summarize_a, summarize_b
    from tradingagent.sim.popular_study import stage_a, stage_b

    expiries = load_expiries(ROOT / "data" / "expiries" / "NIFTY.csv")
    out = ROOT / "data" / "reports" / "backtests" / f"popular_{args.stage}_{datetime.now():%Y%m%d_%H%M}"
    out.mkdir(parents=True, exist_ok=True)
    store = MarketStore(DB_PATH, read_only=True)
    untouched, seen = (date(2021, 11, 1), date(2023, 11, 30)), (date(2023, 12, 1), date(2026, 9, 30))
    try:
        with pd.option_context("display.width", 260, "display.max_columns", 30):
            if args.stage == "A":
                a = stage_a(store, expiries, *untouched)
                a.to_csv(out / "signals_untouched.csv", index=False)
                sa = summarize_a(a)
                sa.to_csv(out / "stage_a_untouched.csv", index=False)
                print(f"=== STAGE A — UNTOUCHED {untouched[0]} → {untouched[1]} (decides) ===")
                print(sa.to_string(index=False))
                sb = summarize_a(stage_a(store, expiries, *seen))
                sb.to_csv(out / "stage_a_seen_era.csv", index=False)
                print(f"\n=== for information: {seen[0]} → {seen[1]} ===")
                print(sb.drop(columns=["PASS_A"]).to_string(index=False))
            else:
                setups = [s for s in args.setups.split(",") if s]
                window = (date.fromisoformat(args.start) if args.start else seen[0],
                          date.fromisoformat(args.end) if args.end else seen[1])
                print(f"=== STAGE B — options {window[0]} → {window[1]} ===")
                t = stage_b(store, CostModel(load_config(ROOT / "config").costs), expiries, setups, *window)
                t.to_csv(out / "trades.csv", index=False)
                r = summarize_b(t)
                r.to_csv(out / "stage_b.csv", index=False)
                print(r.drop(columns=["median_delay_min"]).to_string(index=False))
    finally:
        store.close()
    print(f"\nWritten to {out}")
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
    fh.add_argument("--step", type=int, default=50, help="strike step in index points (BANKNIFTY: 100)")
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
    pop = sub.add_parser("backtest-popular", help="popular strategies batch 1: stage A (untouched) / B (options)")
    pop.add_argument("--stage", choices=["A", "B"], default="A")
    pop.add_argument("--setups", default="")
    pop.add_argument("--start", default="", help="stage B window start YYYY-MM-DD (default 2023-12-01)")
    pop.add_argument("--end", default="", help="stage B window end YYYY-MM-DD (default 2026-09-30)")
    pop.set_defaults(fn=cmd_backtest_popular)
    sub.add_parser("llm-shadow-check", help="one real LLM shadow call to verify key/web search (~Rs 1-3)"
                   ).set_defaults(fn=cmd_llm_shadow_check)
    sub.add_parser("backtest-swing", help="swing study on the Nifty 50 basket (daily bars, long only)"
                   ).set_defaults(fn=cmd_backtest_swing)
    sub.add_parser("backtest-stocks", help="stock intraday pilot (frozen 10 stocks, two untouched periods)"
                   ).set_defaults(fn=cmd_backtest_stocks)
    sub.add_parser("bn-behaviour", help="Bank Nifty behaviour study (measurement only, search window)"
                   ).set_defaults(fn=cmd_bn_behaviour)
    bns = sub.add_parser("bn-search", help="Bank Nifty setup search (search window only; lock boxes refused)")
    bns.add_argument("--step", choices=["entries", "gapfill", "heavy"], default="entries")
    bns.set_defaults(fn=cmd_bn_search)
    ins = sub.add_parser("backtest-inside", help="inside-day setups: stage A (Nifty untouched + Bank Nifty) / B")
    ins.add_argument("--stage", choices=["A", "B"], default="A")
    ins.add_argument("--setups", default="")
    ins.add_argument("--underlying", choices=["NIFTY", "BANKNIFTY"], default="NIFTY")
    ins.set_defaults(fn=cmd_backtest_inside)
    gbn = sub.add_parser("backtest-g-banknifty", help="frozen G1/G2 on Bank Nifty (cross-instrument validation)")
    gbn.add_argument("--skip-options", action="store_true", help="Stage A (index) only")
    gbn.set_defaults(fn=cmd_backtest_g_banknifty)
    sub.add_parser("backtest-internet", help="internet strategies batch 2 (pre-declared, recent 2 years decide)"
                   ).set_defaults(fn=cmd_backtest_internet)
    sub.add_parser("backtest-magnitude", help="can big-move days be predicted by 09:30? (measurement)").set_defaults(
        fn=cmd_backtest_magnitude)
    dv = sub.add_parser("backtest-discovery", help="new-setup discovery: stage A (untouched data) / B (options)")
    dv.add_argument("--stage", choices=["A", "B"], default="A")
    dv.add_argument("--setups", default="", help="stage B: comma-separated setups that passed stage A")
    dv.set_defaults(fn=cmd_backtest_discovery)
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
