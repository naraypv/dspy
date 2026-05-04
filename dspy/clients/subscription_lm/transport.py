from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TransportResult:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class RetryableProviderError(RuntimeError):
    def __init__(self, *, provider: str, account_name: str, reason: str) -> None:
        self.provider = provider
        self.account_name = account_name
        self.reason = reason
        super().__init__(f"{provider} account {account_name} failed with retryable error: {reason}")


class FatalProviderError(RuntimeError):
    def __init__(self, *, provider: str, account_name: str, reason: str) -> None:
        self.provider = provider
        self.account_name = account_name
        self.reason = reason
        super().__init__(f"{provider} account {account_name} failed: {reason}")
