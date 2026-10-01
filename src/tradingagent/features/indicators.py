"""Pure indicator functions (DESIGN.md §4.4). No I/O, no clock; each value at t uses only data ≤ t."""

import numpy as np
import pandas as pd


def wilder_rma(x: "pd.Series[float]", n: int) -> "pd.Series[float]":
    """Wilder's moving average (RMA): seed = SMA of the first n values, then (prev*(n-1) + x)/n."""
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    if len(vals) < n:
        return pd.Series(out, index=x.index)
    out[n - 1] = np.nanmean(vals[:n])
    for i in range(n, len(vals)):
        out[i] = (out[i - 1] * (n - 1) + vals[i]) / n
    return pd.Series(out, index=x.index)


def rsi(close: "pd.Series[float]", n: int = 14) -> "pd.Series[float]":
    """Wilder RSI. 100 when there are no losses in the window."""
    d = close.diff()
    gain, loss = d.clip(lower=0), (-d).clip(lower=0)
    ag, al = wilder_rma(gain.iloc[1:], n), wilder_rma(loss.iloc[1:], n)
    rs = ag / al
    out = 100 - 100 / (1 + rs)
    out[(al == 0) & ag.notna()] = 100.0
    return out.reindex(close.index)


def true_range(df: pd.DataFrame) -> "pd.Series[float]":
    prev = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    """Standard Supertrend. df: open/high/low/close. Returns columns atr, upper, lower, trend (+1 up / −1 down)."""
    atr = wilder_rma(true_range(df), n)
    mid = (df["high"] + df["low"]) / 2
    bu, bl = (mid + mult * atr).to_numpy(), (mid - mult * atr).to_numpy()
    close = df["close"].to_numpy()
    m = len(df)
    fu, fl, trend = np.full(m, np.nan), np.full(m, np.nan), np.zeros(m)
    for i in range(m):
        if np.isnan(bu[i]):
            continue
        if i == 0 or np.isnan(fu[i - 1]):
            fu[i], fl[i], trend[i] = bu[i], bl[i], 1.0
            continue
        fu[i] = bu[i] if (bu[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = bl[i] if (bl[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if trend[i - 1] == 1.0:
            trend[i] = -1.0 if close[i] < fl[i] else 1.0
        else:
            trend[i] = 1.0 if close[i] > fu[i] else -1.0
    trend[np.isnan(fu)] = np.nan
    return pd.DataFrame({"atr": atr, "upper": fu, "lower": fl, "trend": trend}, index=df.index)


def cpr(h: float, low: float, c: float) -> tuple[float, float, float]:
    """Central pivot range from yesterday's H/L/C → (pivot, TC, BC) with TC ≥ BC."""
    p = (h + low + c) / 3
    bc = (h + low) / 2
    tc = 2 * p - bc
    return p, max(tc, bc), min(tc, bc)


def camarilla(h: float, low: float, c: float) -> dict[str, float]:
    """Camarilla levels from yesterday's H/L/C."""
    r = h - low
    return {"R3": c + r * 1.1 / 4, "S3": c - r * 1.1 / 4, "R4": c + r * 1.1 / 2, "S4": c - r * 1.1 / 2}
