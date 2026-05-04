import json
import os

import pytest

from dspy.clients.subscription_lm import AccountRef, AccountRegistry, SecretValueError


def test_registry_stores_account_metadata_without_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    registry = AccountRegistry.from_env()

    account = AccountRef(
        name="minimax-main",
        provider="minimax",
        model="MiniMax-M2.7",
        auth="token_plan_api_key",
        env_key="MINIMAX_API_KEY_1",
        priority=5,
    )
    registry.upsert(account)

    loaded = AccountRegistry.from_env().get("minimax-main")
    assert loaded == account
    assert "MINIMAX_API_KEY_1" in registry.path.read_text()

    if os.name == "posix":
        assert oct(registry.path.stat().st_mode & 0o777) == "0o600"


def test_registry_rejects_raw_secret_looking_values(tmp_path, monkeypatch):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    registry = AccountRegistry.from_env()

    account = AccountRef(
        name="bad",
        provider="minimax",
        model="MiniMax-M2.7",
        auth="token_plan_api_key",
        env_key="sk-this-is-a-raw-secret",
    )

    with pytest.raises(SecretValueError):
        registry.upsert(account)


def test_registry_tolerates_unknown_fields_for_forward_compatibility(tmp_path, monkeypatch):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    registry = AccountRegistry.from_env()
    registry.path.parent.mkdir(parents=True, exist_ok=True)
    registry.path.write_text(
        json.dumps(
            {
                "version": 99,
                "accounts": [
                    {
                        "name": "codex-pro",
                        "provider": "codex",
                        "model": "gpt-5.3-codex",
                        "auth": "chatgpt",
                        "home": "/tmp/codex-home",
                        "priority": 1,
                        "future_field": "kept-by-newer-client",
                    }
                ],
            }
        )
    )

    account = registry.get("codex-pro")
    assert account.name == "codex-pro"
    assert account.provider == "codex"
    assert account.home == "/tmp/codex-home"


def test_registry_remove_returns_whether_account_existed(tmp_path, monkeypatch):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    registry = AccountRegistry.from_env()
    registry.upsert(AccountRef(name="cursor-max", provider="cursor", auth="browser", home="/tmp/cursor"))

    assert registry.remove("cursor-max") is True
    assert registry.remove("cursor-max") is False
    assert registry.list() == []
