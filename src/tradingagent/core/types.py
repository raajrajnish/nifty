"""Shared data classes (DESIGN.md §3). No dependencies on other tradingagent packages."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

OptType = Literal["CE", "PE"]


@dataclass(frozen=True)
class Candle:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    oi: int | None = None


@dataclass(frozen=True)
class Instrument:
    groww_symbol: str  # [VERIFY format]
    exchange: str
    segment: str
    underlying: str
    lot_size: int
    tick_size: float
    expiry: date | None = None
    strike: float | None = None
    opt_type: OptType | None = None


@dataclass(frozen=True)
class Quote:
    instrument: Instrument
    ts: datetime
    ltp: float
    bid: float | None = None
    ask: float | None = None
    volume: int | None = None
    oi: int | None = None
    iv: float | None = None


@dataclass
class AccountState:
    capital: float
    realized_pnl_today: float = 0.0
    unrealized_pnl: float = 0.0
    trades_today: int = 0
    consecutive_losses: int = 0
    last_stop_out_at: datetime | None = None
    week_pnl: float = 0.0
    peak_equity: float = 0.0
    funds_available: float = 0.0


@dataclass
class Position:
    intent_id: str
    instrument: Instrument
    qty: int
    avg_price: float
    entry_ts: datetime
    stop_premium: float
    time_stop_at: datetime
    setup_id: str
    stop_index: float | None = None
    target_premium: float | None = None


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str  # also the client order id (idempotency)
    decision_id: str
    action: Literal["ENTER", "EXIT", "ADJUST"]
    instrument: Instrument
    side: Literal["BUY", "SELL"]
    qty: int  # computed by guardrails/sizing.py, never by the agent
    limit_price: float
    stop_premium: float
    time_stop_at: datetime
    target_premium: float | None = None


# ENFORCE rules can reject a decision. SHADOW rules are evaluated and logged but never block; every new
# rule starts as SHADOW and is promoted only with written evidence (docs/LESSONS_FROM_SIDEHUSTLE.md L2).
RuleAuthority = Literal["ENFORCE", "SHADOW"]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    passed: bool
    reason_code: str
    detail: str = ""
    authority: RuleAuthority = "ENFORCE"

    @property
    def blocks(self) -> bool:
        return not self.passed and self.authority == "ENFORCE"


@dataclass(frozen=True)
class Verdict:
    results: tuple[RuleResult, ...]
    intent: OrderIntent | None = None

    @property
    def approved(self) -> bool:
        return not any(r.blocks for r in self.results)

    @property
    def blocking_failures(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if r.blocks)

    @property
    def shadow_failures(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if not r.passed and r.authority == "SHADOW")
