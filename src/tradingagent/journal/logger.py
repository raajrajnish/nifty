"""Append-only JSONL event log: journal/events/YYYY-MM-DD.jsonl (DESIGN.md §9)."""

import json
import threading
from pathlib import Path

from tradingagent.core.events import Event


class EventLogger:
    def __init__(self, root: Path, context: dict[str, str]) -> None:
        self._root = root
        self._context = context  # mode, stage, config_hash — stamped on every line
        self._lock = threading.Lock()
        root.mkdir(parents=True, exist_ok=True)

    def __call__(self, evt: Event) -> None:
        line = json.dumps({**evt.to_dict(), **self._context}, default=str, ensure_ascii=False)
        path = self._root / f"{evt.ts.date().isoformat()}.jsonl"
        with self._lock, path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
