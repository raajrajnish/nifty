import pytest

from tradingagent.paper.account import equity_from_ledger


def _ledger(tmp_path, rows):
    p = tmp_path / "l.csv"
    p.write_text("day,setup,net_inr\n" + "".join(f"{d},{s},{v}\n" for d, s, v in rows), encoding="utf-8")
    return p


def test_equity_peak_drawdown_and_today(tmp_path):
    p = _ledger(tmp_path, [("2026-10-05", "G1", 5000), ("2026-10-06", "G2", -8000), ("2026-10-07", "G1", 1000)])
    e = equity_from_ledger(200000, p, today="2026-10-07")
    assert e.equity == 198000 and e.realised == -2000
    assert e.start_of_day == 197000 and e.today == 1000
    assert e.peak == 205000 and e.drawdown_pct == pytest.approx(3.41, abs=0.01)


def test_no_ledger_means_start_capital(tmp_path):
    e = equity_from_ledger(200000, tmp_path / "missing.csv", today="2026-10-07")
    assert e.equity == e.start_of_day == e.peak == 200000 and e.drawdown_pct == 0


def test_limits_follow_equity(cfg):
    r = cfg.risk
    assert r.capital_basis == "equity"
    assert r.per_trade_risk_at(250000) == pytest.approx(2500)        # 1% of current equity
    assert r.daily_loss_limit_at(180000) == pytest.approx(5400)      # 3% of start-of-day equity
    assert r.drawdown_kill_at(220000) == pytest.approx(22000)        # 10% of peak
    fixed = r.model_copy(update={"capital_basis": "fixed"})
    assert fixed.per_trade_risk_at(250000) == pytest.approx(2000)    # fixed basis ignores equity
