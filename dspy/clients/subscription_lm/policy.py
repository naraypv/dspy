from __future__ import annotations

from dataclasses import dataclass

from dspy.clients.subscription_lm.transport import RetryableProviderError


@dataclass(frozen=True)
class RateLimitPolicy:
    max_attempts: int | None = None
    cooldown_seconds: int = 300
    backoff_seconds: float = 0.0
    retryable_errors: tuple[type[BaseException], ...] = (RetryableProviderError,)

    def __post_init__(self) -> None:
        if self.max_attempts is not None and self.max_attempts < 1:
            raise ValueError("max_attempts must be positive when set.")
        if self.cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be non-negative.")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must be non-negative.")
        if not self.retryable_errors:
            raise ValueError("retryable_errors must not be empty.")

    def attempts_for_accounts(self, account_count: int) -> int:
        if account_count < 1:
            raise ValueError("account_count must be positive.")
        return account_count if self.max_attempts is None else min(self.max_attempts, account_count)

    def is_retryable(self, error: BaseException) -> bool:
        return isinstance(error, self.retryable_errors)

    def backoff_for_attempt(self, attempt: int) -> float:
        del attempt
        return self.backoff_seconds
