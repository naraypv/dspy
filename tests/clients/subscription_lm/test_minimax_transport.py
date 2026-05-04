from typing import ClassVar

import pytest

from dspy.clients.subscription_lm import AccountRef, FatalProviderError, MiniMaxTransport, RetryableProviderError


class FakeLM:
    calls: ClassVar[list[tuple[str, dict]]] = []

    def __init__(self, model, **kwargs):
        self.model = model
        self.kwargs = kwargs
        self.calls.append((model, kwargs))

    def __call__(self, prompt=None, messages=None):
        self.prompt = prompt
        self.messages = messages
        return ["minimax answer"]


def test_minimax_transport_uses_env_key_with_openai_compatible_dspy_lm(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY_1", "not-a-real-test-secret")
    FakeLM.calls = []
    account = AccountRef(
        name="mini-a",
        provider="minimax",
        model="openai/MiniMax-M2.7",
        env_key="MINIMAX_API_KEY_1",
    )

    result = MiniMaxTransport(lm_factory=FakeLM).complete(account, "hello", kwargs={"temperature": 0.2})

    assert result.text == "minimax answer"
    assert FakeLM.calls[0][0] == "openai/MiniMax-M2.7"
    assert FakeLM.calls[0][1]["api_base"] == "https://api.minimax.io/v1"
    assert FakeLM.calls[0][1]["api_key"] == "not-a-real-test-secret"
    assert FakeLM.calls[0][1]["temperature"] == 0.2


def test_minimax_transport_fails_when_env_key_is_missing(monkeypatch):
    monkeypatch.delenv("MISSING_MINIMAX_KEY", raising=False)
    account = AccountRef(
        name="mini-a",
        provider="minimax",
        model="openai/MiniMax-M2.7",
        env_key="MISSING_MINIMAX_KEY",
    )

    with pytest.raises(FatalProviderError) as exc_info:
        MiniMaxTransport(lm_factory=FakeLM).complete(account, "hello")

    assert "MISSING_MINIMAX_KEY" not in str(exc_info.value)
    assert "missing_api_key_env" in str(exc_info.value)


def test_minimax_transport_normalizes_rate_limits(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY_1", "not-a-real-test-secret")

    class RateLimitedLM(FakeLM):
        def __call__(self, prompt=None, messages=None):
            raise RuntimeError("429 Too Many Requests")

    account = AccountRef(
        name="mini-a",
        provider="minimax",
        model="openai/MiniMax-M2.7",
        env_key="MINIMAX_API_KEY_1",
    )

    with pytest.raises(RetryableProviderError):
        MiniMaxTransport(lm_factory=RateLimitedLM).complete(account, "hello")
