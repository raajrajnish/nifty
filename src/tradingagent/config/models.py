"""Typed config loading and validation (DESIGN.md §4.1, §8). Config is read-only at runtime."""

import hashlib
import json
from datetime import time
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from tradingagent.core.errors import ConfigError
from tradingagent.core.modes import VALID_STAGE_MODES, Mode, Stage

TBD = Literal["TBD"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeWindow(_Strict):
    start: time
    end: time

    @model_validator(mode="after")
    def _ordered(self) -> "TimeWindow":
        if self.start >= self.end:
            raise ValueError(f"window start {self.start} must be before end {self.end}")
        return self


class ExpiryDayRule(_Strict):
    allowed: bool


class KillCriteria(_Strict):
    live_drawdown_pct_from_peak: float
    live_trades_window: int


class RiskConfig(_Strict):
    capital_inr: float
    capital_basis: Literal["equity", "fixed"] = "equity"
    per_trade_risk_pct: float
    max_premium_outlay_pct: float
    max_lots: int
    max_open_positions: int
    max_trades_per_day: int
    consecutive_loss_pause: int
    cooloff_minutes_after_stop: int
    daily_loss_limit_pct: float
    weekly_loss_limit_pct: float
    max_spread_pct_of_premium: float
    min_contract_volume: int | TBD
    min_scorecard_total: int | TBD
    expiry_day: ExpiryDayRule
    order_style: Literal["limit"]
    max_slippage_pct: float | TBD
    kill_criteria: KillCriteria

    @field_validator("capital_inr", "per_trade_risk_pct", "max_premium_outlay_pct", "daily_loss_limit_pct",
                     "weekly_loss_limit_pct", "max_spread_pct_of_premium")
    @classmethod
    def _positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be > 0")
        return v

    # All limits are percentages; rupee values are derived from the equity they apply to (owner, 2026-10-01).
    def base(self, equity: float | None) -> float:
        """The money a percentage limit applies to: current equity, or capital_inr if basis is 'fixed'."""
        return self.capital_inr if self.capital_basis == "fixed" or equity is None else equity

    def per_trade_risk_at(self, equity: float | None = None) -> float:
        return self.base(equity) * self.per_trade_risk_pct / 100

    def daily_loss_limit_at(self, start_of_day_equity: float | None = None) -> float:
        return self.base(start_of_day_equity) * self.daily_loss_limit_pct / 100

    def drawdown_kill_at(self, peak_equity: float | None = None) -> float:
        return self.base(peak_equity) * self.kill_criteria.live_drawdown_pct_from_peak / 100

    @property
    def per_trade_risk_inr(self) -> float:
        """At starting capital (for reports); live sizing uses per_trade_risk_at(equity)."""
        return self.per_trade_risk_at(None)

    @property
    def daily_loss_limit_inr(self) -> float:
        return self.daily_loss_limit_at(None)


class ScheduleConfig(_Strict):
    boot: time
    pre_market: TimeWindow
    market_open: time
    open_observe_end: time
    entry_window: TimeWindow
    square_off: time
    market_close: time
    post_market: time
    decision_interval: Literal["1m", "5m", "15m"]
    stale_seconds: int
    disconnect_grace_seconds: int
    agent_timeout_seconds: int

    @model_validator(mode="after")
    def _order(self) -> "ScheduleConfig":
        seq = [self.boot, self.pre_market.start, self.market_open, self.entry_window.start,
               self.entry_window.end, self.square_off, self.market_close, self.post_market]
        if seq != sorted(seq):
            raise ValueError("schedule times are out of order")
        return self


class StageConfig(_Strict):
    stage: Stage
    mode: Mode

    @model_validator(mode="after")
    def _combo(self) -> "StageConfig":
        if self.mode not in VALID_STAGE_MODES[self.stage]:
            raise ValueError(f"mode {self.mode} not allowed in stage {self.stage}")
        return self


class InstrumentSpec(_Strict):
    underlying: str
    exchange: str
    segment: str
    lot_size: int
    tick_size: float
    expiry_weekday: Literal["MON", "TUE", "WED", "THU", "FRI"]


class RateEntry(_Strict):
    value: float | TBD
    unit: str
    source_url: str
    as_of: str


class SlippageModel(_Strict):
    kind: Literal["cross_spread"]
    extra_ticks: int


class CostsConfig(_Strict):
    brokerage_per_order: RateEntry
    stt_sell_pct_of_premium: RateEntry
    exchange_txn_pct_of_premium: RateEntry
    sebi_fee_per_crore: RateEntry
    gst_pct: RateEntry
    stamp_duty_buy_pct: RateEntry
    slippage_model: SlippageModel


class ModelsConfig(_Strict):
    screen: str
    manage: str
    entry: str
    risk_officer: str
    reviewer: str
    daily_budget_usd: float


class UIConfig(_Strict):
    require_login: bool = True
    host: str
    port: int
    session_hours: int
    approval_timeout_seconds: int

    @field_validator("host")
    @classmethod
    def _localhost_only(cls, v: str) -> str:
        if v not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("UI must bind to localhost only (DESIGN.md §6.2)")
        return v


class AppConfig(_Strict):
    risk: RiskConfig
    schedule: ScheduleConfig
    stage: StageConfig
    instruments: dict[str, InstrumentSpec]
    costs: CostsConfig
    models: ModelsConfig
    ui: UIConfig
    config_hash: str

    @model_validator(mode="after")
    def _login_required_for_live(self) -> "AppConfig":
        if self.stage.mode is Mode.LIVE and not self.ui.require_login:
            raise ValueError("ui.require_login must be true in LIVE mode")
        return self

    def tbd_fields(self) -> list[str]:
        return _find_tbd(self.model_dump(exclude={"config_hash"}))

    def assert_ready_for(self, mode: Mode) -> None:
        """DESIGN.md A5: PAPER/LIVE refuse to start while any enforcement value is TBD."""
        if mode in (Mode.PAPER, Mode.LIVE) and (missing := self.tbd_fields()):
            raise ConfigError(f"{mode} requires all config values; still TBD: {', '.join(missing)}")


def _find_tbd(obj: Any, prefix: str = "") -> list[str]:
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _find_tbd(v, f"{prefix}{k}.")]
    return [prefix.rstrip(".")] if obj == "TBD" else []


_FILES = ("risk", "schedule", "stage", "instruments", "costs", "models", "ui")


def load_config(root: Path = Path("config")) -> AppConfig:
    raw: dict[str, Any] = {}
    for name in _FILES:
        path = root / f"{name}.yaml"
        if not path.exists():
            raise ConfigError(f"missing config file: {path}")
        raw[name] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    digest = hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()
    try:
        return AppConfig(**raw, config_hash=f"sha256:{digest[:16]}")
    except ValueError as e:
        raise ConfigError(str(e)) from e
