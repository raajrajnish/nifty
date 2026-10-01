"""Transaction cost model for option BUYING (DESIGN.md §4.10), driven by config/costs.yaml."""

from dataclasses import dataclass

from tradingagent.config.models import CostsConfig


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    stamp: float
    gst: float

    @property
    def total(self) -> float:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst


def _v(entry: object) -> float:
    value = getattr(entry, "value")  # noqa: B009
    if value == "TBD":
        raise ValueError("costs.yaml still has TBD values")
    return float(value)


class CostModel:
    def __init__(self, cfg: CostsConfig) -> None:
        self.brokerage = _v(cfg.brokerage_per_order)
        self.stt = _v(cfg.stt_sell_pct_of_premium) / 100
        self.exch = _v(cfg.exchange_txn_pct_of_premium) / 100
        self.sebi = _v(cfg.sebi_fee_per_crore) / 1e7
        self.gst = _v(cfg.gst_pct) / 100
        self.stamp = _v(cfg.stamp_duty_buy_pct) / 100

    def round_trip(self, buy_px: float, sell_px: float, qty: int) -> CostBreakdown:
        """Charges for one buy order + one sell order (spread/slippage is NOT included here)."""
        buy_t, sell_t = buy_px * qty, sell_px * qty
        brokerage = 2 * self.brokerage
        exchange = (buy_t + sell_t) * self.exch
        sebi = (buy_t + sell_t) * self.sebi
        return CostBreakdown(
            brokerage=brokerage, stt=sell_t * self.stt, exchange=exchange, sebi=sebi,
            stamp=buy_t * self.stamp, gst=(brokerage + exchange + sebi) * self.gst,
        )
