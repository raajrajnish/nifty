"""Save expiry dates (from Groww) for a month range to data/expiries/<UNDERLYING>.csv (READ-ONLY, one-off).
Usage: uv run python scripts/fetch_expiries.py 2021-10 2023-11 [BANKNIFTY]   (default NIFTY)"""

import csv
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(".env")
from growwapi import GrowwAPI  # noqa: E402

start, end = sys.argv[1], sys.argv[2]
underlying = sys.argv[3] if len(sys.argv) > 3 else "NIFTY"
g = GrowwAPI(os.environ["GROWW_ACCESS_TOKEN"])
y, m = map(int, start.split("-"))
ey, em = map(int, end.split("-"))
out: set[str] = set()
path = Path(f"data/expiries/{underlying}.csv")
if path.exists():
    out |= {r["expiry"] for r in csv.DictReader(path.open(encoding="utf-8"))}
while (y, m) <= (ey, em):
    time.sleep(0.3)
    out |= set(g.get_expiries(exchange="NSE", underlying_symbol=underlying, year=y, month=m).get("expiries") or [])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["expiry"])
    for e in sorted(out):
        w.writerow([e])
print(f"{len(out)} expiries saved to {path} ({min(out)} → {max(out)})")
