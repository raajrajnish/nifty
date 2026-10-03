"""LLM take/skip SHADOW filter for G1/G2 (spec: docs/reports/2026-10-03_llm_shadow_filter.md).

Shadow only: for each G1/G2 paper trade it records an LLM decision (TAKE/SKIP + reasons + sources) and, once a
day, a morning "risk of the day" note. It never changes, delays or blocks a paper trade:
  * calls run in background threads; the engine loop never waits;
  * every failure (no key, over budget, API error, refusal, bad JSON) becomes a recorded NO_DECISION;
  * live sessions only — a replay would read today's news about a past day (look-ahead), so it is never called there.
"""

import hashlib
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "llm_shadow.yaml"
EVENTS = ROOT / "config" / "event_calendar.yaml"
LEDGER = ROOT / "data" / "paper" / "llm_shadow.jsonl"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SETUP_NOTES = {
    "G1": "Narrow-range opening breakout on a day that opened outside yesterday's range. Backtest +₹833/trade "
          "(2023-12..2026-09), but its direction FAILED on untouched Nifty 2021-23 and on Bank Nifty. Puts carried "
          "almost all of the profit; calls were about break-even.",
    "G2": "TWAP pullback on a calm day that opened outside yesterday's range; -30% stop, hold to 15:10. Corrected "
          "backtest +₹300/trade, not robust; an independent review found its profit is not directional (stop "
          "geometry). Puts carried most of the profit.",
}

SYSTEM_V1 = """You are an independent risk reviewer for a PAPER-trading research project on Indian markets \
(Nifty and Bank Nifty index options, and large NSE stocks). Nothing you say places an order. Each trade already \
happened by a fixed, frozen rule; your job is to judge, from today's context, whether THIS signal looks more likely \
than usual to fail.

How to work:
- Search the web for news from the last 24 hours that matters for this trade's instrument: Indian market news, \
RBI/government announcements, company news for a stock trade, big index-heavyweight news, and overnight global \
markets. Prefer reputable financial sources.
- Weigh that with the market facts and the event calendar you are given.
- Be calibrated. A normal day with no specific risk → TAKE. Choose SKIP only when you can name a concrete, current \
reason this setup's signal is likely to fail (e.g. a scheduled event during the holding period that could reverse \
the move, news pointing the other way, an abnormal market state). Do not SKIP merely because markets are \
uncertain — they always are.
- Do not predict prices. Judge only whether today's context undermines this particular setup's logic.
- Reply only with the JSON object required by the output schema."""

MORNING_SYSTEM_V1 = """You are an independent risk reviewer for a PAPER-trading research project on the Nifty 50 \
index (India, NSE). Before the session, write a short "risk of the day" note: search the web for the last 24 hours \
of news relevant to Nifty today (Indian market news, RBI/government, index heavyweights, overnight global markets) \
and combine it with the event calendar. Classify the day as NORMAL, EVENT_RISK (a scheduled or developing event \
could cause a sharp move or reversal during the session) or AVOID (conditions so abnormal that rule-based intraday \
signals are unreliable). Be calibrated: most days are NORMAL. Reply only with the JSON object required by the \
output schema."""

REASON_TAGS = ["NO_SPECIFIC_RISK", "SCHEDULED_EVENT_TODAY", "SCHEDULED_EVENT_SOON", "NEWS_SUPPORTS_TRADE",
               "NEWS_AGAINST_TRADE", "GLOBAL_CUES_SUPPORT", "GLOBAL_CUES_AGAINST", "HIGH_VOLATILITY", "LOW_VOLATILITY",
               "TREND_SUPPORTS", "TREND_AGAINST", "EXPIRY_DYNAMICS", "KNOWN_SETUP_WEAKNESS", "LATE_IN_SESSION",
               "STOCK_SPECIFIC_NEWS", "OTHER"]

# v2 (2026-10-04, forward tournament): structured reasons so outcomes can later be regressed on them.
SIGNAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["TAKE", "SKIP"]},
        "confidence": {"type": "number"},
        "reason_tags": {"type": "array", "items": {"type": "string", "enum": REASON_TAGS}},
        "news_for_trade": {"type": "number"},
        "event_risk": {"type": "number"},
        "global_for_trade": {"type": "number"},
        "volatility_view": {"type": "number"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "key_news": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decision", "confidence", "reason_tags", "news_for_trade", "event_risk", "global_for_trade",
                 "volatility_view", "reasons", "key_news"],
    "additionalProperties": False,
}
STRUCTURED_HELP = ("Also fill the structured fields: reason_tags = every tag from the allowed list that drove your "
                   "decision; news_for_trade = -1 (news clearly against this trade) .. 0 (neutral/none) .. 1 (clearly "
                   "supports it); event_risk = 0 (no event risk) .. 1 (major event during the holding period); "
                   "global_for_trade = -1 .. 1 (overnight/global cues against or for this trade's direction); "
                   "volatility_view = -1 (unusually calm) .. 1 (unusually stormy).")
MORNING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "day_view": {"type": "string", "enum": ["NORMAL", "EVENT_RISK", "AVOID"]},
        "confidence": {"type": "number"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "key_news": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["day_view", "confidence", "reasons", "key_news"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------- config / ledger / cost
@dataclass(frozen=True)
class ShadowConfig:
    enabled: bool = True
    model: str = "claude-sonnet-5-5"
    effort: str = "medium"
    max_tokens: int = 4000
    timeout_s: float = 120.0
    web_search_max_uses: int = 4
    monthly_cap_inr: float = 500.0
    max_calls_per_day: int = 12
    usd_inr: float = 88.0
    prices_usd_per_mtok: dict[str, dict[str, float]] = field(default_factory=dict)
    web_search_usd_each: float = 0.01
    prompt_version: str = "v1"

    @classmethod
    def load(cls, path: Path = CONFIG) -> "ShadowConfig":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        return cls(**{k: v for k, v in (raw or {}).items() if k in cls.__dataclass_fields__})


def cost_inr(cfg: ShadowConfig, usage: dict[str, int]) -> float:
    p = cfg.prices_usd_per_mtok.get(cfg.model, {"input": 2.0, "output": 10.0})
    inp = usage.get("input_tokens", 0) + 1.25 * usage.get("cache_creation_input_tokens", 0) \
        + 0.1 * usage.get("cache_read_input_tokens", 0)
    usd = inp / 1e6 * p["input"] + usage.get("output_tokens", 0) / 1e6 * p["output"] \
        + usage.get("web_search_requests", 0) * cfg.web_search_usd_each
    return round(usd * cfg.usd_inr, 2)


class Ledger:
    def __init__(self, path: Path = LEDGER) -> None:
        self.path = path
        self._lock = threading.Lock()

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as f:
            return [json.loads(x) for x in f if x.strip()]

    def month_spend_inr(self, day: date) -> float:
        return sum(float(r.get("cost_inr") or 0) for r in self.rows() if str(r.get("day", ""))[:7] == f"{day:%Y-%m}")

    def calls_on(self, day: date) -> int:
        return sum(1 for r in self.rows() if r.get("day") == str(day) and r.get("called"))

    def has(self, day: date, kind: str, setup: str | None) -> bool:
        return any(r.get("day") == str(day) and r.get("kind") == kind and r.get("setup") == setup for r in self.rows())

    def append(self, rec: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")


def load_events(day: date, path: Path = EVENTS) -> list[dict[str, Any]]:
    """Calendar entries within ±3 days of `day` (verified and unverified, flagged)."""
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for e in raw.get("events") or []:
        d = e.get("date")
        d = d if isinstance(d, date) else date.fromisoformat(str(d))
        if abs((d - day).days) <= 3:
            out.append({"date": str(d), "event": e.get("event"), "verified": bool(e.get("verified"))})
    return out


# ---------------------------------------------------------------------------- prompts
def signal_prompt(setup: str, state: dict[str, Any], events: list[dict[str, Any]]) -> str:
    st, mkt = state["setups"][setup], state["market"]
    tr = st.get("trade") or {}
    facts = {
        "date": state["day"], "now_ist": state.get("as_of"), "expiry": state.get("expiry"),
        "nifty": mkt.get("index"), "prev_close": mkt.get("prev_close"), "change_pct": mkt.get("change_pct"),
        "day_open": mkt.get("day_open"), "day_high": mkt.get("day_high"), "day_low": mkt.get("day_low"),
        "prev_day_high": mkt.get("pdh"), "prev_day_low": mkt.get("pdl"),
        "opening_range": [mkt.get("or_low"), mkt.get("or_high")], "twap": mkt.get("twap"), "india_vix": mkt.get("vix"),
        "setup_checks": st.get("checks"),
        "trade": {k: tr.get(k) for k in ("side", "strike", "entry_ts", "entry_px", "stop_px")},
    }
    return (f"Setup {setup}: {SETUP_NOTES[setup]}\n\nRule description: {st.get('summary', '')}\n\n"
            f"The {setup} signal fired. Market facts (JSON):\n{json.dumps(facts, default=str)}\n\n"
            f"Event calendar near today (verified=false means not yet checked against the official source):\n"
            f"{json.dumps(events)}\n\nShould this {tr.get('side')} trade be TAKEN or SKIPPED today? "
            f"confidence = your probability (0-1) that your decision is right. 2-4 short reasons.")


def morning_prompt(day: date, events: list[dict[str, Any]]) -> str:
    return (f"Date: {day} (India). Event calendar near today:\n{json.dumps(events)}\n\nWrite the risk-of-the-day "
            f"classification. confidence = probability (0-1) your classification is right. 2-4 short reasons.")


# ---------------------------------------------------------------------------- API call (never raises)
def call_claude(client: Any, cfg: ShadowConfig, system: str, user: str,
                schema: dict[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, str]], dict[str, int], str]:
    """Returns (parsed JSON or None, web sources actually retrieved, usage totals, error text)."""
    import anthropic

    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": cfg.web_search_max_uses,
              "user_location": {"type": "approximate", "country": "IN", "timezone": "Asia/Kolkata"}}]
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_creation_input_tokens": 0,
             "cache_read_input_tokens": 0, "web_search_requests": 0}
    sources: list[dict[str, str]] = []
    try:
        for _ in range(4):                                   # first call + up to 3 pause_turn continuations
            resp = client.beta.messages.create(
                model=cfg.model, max_tokens=cfg.max_tokens, system=system, messages=messages, tools=tools,
                output_config={"effort": cfg.effort, "format": {"type": "json_schema", "schema": schema}},
                betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"}, timeout=cfg.timeout_s)
            u = resp.usage
            for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
                usage[k] += int(getattr(u, k, 0) or 0)
            stu = getattr(u, "server_tool_use", None)
            usage["web_search_requests"] += int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0
            for b in resp.content:
                if b.type == "web_search_tool_result" and isinstance(b.content, list):
                    sources += [{"url": r.url, "title": getattr(r, "title", "")} for r in b.content
                                if getattr(r, "type", "") == "web_search_result"]
            if resp.stop_reason == "pause_turn":
                messages = [messages[0], {"role": "assistant", "content": resp.content}]
                continue
            if resp.stop_reason == "refusal":
                return None, sources, usage, f"refusal: {getattr(resp, 'stop_details', None)}"
            tail: list[str] = []                             # the answer = text blocks after the last tool block
            for b in reversed(resp.content):
                if b.type != "text":
                    if tail:
                        break
                    continue
                tail.insert(0, b.text)
            if not tail:
                return None, sources, usage, f"no text (stop_reason={resp.stop_reason})"
            answer = "".join(tail).strip()
            try:
                return json.loads(answer), sources, usage, ""
            except json.JSONDecodeError:
                return None, sources, usage, f"bad JSON: {answer[:200]}"
        return None, sources, usage, "pause_turn limit reached"
    except anthropic.AuthenticationError:
        return None, sources, usage, "authentication failed (check ANTHROPIC_API_KEY)"
    except anthropic.RateLimitError:
        return None, sources, usage, "rate limited"
    except anthropic.APIStatusError as e:
        return None, sources, usage, f"API error {e.status_code}: {str(e)[:200]}"
    except anthropic.APIConnectionError as e:
        return None, sources, usage, f"connection error: {str(e)[:200]}"
    except Exception as e:  # never let the shadow filter break anything
        return None, sources, usage, f"{type(e).__name__}: {str(e)[:200]}"


# ---------------------------------------------------------------------------- decide (records always)
def decide(kind: str, day: date, setup: str | None, user: str, cfg: ShadowConfig, ledger: Ledger,
           now: Callable[[], datetime], client_factory: Callable[[], Any] | None = None,
           extra: dict[str, Any] | None = None) -> dict[str, Any]:
    system = SYSTEM_V1 if kind == "signal" else MORNING_SYSTEM_V1
    rec: dict[str, Any] = {"day": str(day), "kind": kind, "setup": setup, **(extra or {}), "model": cfg.model,
                           "prompt_version": cfg.prompt_version, "asked_at": now().isoformat(timespec="seconds"),
                           "input_hash": hashlib.sha256((system + user).encode()).hexdigest()[:16],
                           "called": False, "cost_inr": 0.0}
    why_not = ""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        why_not = "no ANTHROPIC_API_KEY"
    elif ledger.month_spend_inr(day) >= cfg.monthly_cap_inr:
        why_not = f"monthly cap ₹{cfg.monthly_cap_inr:.0f} reached"
    elif ledger.calls_on(day) >= cfg.max_calls_per_day:
        why_not = f"daily call limit {cfg.max_calls_per_day} reached"
    if why_not:
        ledger.append({**rec, "decision": "NO_DECISION", "error": why_not, "decided_at": now().isoformat()})
        return rec | {"decision": "NO_DECISION", "error": why_not}
    if client_factory is None:
        import anthropic
        client_factory = lambda: anthropic.Anthropic(max_retries=1)  # noqa: E731
    t0 = now()
    data, sources, usage, err = call_claude(client_factory(), cfg, system, user,
                                            SIGNAL_SCHEMA if kind == "signal" else MORNING_SCHEMA)
    out = {**rec, "called": True, "decided_at": now().isoformat(timespec="seconds"),
           "latency_s": round((now() - t0).total_seconds(), 1), "usage": usage, "cost_inr": cost_inr(cfg, usage),
           "sources": sources[:20], "error": err}
    if data is None:
        out["decision"] = "NO_DECISION"
    elif kind == "signal":
        out |= {k: data.get(k) for k in ("confidence", "reason_tags", "news_for_trade", "event_risk",
                                         "global_for_trade", "volatility_view", "reasons", "key_news")}
        out["decision"] = data["decision"]
    else:
        out |= {"decision": data["day_view"], "confidence": data["confidence"], "reasons": data["reasons"],
                "key_news": data["key_news"]}
    ledger.append(out)
    return out


# ---------------------------------------------------------------------------- live-session driver
class ShadowRunner:
    """Called from the live paper loop after each batch of events. Starts at most one background call per
    (day, morning) and per (day, setup) trade. Never blocks; never touches the engine's state."""

    def __init__(self, cfg: ShadowConfig, ledger: Ledger, now: Callable[[], datetime],
                 client_factory: Callable[[], Any] | None = None, log: Callable[[str], None] = print,
                 start_thread: Callable[[Callable[[], None]], None] | None = None) -> None:
        self.cfg, self.ledger, self.now, self.client_factory, self.log = cfg, ledger, now, client_factory, log
        self.started: set[tuple[str, str | None]] = set()
        self.start_thread = start_thread or (lambda fn: threading.Thread(target=fn, daemon=True).start())

    def tick(self, engine: Any) -> None:
        if not self.cfg.enabled:
            return
        day = engine.day
        if ("morning", None) not in self.started and not self.ledger.has(day, "morning", None):
            self.started.add(("morning", None))
            ev = load_events(day)
            self._spawn(lambda: decide("morning", day, None, morning_prompt(day, ev), self.cfg, self.ledger,
                                       self.now, self.client_factory))
        state = engine.state()
        for name, st in state["setups"].items():
            tr = st.get("trade") or {}
            if not tr.get("entry_ts") or ("signal", name) in self.started or self.ledger.has(day, "signal", name):
                continue
            self.started.add(("signal", name))
            user = signal_prompt(name, state, load_events(day))
            extra = {"signal_ts": tr.get("entry_ts"), "side": tr.get("side"), "strike": tr.get("strike"),
                     "entry_px": tr.get("entry_px")}
            def ask(n: str = name, u: str = user, x: dict[str, Any] = extra) -> None:
                decide("signal", day, n, u, self.cfg, self.ledger, self.now, self.client_factory, x)

            self._spawn(ask)
            self.log(f"LLM shadow: asked about {name} {tr.get('side')} (shadow only — the paper trade is unchanged)")

    def _spawn(self, fn: Callable[[], Any]) -> None:
        def safe() -> None:
            try:
                fn()
            except Exception as e:  # pragma: no cover - decide() already catches everything
                self.log(f"LLM shadow error (ignored): {e}")
        self.start_thread(safe)
