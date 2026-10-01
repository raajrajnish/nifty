"""Indicators vs hand-calculated values, plus a no-look-ahead check."""

import numpy as np
import pandas as pd
import pytest

from tradingagent.features.indicators import camarilla, cpr, rsi, supertrend, true_range, wilder_rma


def test_wilder_rma_by_hand():
    x = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    r = wilder_rma(x, 3)
    assert np.isnan(r.iloc[1])
    assert r.iloc[2] == pytest.approx(2.0)                    # SMA seed of 1,2,3
    assert r.iloc[3] == pytest.approx((2.0 * 2 + 4) / 3)      # 2.6667
    assert r.iloc[4] == pytest.approx((r.iloc[3] * 2 + 5) / 3)


def test_rsi_by_hand():
    close = pd.Series([10.0, 11.0, 10.0, 12.0, 11.0, 13.0])
    # diffs: +1, −1, +2, −1, +2 → with n=2: seed gain = (1+0)/2 = .5, loss = (0+1)/2 = .5
    r = rsi(close, 2)
    assert r.iloc[2] == pytest.approx(50.0)
    # next: gain = (.5*1 + 2)/2 = 1.25, loss = (.5*1 + 0)/2 = .25 → RS 5 → RSI 83.333
    assert r.iloc[3] == pytest.approx(100 - 100 / 6)
    assert rsi(pd.Series([1.0, 2.0, 3.0, 4.0]), 2).iloc[-1] == 100.0  # no losses


def test_true_range_uses_previous_close():
    df = pd.DataFrame({"high": [10.0, 12.0], "low": [9.0, 11.5], "close": [9.5, 12.0]})
    assert true_range(df).tolist() == [1.0, 2.5]  # max(0.5, |12−9.5|, |11.5−9.5|)


def test_supertrend_flips_on_a_reversal():
    up = [100 + i for i in range(30)]
    down = [129 - 3 * i for i in range(30)]
    c = pd.Series(up + down, dtype=float)
    df = pd.DataFrame({"open": c, "high": c + 1, "low": c - 1, "close": c})
    st = supertrend(df, 10, 3)
    assert st["trend"].iloc[28] == 1.0 and st["trend"].iloc[-1] == -1.0
    flip = st["trend"].diff().fillna(0).ne(0) & st["trend"].shift(1).notna()
    assert flip.sum() == 1  # exactly one flip, up → down


def test_indicators_have_no_look_ahead():
    rng = np.random.default_rng(1)
    c = pd.Series(100 + rng.normal(size=200).cumsum())
    df = pd.DataFrame({"open": c, "high": c + 0.5, "low": c - 0.5, "close": c})
    full_st, full_rsi = supertrend(df), rsi(c)
    for t in (50, 120, 199):
        cut = df.iloc[: t + 1]
        assert supertrend(cut)["trend"].iloc[-1] == full_st["trend"].iloc[t]
        assert rsi(cut["close"]).iloc[-1] == pytest.approx(full_rsi.iloc[t])


def test_cpr_and_camarilla_formulas():
    # H=110, L=90, C=95 → P = 98.3333, (H+L)/2 = 100, 2P − 100 = 96.6667 → TC = 100, BC = 96.6667 (swapped)
    p, tc, bc = cpr(110.0, 90.0, 95.0)
    assert p == pytest.approx(98.33333, abs=1e-4)
    assert tc == pytest.approx(100.0) and bc == pytest.approx(96.66667, abs=1e-4)
    lv = camarilla(110.0, 90.0, 95.0)
    assert lv["R3"] == pytest.approx(95 + 20 * 1.1 / 4) and lv["S4"] == pytest.approx(95 - 20 * 1.1 / 2)
