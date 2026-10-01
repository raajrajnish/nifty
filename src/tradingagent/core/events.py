"""In-process event bus and event record (DESIGN.md §9)."""

import asyncio
import itertools
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_SECRET_KEYS = re.compile(r"(secret|token|api_key|password|passphrase|totp)", re.IGNORECASE)


def redact(obj: Any) -> Any:
    """Recursively replace values of secret-looking keys. Applied to every event payload."""
    if isinstance(obj, dict):
        return {k: ("***" if _SECRET_KEYS.search(str(k)) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


@dataclass(frozen=True)
class Event:
    type: str
    ts: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "type": self.type, "ts": self.ts.isoformat(), "payload": self.payload}


Handler = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._seq = itertools.count(1)
        self._handlers: list[Handler] = []
        self._queues: set[asyncio.Queue[Event]] = set()

    def publish(self, type_: str, ts: datetime, payload: dict[str, Any] | None = None) -> Event:
        evt = Event(type=type_, ts=ts, payload=redact(payload or {}), seq=next(self._seq))
        for h in list(self._handlers):
            h(evt)
        for q in list(self._queues):
            if q.full():
                q.get_nowait()  # slow consumer (e.g. a stalled browser tab) drops oldest, never blocks trading
            q.put_nowait(evt)
        return evt

    def subscribe(self, handler: Handler) -> None:
        self._handlers.append(handler)

    def open_queue(self, maxsize: int = 500) -> "asyncio.Queue[Event]":
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._queues.add(q)
        return q

    def close_queue(self, q: "asyncio.Queue[Event]") -> None:
        self._queues.discard(q)
