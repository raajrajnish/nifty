import pytest

from tradingagent.sim.costs import CostModel


def test_round_trip_matches_hand_calculation(cfg):
    """Buy 65 @ 140, sell 65 @ 145 (1 lot) — computed by hand from config/costs.yaml (2026-10-01):
    buy turnover 9,100; sell turnover 9,425; total 18,525
    brokerage 2 × 20                      = 40.00
    STT 0.15% × 9,425                     = 14.1375
    exchange 0.03503% × 18,525            =  6.48931
    SEBI ₹10/crore × 18,525               =  0.018525
    stamp 0.003% × 9,100                  =  0.273
    GST 18% × (40 + 6.48931 + 0.018525)   =  8.37141
    total                                 ≈ 69.29
    """
    c = CostModel(cfg.costs).round_trip(140.0, 145.0, 65)
    assert c.brokerage == 40.0
    assert c.stt == pytest.approx(14.1375)
    assert c.exchange == pytest.approx(6.48931, abs=1e-5)
    assert c.sebi == pytest.approx(0.018525)
    assert c.stamp == pytest.approx(0.273)
    assert c.gst == pytest.approx(8.37141, abs=1e-4)
    assert c.total == pytest.approx(69.29, abs=0.01)


def test_tbd_costs_refuse(cfg):
    bad = cfg.costs.model_copy(update={"gst_pct": cfg.costs.gst_pct.model_copy(update={"value": "TBD"})})
    with pytest.raises(ValueError, match="TBD"):
        CostModel(bad)
