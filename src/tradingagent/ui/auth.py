"""Dashboard login (DESIGN.md §5.1 step 1, §6.2). Separate from the Groww broker login.

Passphrase is stored as a scrypt hash in runtime/ui_auth.json. Sessions are server-side, in memory
(restart = log in again). Every POST needs the per-session CSRF token.
"""

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
MIN_PASSPHRASE_LEN = 10


def hash_passphrase(passphrase: str, salt: bytes | None = None) -> dict[str, str]:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(passphrase.encode(), salt=salt, **_SCRYPT)
    return {"salt": salt.hex(), "hash": digest.hex(), "algo": "scrypt-n14-r8-p1"}


def verify_passphrase(passphrase: str, record: dict[str, str]) -> bool:
    digest = hashlib.scrypt(passphrase.encode(), salt=bytes.fromhex(record["salt"]), **_SCRYPT)
    return hmac.compare_digest(digest.hex(), record["hash"])


def set_passphrase(path: Path, passphrase: str) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LEN:
        raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE_LEN} characters")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hash_passphrase(passphrase)), encoding="utf-8")


@dataclass
class Session:
    csrf: str
    expires_at: float


class SessionStore:
    def __init__(self, auth_file: Path, session_hours: int, max_failures: int = 5) -> None:
        self._auth_file = auth_file
        self._ttl = session_hours * 3600
        self._sessions: dict[str, Session] = {}
        self._failures: list[float] = []
        self._max_failures = max_failures

    @property
    def configured(self) -> bool:
        return self._auth_file.exists()

    def login(self, passphrase: str) -> tuple[str, Session] | None:
        now = time.time()
        self._failures = [t for t in self._failures if now - t < 300]
        if len(self._failures) >= self._max_failures:  # simple lockout: 5 failures / 5 min
            return None
        if not self.configured:
            return None
        record = json.loads(self._auth_file.read_text(encoding="utf-8"))
        if not verify_passphrase(passphrase, record):
            self._failures.append(now)
            return None
        sid = secrets.token_urlsafe(32)
        sess = Session(csrf=secrets.token_urlsafe(32), expires_at=now + self._ttl)
        self._sessions[sid] = sess
        return sid, sess

    def auto_login(self) -> tuple[str, Session]:
        """Passphrase-free session for ui.require_login=false (dev/PAPER only). Still carries a CSRF token."""
        sid = secrets.token_urlsafe(32)
        sess = Session(csrf=secrets.token_urlsafe(32), expires_at=time.time() + self._ttl)
        self._sessions[sid] = sess
        return sid, sess

    def get(self, sid: str | None) -> Session | None:
        if not sid or (sess := self._sessions.get(sid)) is None:
            return None
        if sess.expires_at < time.time():
            self._sessions.pop(sid, None)
            return None
        return sess

    def logout(self, sid: str | None) -> None:
        if sid:
            self._sessions.pop(sid, None)

    @property
    def locked_out(self) -> bool:
        now = time.time()
        return len([t for t in self._failures if now - t < 300]) >= self._max_failures
