from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from dspy.clients.lm import LM
from dspy.clients.subscription_lm.account import AccountRef
from dspy.clients.subscription_lm.transport import FatalProviderError, RetryableProviderError, TransportResult

DEFAULT_MINIMAX_API_BASE = "https://api.minimax.io/v1"
LMFactory = Callable[..., Any]


class MiniMaxTransport:
    def __init__(self, lm_factory: LMFactory = LM) -> None:
        self.lm_factory = lm_factory

    def complete(
        self,
        account: AccountRef,
        prompt: str,
        *,
        messages: list[dict] | None = None,
        kwargs: dict | None = None,
    ) -> TransportResult:
        if not account.env_key:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_env_key")
        api_key = os.environ.get(account.env_key)
        if not api_key:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_api_key_env")
        if not account.model:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_model")

        request_kwargs = dict(kwargs or {})
        cache = bool(request_kwargs.pop("cache", False))
        api_base = account.metadata.get("api_base", DEFAULT_MINIMAX_API_BASE)
        try:
            lm = self.lm_factory(account.model, api_base=api_base, api_key=api_key, cache=cache, **request_kwargs)
            outputs = lm(prompt=prompt, messages=messages)
        except Exception as error:
            if _is_retryable(str(error)):
                raise RetryableProviderError(
                    provider=account.provider, account_name=account.name, reason="rate_limit"
                ) from error
            raise FatalProviderError(
                provider=account.provider, account_name=account.name, reason=error.__class__.__name__
            ) from error

        text = outputs[0] if outputs else ""
        if not isinstance(text, str):
            text = str(text)
        if not text:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_result")
        return TransportResult(text=text)


def _is_retryable(message: str) -> bool:
    lowered = message.lower()
    return "429" in lowered or "rate limit" in lowered or "too many requests" in lowered
