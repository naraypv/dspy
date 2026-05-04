from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from dspy.clients.subscription_lm.account import AccountRef


class AccountPoolExhaustedError(RuntimeError):
    """Raised when no account is currently available for a provider call."""


AccountPoolExhausted = AccountPoolExhaustedError


@dataclass
class AccountState:
    cooldown_until: float = 0.0
    consecutive_failures: int = 0
    last_error: str | None = None


class AccountPool:
    def __init__(self, accounts: list[AccountRef], now: Callable[[], float] | None = None) -> None:
        if not accounts:
            raise ValueError("At least one account is required.")
        self.accounts = list(accounts)
        self._now = now or time.time
        self._states = {account.name: AccountState() for account in accounts}
        self._positions: dict[int, int] = {}
        self._lock = RLock()

    def next_account(self) -> AccountRef:
        with self._lock:
            for priority in sorted({account.priority for account in self.accounts}):
                group = [account for account in self.accounts if account.priority == priority]
                start = self._positions.get(priority, 0) % len(group)
                for offset in range(len(group)):
                    index = (start + offset) % len(group)
                    account = group[index]
                    if self._is_available(account):
                        self._positions[priority] = (index + 1) % len(group)
                        return account
        raise AccountPoolExhausted("All subscription LM accounts are unavailable.")

    def mark_rate_limited(self, account_name: str, cooldown_seconds: int) -> None:
        with self._lock:
            state = self._states[account_name]
            state.cooldown_until = self._now() + cooldown_seconds
            state.consecutive_failures += 1
            state.last_error = "rate_limit"

    def mark_success(self, account_name: str) -> None:
        with self._lock:
            state = self._states[account_name]
            state.consecutive_failures = 0
            state.last_error = None

    def _is_available(self, account: AccountRef) -> bool:
        return self._states[account.name].cooldown_until <= self._now()
