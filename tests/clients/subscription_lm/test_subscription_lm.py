import pytest

import dspy
from dspy.clients.subscription_lm import (
    AccountRef,
    AccountRegistry,
    RateLimitPolicy,
    RetryableProviderError,
    SubscriptionLM,
    TransportResult,
)


class FakeTransport:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def complete(self, account, prompt, *, messages=None, kwargs=None):
        self.calls.append(account.name)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_subscription_lm_returns_dspy_outputs_and_records_redacted_history():
    transport = FakeTransport([TransportResult(text="done", usage={"prompt_tokens": 1, "completion_tokens": 1})])
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-pro", provider="codex", home="/tmp/codex")],
        transports={"codex": transport},
        cache=False,
    )

    assert lm("hello") == ["done"]
    assert lm.history[-1]["model"] == "subscription/codex"
    assert "auth" not in str(lm.history[-1]).lower()


def test_subscription_lm_falls_back_after_retryable_provider_error():
    transport = FakeTransport(
        [
            RetryableProviderError(provider="codex", account_name="codex-a", reason="rate_limit"),
            TransportResult(text="fallback"),
        ]
    )
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[
            AccountRef(name="codex-a", provider="codex"),
            AccountRef(name="codex-b", provider="codex"),
        ],
        transports={"codex": transport},
        cache=False,
    )

    assert lm("hello") == ["fallback"]
    assert transport.calls == ["codex-a", "codex-b"]


def test_subscription_lm_honors_configurable_rate_limit_policy():
    transport = FakeTransport(
        [
            RetryableProviderError(provider="codex", account_name="codex-a", reason="rate_limit"),
            TransportResult(text="should not be reached"),
        ]
    )
    sleep_calls = []
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[
            AccountRef(name="codex-a", provider="codex"),
            AccountRef(name="codex-b", provider="codex"),
        ],
        transports={"codex": transport},
        cache=False,
        rate_limit_policy=RateLimitPolicy(max_attempts=1, cooldown_seconds=17, backoff_seconds=0.25),
        sleep=sleep_calls.append,
    )

    with pytest.raises(RetryableProviderError):
        lm("hello")

    assert transport.calls == ["codex-a"]
    assert sleep_calls == [0.25]


def test_subscription_lm_response_records_sanitized_provider_metadata():
    transport = FakeTransport(
        [
            TransportResult(
                text="done",
                raw={"token": "sk-secret-value", "home": "/tmp/codex-secret", "provider_version": "1.2.3"},
            )
        ]
    )
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-pro", provider="codex", home="/tmp/codex-secret")],
        transports={"codex": transport},
        cache=False,
    )

    response = lm.forward(prompt="hello")

    assert response.provider_metadata == {
        "account": "codex-pro",
        "provider": "codex",
        "provider_version": "1.2.3",
    }
    assert "sk-secret-value" not in str(response.provider_metadata)
    assert "/tmp/codex-secret" not in str(response.provider_metadata)


def test_subscription_lm_declares_conservative_capabilities_locally():
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-a", provider="codex")],
        transports={"codex": FakeTransport([TransportResult(text="ok")])},
        cache=False,
    )

    assert SubscriptionLM.supports_function_calling.fget.__qualname__.startswith("SubscriptionLM.")
    assert SubscriptionLM.supports_reasoning.fget.__qualname__.startswith("SubscriptionLM.")
    assert SubscriptionLM.supports_response_schema.fget.__qualname__.startswith("SubscriptionLM.")
    assert SubscriptionLM.supported_params.fget.__qualname__.startswith("SubscriptionLM.")
    assert lm.supports_function_calling is False
    assert lm.supports_reasoning is False
    assert lm.supports_response_schema is False
    assert lm.supported_params == set()


def test_subscription_lm_can_be_created_from_cli_account_registry(tmp_path, monkeypatch):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    registry = AccountRegistry.from_env()
    registry.upsert(AccountRef(name="codex-a", provider="codex"))
    registry.upsert(AccountRef(name="cursor-a", provider="cursor"))
    transport = FakeTransport([TransportResult(text="registry answer")])

    lm = SubscriptionLM.from_registry(
        model="subscription/agent-pool",
        providers=["cursor"],
        transports={"cursor": transport},
        cache=False,
    )

    assert lm("hello") == ["registry answer"]
    assert transport.calls == ["cursor-a"]


def test_subscription_lm_uses_dspy_cache_for_repeated_requests():
    original_cache = dspy.cache
    dspy.configure_cache(enable_disk_cache=False, enable_memory_cache=True)
    transport = FakeTransport(
        [
            TransportResult(text="cached answer", usage={"prompt_tokens": 1, "completion_tokens": 1}),
            TransportResult(text="uncached answer"),
        ]
    )
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-a", provider="codex")],
        transports={"codex": transport},
        cache=True,
    )

    try:
        assert lm("hello") == ["cached answer"]
        assert lm("hello") == ["cached answer"]
    finally:
        dspy.cache = original_cache

    assert transport.calls == ["codex-a"]


def test_subscription_lm_copy_preserves_configuration_without_sharing_pool():
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-a", provider="codex")],
        transports={"codex": FakeTransport([TransportResult(text="copy answer")])},
        temperature=0.0,
    )

    copied = lm.copy(temperature=0.7)

    assert isinstance(copied, SubscriptionLM)
    assert copied is not lm
    assert copied.accounts == lm.accounts
    assert copied.pool is not lm.pool
    assert copied.history == []
    assert copied.kwargs["temperature"] == 0.7
    assert lm.kwargs["temperature"] == 0.0


@pytest.mark.asyncio
async def test_subscription_lm_supports_async_call_with_blocking_transports():
    transport = FakeTransport([TransportResult(text="async answer")])
    lm = SubscriptionLM(
        model="subscription/codex",
        accounts=[AccountRef(name="codex-a", provider="codex")],
        transports={"codex": transport},
        cache=False,
    )

    assert await lm.acall("hello") == ["async answer"]
    assert transport.calls == ["codex-a"]


def test_minimax_openai_compatible_path_is_forwarded_through_dspy_lm(monkeypatch):
    calls = []

    def fake_completion(*, request, cache, num_retries):
        del cache, num_retries
        calls.append(request)
        from litellm.utils import Choices, Message, ModelResponse

        return ModelResponse(choices=[Choices(message=Message(content="ok"))], model=request["model"])

    monkeypatch.setattr("dspy.clients.lm.litellm_completion", fake_completion)

    lm = dspy.LM(
        "openai/MiniMax-M2.7",
        api_base="https://api.minimax.io/v1",
        api_key="fake-test-key",
        cache=False,
    )
    assert lm("hello") == ["ok"]
    assert calls[0]["model"] == "openai/MiniMax-M2.7"
    assert calls[0]["api_base"] == "https://api.minimax.io/v1"
