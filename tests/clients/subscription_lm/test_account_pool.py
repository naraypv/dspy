import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from dspy.clients.subscription_lm import AccountPool, AccountPoolExhausted, AccountRef


def test_account_pool_uses_priority_then_round_robin():
    pool = AccountPool(
        [
            AccountRef(name="low", provider="codex", priority=10),
            AccountRef(name="high-a", provider="codex", priority=1),
            AccountRef(name="high-b", provider="codex", priority=1),
        ],
        now=lambda: 100.0,
    )

    assert pool.next_account().name == "high-a"
    assert pool.next_account().name == "high-b"
    assert pool.next_account().name == "high-a"


def test_account_pool_skips_cooldown_accounts():
    now = [100.0]
    pool = AccountPool(
        [
            AccountRef(name="a", provider="codex", priority=1),
            AccountRef(name="b", provider="codex", priority=1),
        ],
        now=lambda: now[0],
    )

    pool.mark_rate_limited("a", cooldown_seconds=30)
    assert pool.next_account().name == "b"

    now[0] = 131.0
    assert pool.next_account().name == "a"


def test_account_pool_raises_when_all_accounts_are_in_cooldown():
    pool = AccountPool([AccountRef(name="a", provider="codex")], now=lambda: 100.0)
    pool.mark_rate_limited("a", cooldown_seconds=30)

    with pytest.raises(AccountPoolExhausted):
        pool.next_account()


def test_account_pool_rotates_safely_under_concurrent_high_frequency_calls():
    accounts = [
        AccountRef(name="a", provider="codex"),
        AccountRef(name="b", provider="codex"),
        AccountRef(name="c", provider="codex"),
    ]

    def slow_clock():
        time.sleep(0.001)
        return time.monotonic()

    pool = AccountPool(accounts, now=slow_clock)
    worker_count = 24
    barrier = Barrier(worker_count)

    def pick_account():
        barrier.wait()
        return pool.next_account().name

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        selected = list(executor.map(lambda _: pick_account(), range(worker_count)))

    counts = Counter(selected)
    assert counts == {"a": 8, "b": 8, "c": 8}
