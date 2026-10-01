import pytest

from tradingagent.broker.auth import GrowwAuth
from tradingagent.core.errors import BrokerAuthError

ENV = {"GROWW_API_KEY": "KEY-abc123", "GROWW_API_SECRET": "SECRET-xyz789"}
OK = lambda token: None  # noqa: E731


def test_missing_env(clock):
    st = GrowwAuth(clock, env={}, verifier=OK).acquire()
    assert not st.connected
    assert "GROWW_ACCESS_TOKEN" in (st.error or "")


def test_key_secret_without_secret_is_missing(clock):
    st = GrowwAuth(clock, env={"GROWW_API_KEY": "k"}, verifier=OK).acquire()
    assert not st.connected


def test_access_token_used_directly_and_verified(clock):
    verified, fetched = [], []
    auth = GrowwAuth(clock, env={"GROWW_ACCESS_TOKEN": "TOK-direct"},
                     fetcher=lambda k, s: fetched.append(1) or "x", verifier=verified.append)
    st = auth.acquire()
    assert st.connected and st.method == "access_token"
    assert auth.token() == "TOK-direct"
    assert verified == ["TOK-direct"] and fetched == []


def test_access_token_takes_priority_over_key_secret(clock):
    auth = GrowwAuth(clock, env={**ENV, "GROWW_ACCESS_TOKEN": "TOK-direct"},
                     fetcher=lambda k, s: "TOK-fetched", verifier=OK)
    assert auth.acquire().method == "access_token"
    assert auth.token() == "TOK-direct"


def test_key_secret_flow(clock):
    calls = []

    def fetch(key, secret):
        calls.append((key, secret))
        return "TOKEN-1"

    auth = GrowwAuth(clock, env=ENV, fetcher=fetch, verifier=OK)
    st = auth.acquire()
    assert st.connected and st.acquired_at == clock.now() and st.method == "key_secret"
    assert auth.token() == "TOKEN-1"
    assert calls == [("KEY-abc123", "SECRET-xyz789")]
    assert "TOKEN" not in repr(st)  # status object never carries the token


def test_expired_access_token_fails_verification_without_leaking(clock):
    def verify(token):
        raise RuntimeError(f"401 unauthorized token={token}")

    auth = GrowwAuth(clock, env={"GROWW_ACCESS_TOKEN": "TOK-expired"}, verifier=verify)
    st = auth.acquire()
    assert not st.connected and "TOK-expired" not in st.error and "expires daily" in st.error
    with pytest.raises(BrokerAuthError):
        auth.token()


def test_failure_never_echoes_secrets(clock):
    def fetch(key, secret):
        raise RuntimeError(f"401 for key={key} secret={secret}")

    st = GrowwAuth(clock, env=ENV, fetcher=fetch, verifier=OK).acquire()
    assert not st.connected
    assert "KEY-abc123" not in st.error and "SECRET-xyz789" not in st.error
    assert "approve" in st.error


def test_token_before_connect_raises(clock):
    with pytest.raises(BrokerAuthError):
        GrowwAuth(clock, env=ENV).token()
