from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from dspy.clients.base_lm import BaseLM
from dspy.clients.cache import request_cache
from dspy.clients.subscription_lm.account import AccountRef
from dspy.clients.subscription_lm.cli_transport import ClaudeCodeTransport, CodexExecTransport, CursorAgentTransport
from dspy.clients.subscription_lm.minimax_transport import MiniMaxTransport
from dspy.clients.subscription_lm.policy import RateLimitPolicy
from dspy.clients.subscription_lm.pool import AccountPool, AccountPoolExhausted
from dspy.clients.subscription_lm.registry import AccountRegistry
from dspy.clients.subscription_lm.responses import build_chat_response
from dspy.clients.subscription_lm.security import sanitize_provider_metadata
from dspy.clients.subscription_lm.transport import TransportResult


class SubscriptionLM(BaseLM):
    """A DSPy LM facade that rotates across locally configured subscription accounts.

    `SubscriptionLM` is intended for provider CLIs and OpenAI-compatible API
    accounts whose credentials live outside source code. Account metadata comes
    from `AccountRef` objects or the local `AccountRegistry`; OAuth tokens and
    API keys remain in provider config directories or environment variables.
    """

    def __init__(
        self,
        model: str,
        accounts: list[AccountRef],
        transports: dict[str, Any] | None = None,
        cache: bool = True,
        rate_limit_policy: RateLimitPolicy | None = None,
        sleep: Callable[[float], None] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model=model, model_type="chat", cache=cache, **kwargs)
        self.accounts = list(accounts)
        self.pool = AccountPool(self.accounts)
        self.rate_limit_policy = rate_limit_policy or RateLimitPolicy()
        self._sleep = sleep or time.sleep
        self.transports = transports or {
            "claude": ClaudeCodeTransport(),
            "codex": CodexExecTransport(),
            "cursor": CursorAgentTransport(),
            "minimax": MiniMaxTransport(),
        }

    @classmethod
    def from_registry(
        cls,
        model: str,
        *,
        providers: list[str] | None = None,
        account_names: list[str] | None = None,
        registry: AccountRegistry | None = None,
        transports: dict[str, Any] | None = None,
        cache: bool = True,
        rate_limit_policy: RateLimitPolicy | None = None,
        **kwargs: Any,
    ) -> SubscriptionLM:
        registry = registry or AccountRegistry.from_env()
        accounts = registry.list()
        if providers is not None:
            provider_filter = set(providers)
            accounts = [account for account in accounts if account.provider in provider_filter]
        if account_names is not None:
            name_filter = set(account_names)
            accounts = [account for account in accounts if account.name in name_filter]
        if not accounts:
            raise ValueError("No subscription LM accounts matched the registry selection.")
        return cls(
            model=model,
            accounts=accounts,
            transports=transports,
            cache=cache,
            rate_limit_policy=rate_limit_policy,
            **kwargs,
        )

    @property
    def supports_function_calling(self) -> bool:
        return False

    @property
    def supports_reasoning(self) -> bool:
        return False

    @property
    def supports_response_schema(self) -> bool:
        return False

    @property
    def supported_params(self) -> set[str]:
        return set()

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        kwargs = dict(kwargs)
        cache = kwargs.pop("cache", self.cache)
        request = {
            "model": self.model,
            "prompt": prompt,
            "messages": messages,
            "kwargs": {**self.kwargs, **kwargs},
        }
        if cache:
            return self._cached_complete(request=request)
        return self._complete_request(request=request)

    async def aforward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        return await asyncio.to_thread(self.forward, prompt=prompt, messages=messages, **kwargs)

    @request_cache(cache_arg_name="request")
    def _cached_complete(self, *, request: dict[str, Any]) -> Any:
        return self._complete_request(request=request)

    def _complete_request(self, *, request: dict[str, Any]) -> Any:
        prompt = request["prompt"]
        messages = request["messages"]
        request_kwargs = request["kwargs"]
        request_prompt = prompt if prompt is not None else self._messages_to_prompt(messages or [])
        attempts = 0
        max_attempts = self.rate_limit_policy.attempts_for_accounts(len(self.accounts))
        last_error: BaseException | None = None

        while attempts < max_attempts:
            account = self.pool.next_account()
            attempts += 1
            transport = self.transports.get(account.provider)
            if transport is None:
                raise ValueError(f"No transport registered for provider: {account.provider}")
            try:
                result: TransportResult = transport.complete(
                    account,
                    request_prompt,
                    messages=messages,
                    kwargs=request_kwargs,
                )
            except Exception as error:
                if not self.rate_limit_policy.is_retryable(error):
                    raise
                last_error = error
                self.pool.mark_rate_limited(account.name, self.rate_limit_policy.cooldown_seconds)
                backoff_seconds = self.rate_limit_policy.backoff_for_attempt(attempts)
                if backoff_seconds:
                    self._sleep(backoff_seconds)
                continue
            self.pool.mark_success(account.name)
            return build_chat_response(
                model=self.model,
                text=result.text,
                usage=result.usage,
                provider_metadata=sanitize_provider_metadata(account=account, raw=result.raw),
            )

        if last_error is not None:
            raise last_error
        raise AccountPoolExhausted("No subscription LM account could service the request.")

    def copy(self, **kwargs: Any) -> SubscriptionLM:
        model = kwargs.pop("model", self.model)
        accounts = kwargs.pop("accounts", self.accounts)
        transports = kwargs.pop("transports", self.transports)
        cache = kwargs.pop("cache", self.cache)
        rate_limit_policy = kwargs.pop("rate_limit_policy", self.rate_limit_policy)
        sleep = kwargs.pop("sleep", self._sleep)
        lm_kwargs = dict(self.kwargs)
        for key, value in kwargs.items():
            if value is None:
                lm_kwargs.pop(key, None)
            else:
                lm_kwargs[key] = value
        return type(self)(
            model=model,
            accounts=list(accounts),
            transports=dict(transports),
            cache=cache,
            rate_limit_policy=rate_limit_policy,
            sleep=sleep,
            **lm_kwargs,
        )

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        parts = []
        for message in messages:
            content = message.get("content", "")
            parts.append(content if isinstance(content, str) else str(content))
        return "\n".join(parts)
