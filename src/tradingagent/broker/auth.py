"""Daily Groww token acquisition (DESIGN.md §5.1). Isolated: secrets never leave this module.

Two supported ways to log in (checked against growwapi's installed source, 2026-09-29):
  A. GROWW_ACCESS_TOKEN — a token generated on the Groww Cloud API Keys page. One value, used directly
     via GrowwAPI(token). It expires daily, so it must be replaced each morning.
  B. GROWW_API_KEY + GROWW_API_SECRET — "approval" key: owner approves it daily on the Groww page, then we
     exchange it via GrowwAPI.get_access_token(api_key, secret=...), which returns the token string.
Either way the token is verified with get_user_profile() before we report "connected".
"""

import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from tradingagent.core.clock import Clock
from tradingagent.core.errors import BrokerAuthError

TokenFetcher = Callable[[str, str], str]
TokenVerifier = Callable[[str], None]


def _groww_fetch_token(api_key: str, secret: str) -> str:
    try:
        from growwapi import GrowwAPI  # the only other growwapi import besides groww_adapter.py
    except ImportError as e:
        raise BrokerAuthError("growwapi not installed: run `uv sync --extra broker`") from e
    token = GrowwAPI.get_access_token(api_key=api_key, secret=secret)
    if not isinstance(token, str) or not token:
        raise BrokerAuthError("Groww returned an empty access token")
    return token


def _groww_verify_token(token: str) -> None:
    try:
        from growwapi import GrowwAPI
    except ImportError as e:
        raise BrokerAuthError("growwapi not installed: run `uv sync --extra broker`") from e
    GrowwAPI(token).get_user_profile(timeout=10)  # raises GrowwAPIException if the token is bad/expired


@dataclass(frozen=True)
class AuthStatus:
    """The only auth information that may leave this module (UI, logs, agent never see secrets)."""

    connected: bool
    acquired_at: datetime | None = None
    error: str | None = None
    method: str | None = None  # "access_token" | "key_secret"


class GrowwAuth:
    def __init__(self, clock: Clock, env: Mapping[str, str] | None = None,
                 fetcher: TokenFetcher = _groww_fetch_token,
                 verifier: TokenVerifier = _groww_verify_token) -> None:
        self._clock = clock
        self._env = env if env is not None else os.environ
        self._fetcher = fetcher
        self._verifier = verifier
        self._token: str | None = None
        self._status = AuthStatus(connected=False)
        self._lock = threading.Lock()

    def status(self) -> AuthStatus:
        return self._status

    def acquire(self) -> AuthStatus:
        direct = self._env.get("GROWW_ACCESS_TOKEN", "").strip()
        key = self._env.get("GROWW_API_KEY", "").strip()
        secret = self._env.get("GROWW_API_SECRET", "").strip()
        secrets_ = [s for s in (direct, key, secret) if s]
        with self._lock:
            self._token = None
            if direct:
                method, hint = "access_token", " — the access token expires daily; generate a new one on Groww"
            elif key and secret:
                method, hint = "key_secret", " — did you approve today's key on the Groww Cloud API Keys page?"
            else:
                self._status = AuthStatus(False, error="set GROWW_ACCESS_TOKEN (or GROWW_API_KEY + "
                                                        "GROWW_API_SECRET) in .env")
                return self._status
            try:
                token = direct if direct else self._fetcher(key, secret)
                self._verifier(token)
            except Exception as e:  # any SDK failure means "not connected"
                msg = str(e)
                for s in secrets_:  # SDK errors can contain request data; never echo secrets
                    msg = msg.replace(s, "***")
                self._status = AuthStatus(False, error=f"{type(e).__name__}: {msg[:200]}{hint}", method=method)
                return self._status
            self._token = token
            self._status = AuthStatus(True, acquired_at=self._clock.now(), method=method)
            return self._status

    def token(self) -> str:
        """For broker/groww_adapter.py only."""
        if self._token is None:
            raise BrokerAuthError("not authenticated — run the daily Groww connect step")
        return self._token

    def clear(self) -> None:
        with self._lock:
            self._token = None
            self._status = AuthStatus(connected=False)
