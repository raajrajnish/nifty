"""Runtime facade the UI and CLI talk to (Phase 0 skeleton of DESIGN.md §4.9).

Phase 0 scope: day state, HALT/resume, broker connect, event publishing. There is no trading loop,
no executor and no positions yet, so halt() has nothing to cancel or flatten. When the executor
lands (Phase 6) halt() must call it BEFORE marking HALTED (DESIGN.md §5.8 order).
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from tradingagent.config.models import AppConfig
from tradingagent.core.clock import Clock
from tradingagent.core.events import EventBus
from tradingagent.core.modes import DayState
from tradingagent.paper.account import Equity, equity_from_ledger


class BrokerAuth(Protocol):
    """Satisfied by broker.auth.GrowwAuth; injected so ui/ never imports the broker package."""

    def status(self) -> Any: ...
    def acquire(self) -> Any: ...


@dataclass
class HaltInfo:
    reason: str
    source: str
    at: str


class Runtime:
    def __init__(self, cfg: AppConfig, clock: Clock, bus: EventBus, auth: BrokerAuth,
                 runtime_dir: Path, data_dir: Path | None = None, config_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.clock = clock
        self.bus = bus
        self._auth = auth
        self._dir = runtime_dir
        self._data = data_dir or runtime_dir.parent / "data"
        self._config = config_dir or runtime_dir.parent / "config"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._halt_file = runtime_dir / "HALT"
        self.day_state = DayState.BOOT
        self.halt_info: HaltInfo | None = None
        if self._halt_file.exists():  # HALT survives restarts until the owner resumes
            self.halt_info = HaltInfo(self._halt_file.read_text(encoding="utf-8").strip() or "unknown",
                                      "file", "")
            self.day_state = DayState.HALTED

    # ---- state -------------------------------------------------------------------------------
    @property
    def halted(self) -> bool:
        return self._halt_file.exists() or self.day_state is DayState.HALTED

    def transition(self, to: DayState, reason: str) -> None:
        if self.halted and to is not DayState.HALTED:
            raise RuntimeError("HALTED is sticky: owner must resume first")
        frm, self.day_state = self.day_state, to
        self.bus.publish("STATE_TRANSITION", self.clock.now(), {"from": frm, "to": to, "reason": reason})

    def snapshot(self) -> dict[str, Any]:
        auth = self._auth.status()
        return {
            "day_state": self.day_state.value,
            "stage": self.cfg.stage.stage.value,
            "mode": self.cfg.stage.mode.value,
            "halted": self.halted,
            "halt": self.halt_info.__dict__ if self.halt_info else None,
            "broker": {
                "connected": bool(auth.connected),
                "acquired_at": auth.acquired_at.isoformat() if getattr(auth, "acquired_at", None) else None,
                "error": auth.error,
            },
            "now": self.clock.now().isoformat(),
            "config_hash": self.cfg.config_hash,
            "risk": self.risk_view(),
            "config_tbd": self.cfg.tbd_fields(),
            "recorder": self._recorder_status(),
        }

    def equity(self) -> Equity:
        today = self.clock.now().date().isoformat()
        return equity_from_ledger(self.cfg.risk.capital_inr, self._data / "paper" / "live_trades.csv", today)

    def risk_view(self) -> dict[str, Any]:
        """Every limit as a percentage, with the rupee value it means right now (risk.yaml: % of equity)."""
        r, eq = self.cfg.risk, self.equity()
        return {
            "basis": r.capital_basis, "start_capital": r.capital_inr, "equity": eq.equity,
            "start_of_day_equity": eq.start_of_day, "peak_equity": eq.peak, "drawdown_pct": eq.drawdown_pct,
            "today_pnl": eq.today,
            "per_trade_risk_pct": r.per_trade_risk_pct, "per_trade_risk_inr": round(r.per_trade_risk_at(eq.equity)),
            "daily_loss_limit_pct": r.daily_loss_limit_pct,
            "daily_loss_limit_inr": round(r.daily_loss_limit_at(eq.start_of_day)),
            "drawdown_kill_pct": r.kill_criteria.live_drawdown_pct_from_peak,
            "drawdown_kill_inr": round(r.drawdown_kill_at(eq.peak)),
            "max_trades_per_day": r.max_trades_per_day,
            # back-compat for older UI code
            "capital": eq.equity,
        }

    def lots_allowed(self, premium: float | None, stop_pct: float, lot: int, equity: float) -> dict[str, Any]:
        """Live-sizing answer (paper always uses 1 lot): lots = min(risk budget ÷ risk per lot,
        outlay cap ÷ cost per lot, max_lots), rounded down."""
        r = self.cfg.risk
        if not premium:
            return {"lots": None, "why": "no live option price yet"}
        risk_per_lot = premium * stop_pct * lot
        cost_per_lot = premium * lot
        budget, outlay = r.per_trade_risk_at(equity), equity * r.max_premium_outlay_pct / 100
        by_risk, by_outlay = int(budget // risk_per_lot), int(outlay // cost_per_lot)
        lots = max(0, min(by_risk, by_outlay, r.max_lots))
        need_pct = risk_per_lot / equity * 100
        if lots == 0 and by_risk == 0:
            why = f"1 lot needs a risk budget of {need_pct:.2f}% — you allow {r.per_trade_risk_pct}%"
        elif lots == 0:
            why = f"1 lot costs more than the {r.max_premium_outlay_pct}% spend cap"
        else:
            limit = "max lots" if lots == r.max_lots else "risk budget" if by_risk <= by_outlay else "spend cap"
            why = f"limited by {limit} — uses {lots * need_pct:.2f}% of equity as risk"
        return {"lots": lots, "risk_per_lot_inr": round(risk_per_lot), "cost_per_lot_inr": round(cost_per_lot),
                "risk_per_lot_pct": round(need_pct, 2), "why": why}

    def overview(self) -> dict[str, Any]:
        """Everything the dashboard shows, in one call."""
        p = self.paper_snapshot()
        st = p["state"] or {}
        mkt = st.get("market") or {}
        eq = self.equity()
        risk = self.risk_view()
        open_mtm = sum(float((s.get("trade") or {}).get("pnl_inr") or 0)
                       for s in (st.get("setups") or {}).values() if s.get("status") == "IN_TRADE")
        today_total = eq.today + open_mtm
        lot = int(mkt.get("lot_size") or 65)
        atm = mkt.get("atm") or {}
        premium = None
        for side in ("CE", "PE"):
            leg = atm.get(side) or {}
            px = leg.get("ask") or leg.get("ltp")
            premium = max(premium or 0, float(px)) if px else premium
        sizing = {"G1": self.lots_allowed(premium, 0.50, lot, eq.equity),
                  "G2": self.lots_allowed(premium, 0.30, lot, eq.equity)}
        days: dict[str, dict[str, Any]] = {}
        for t in p["trades"]:
            d = days.setdefault(t["day"], {"day": t["day"], "trades": 0, "wins": 0, "net_inr": 0.0, "setups": []})
            net = float(t.get("net_inr") or 0)
            d["trades"] += 1
            d["wins"] += int(net > 0)
            d["net_inr"] = round(d["net_inr"] + net, 1)
            d["setups"].append(t["setup"])
        running = self.cfg.risk.capital_inr
        day_rows = []
        for k in sorted(days):
            d = days[k]
            d["net_pct"] = round(d["net_inr"] / running * 100, 2)
            running += d["net_inr"]
            d["equity_after"] = round(running, 1)
            day_rows.append(d)
        return {
            "system": self.snapshot(),
            "market": mkt,
            "account": {**risk, "open_mtm_inr": round(open_mtm, 1), "today_total_inr": round(today_total, 1),
                        "today_total_pct": round(today_total / eq.start_of_day * 100, 2) if eq.start_of_day else 0,
                        "total_pnl_inr": eq.realised,
                        "total_pnl_pct": round(eq.realised / self.cfg.risk.capital_inr * 100, 2),
                        "max_outlay_pct": self.cfg.risk.max_premium_outlay_pct,
                        "max_outlay_inr": round(eq.equity * self.cfg.risk.max_premium_outlay_pct / 100),
                        "max_lots": self.cfg.risk.max_lots, "sizing": sizing},
            "paper": {k: p[k] for k in ("engine_running", "heartbeat_age_s", "totals", "expected", "status_label")},
            "setups": st.get("setups"), "as_of": st.get("as_of"), "history_note": st.get("history_note"),
            "trades": p["trades"], "days": list(reversed(day_rows)),
        }

    def paper_snapshot(self) -> dict[str, Any]:
        """Live G1/G2 paper state (written by `tradingagent paper`) + the paper ledger + backtest expectations."""
        import csv

        import yaml

        today = self.clock.now().date().isoformat()
        state: dict[str, Any] | None = None
        p = self._dir / "paper_state.json"
        if p.exists():
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
                state = s if s.get("day") == today else None
            except (OSError, ValueError):
                state = None
        trades: list[dict[str, Any]] = []
        ledger = self._data / "paper" / "live_trades.csv"
        if ledger.exists():
            with ledger.open(encoding="utf-8") as f:
                trades = list(csv.DictReader(f))
        totals: dict[str, dict[str, Any]] = {}
        for t in trades:
            g = totals.setdefault(t["setup"], {"trades": 0, "wins": 0, "net_inr": 0.0})
            net = float(t.get("net_inr") or 0)
            g["trades"] += 1
            g["wins"] += int(net > 0)
            g["net_inr"] = round(g["net_inr"] + net, 1)
        for g in totals.values():
            g["net_per_trade"] = round(g["net_inr"] / g["trades"], 1) if g["trades"] else None
        expect: dict[str, Any] = {}
        sp = self._config / "setups.yaml"
        if sp.exists():
            y = yaml.safe_load(sp.read_text(encoding="utf-8"))
            expect = {k: {"name": v["name"], **v["evidence"]} for k, v in y.get("setups", {}).items()}
        heartbeat_age = None
        if state and state.get("engine_heartbeat"):
            hb = datetime.fromisoformat(state["engine_heartbeat"])
            heartbeat_age = (self.clock.now().replace(tzinfo=None) - hb.replace(tzinfo=None)).total_seconds()
        eq = self.equity()
        for g in totals.values():
            g["net_pct_of_start_capital"] = round(g["net_inr"] / self.cfg.risk.capital_inr * 100, 2)
        return {"state": state, "engine_running": heartbeat_age is not None and heartbeat_age < 30,
                "heartbeat_age_s": heartbeat_age, "trades": trades[-30:], "totals": totals, "expected": expect,
                "equity": eq.as_dict(), "status_label": "HYPERCARE — forward paper, under close watch"}

    def _recorder_status(self) -> dict[str, Any] | None:
        """Written by the separate `tradingagent record` process (runtime/recorder_status.json)."""
        path = self._dir / "recorder_status.json"
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data

    # ---- owner actions -----------------------------------------------------------------------
    async def connect_broker(self, source: str) -> dict[str, Any]:
        status = await asyncio.to_thread(self._auth.acquire)  # SDK call is blocking
        self.bus.publish("AUTH", self.clock.now(),
                         {"source": source, "connected": status.connected, "error": status.error})
        return self.snapshot()["broker"]  # type: ignore[no-any-return]

    def halt(self, reason: str, source: str) -> None:
        # Phase 6: executor.cancel_all(); executor.flatten(reason); reconciler.reconcile()  ← before this
        self._halt_file.write_text(reason, encoding="utf-8")
        self.halt_info = HaltInfo(reason, source, self.clock.now().isoformat())
        self.day_state = DayState.HALTED
        self.bus.publish("HALT", self.clock.now(), {"reason": reason, "source": source})

    def resume(self, reason: str, source: str) -> None:
        if not reason.strip():
            raise ValueError("a reason is required to resume")
        self._halt_file.unlink(missing_ok=True)
        self.halt_info = None
        self.day_state = DayState.BOOT  # resume re-runs boot checks, never jumps straight into trading
        self.bus.publish("RESUME", self.clock.now(), {"reason": reason, "source": source})
