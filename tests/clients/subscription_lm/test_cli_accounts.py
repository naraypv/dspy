import base64
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from dspy.cli import main
from dspy.clients.subscription_lm import AccountRef
from dspy.clients.subscription_lm.account_login import probe_provider_identity


def _fake_codex_id_token(*, email: str, account_id: str) -> str:
    def encode_json(data: dict) -> str:
        encoded = base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("ascii")
        return encoded.rstrip("=")

    claims = {
        "email": email,
        "sub": f"auth0|{account_id}",
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    return f"{encode_json({'alg': 'none'})}.{encode_json(claims)}."


def _write_codex_auth(home: Path, *, email: str, account_id: str) -> None:
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    (home / "auth.json").write_text(
        json.dumps(
            {
                "tokens": {
                    "id_token": _fake_codex_id_token(
                        email=email,
                        account_id=account_id,
                    )
                }
            }
        )
    )


def test_cli_add_list_status_and_remove_minimax_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY_1", "not-a-real-test-secret")

    assert (
        main(
            [
                "lm",
                "accounts",
                "add",
                "minimax",
                "--name",
                "mini",
                "--env-key",
                "MINIMAX_API_KEY_1",
                "--model",
                "MiniMax-M2.7",
            ]
        )
        == 0
    )
    assert "mini" in capsys.readouterr().out

    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["accounts"][0]["name"] == "mini"
    assert listed["accounts"][0]["env_key"] == "MINIMAX_API_KEY_1"
    assert "not-a-real-test-secret" not in json.dumps(listed)

    assert main(["lm", "accounts", "status", "--format", "json"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["accounts"][0]["env_present"] is True

    assert main(["lm", "accounts", "remove", "mini"]) == 0
    assert "removed" in capsys.readouterr().out


def test_cli_add_codex_with_login_invokes_provider_login(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    calls = []

    def fake_login(account):
        calls.append(account)
        return "codex login checked"

    monkeypatch.setattr("dspy.cli.run_provider_login", fake_login)

    assert (
        main(
            [
                "lm",
                "accounts",
                "add",
                "codex",
                "--name",
                "codex-pro",
                "--codex-home",
                str(tmp_path / "codex-home"),
                "--auth",
                "chatgpt",
                "--login",
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "codex login checked" in output
    assert calls[0].provider == "codex"
    assert calls[0].auth == "chatgpt"


def test_cli_login_codex_auto_names_and_isolates_accounts(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))

    def fake_login(account):
        home = tmp_path / "homes" / "codex" / "_login"
        _write_codex_auth(home, email="codex-a@example.com", account_id="account-a")
        assert account.home == str(home)
        return "codex login checked"

    monkeypatch.setattr("dspy.cli.run_provider_login", fake_login)

    assert main(["lm", "accounts", "login", "codex"]) == 0

    output = capsys.readouterr().out
    assert "codex login checked" in output
    assert "codex-1" in output
    assert "codex-a@example.com" in output

    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    account = listed["accounts"][0]
    assert account["name"] == "codex-1"
    assert account["home"] == str(tmp_path / "homes" / "codex" / "codex-1")
    assert account["metadata"]["identity_label"] == "codex-a@example.com"
    assert not (tmp_path / "homes" / "codex" / "_login").exists()


def test_cli_login_codex_deduplicates_same_authenticated_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))

    def fake_login(account):
        home = tmp_path / "homes" / "codex" / "_login"
        _write_codex_auth(home, email="same-codex@example.com", account_id="same-account")
        return "codex login checked"

    monkeypatch.setattr("dspy.cli.run_provider_login", fake_login)

    assert main(["lm", "accounts", "login", "codex"]) == 0
    capsys.readouterr()
    assert main(["lm", "accounts", "login", "codex"]) == 0

    output = capsys.readouterr().out
    assert "already registered as codex-1" in output
    assert not (tmp_path / "homes" / "codex" / "_login").exists()

    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [account["name"] for account in listed["accounts"]] == ["codex-1"]


def test_cli_login_codex_deduplicates_legacy_manual_account(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    legacy_home = tmp_path / "legacy-codex"
    _write_codex_auth(legacy_home, email="legacy-codex@example.com", account_id="legacy-account")

    assert (
        main(
            [
                "lm",
                "accounts",
                "add",
                "codex",
                "--name",
                "codex-legacy",
                "--codex-home",
                str(legacy_home),
            ]
        )
        == 0
    )
    capsys.readouterr()

    def fake_login(account):
        home = tmp_path / "homes" / "codex" / "_login"
        _write_codex_auth(home, email="legacy-codex@example.com", account_id="legacy-account")
        return "codex login checked"

    monkeypatch.setattr("dspy.cli.run_provider_login", fake_login)

    assert main(["lm", "accounts", "login", "codex"]) == 0

    assert "already registered as codex-legacy" in capsys.readouterr().out
    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [account["name"] for account in listed["accounts"]] == ["codex-legacy"]


def test_codex_identity_probe_requires_auth_file_identity(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return CompletedProcess(args=command, returncode=0, stdout="Logged in using ChatGPT")

    monkeypatch.setattr("subprocess.run", fake_run)

    with pytest.raises(ValueError, match=r"auth\.json"):
        probe_provider_identity(AccountRef(name="codex", provider="codex", home=str(tmp_path / "missing-auth")))

    assert calls == []


def test_cli_login_minimax_auto_names_and_deduplicates_same_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY_1", "minimax-test-key-one")

    assert main(["lm", "accounts", "login", "minimax"]) == 0
    assert "minimax-1" in capsys.readouterr().out

    assert main(["lm", "accounts", "login", "minimax"]) == 0
    assert "already registered as minimax-1" in capsys.readouterr().out

    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [account["name"] for account in listed["accounts"]] == ["minimax-1"]
    assert "minimax-test-key-one" not in json.dumps(listed)


def test_cli_login_minimax_adds_second_distinct_key_without_user_numbering(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("MINIMAX_API_KEY_1", "minimax-test-key-one")
    monkeypatch.setenv("MINIMAX_API_KEY_2", "minimax-test-key-two")

    assert main(["lm", "accounts", "login", "minimax", "--env-key", "MINIMAX_API_KEY_1"]) == 0
    capsys.readouterr()
    assert main(["lm", "accounts", "login", "minimax", "--env-key", "MINIMAX_API_KEY_2"]) == 0

    assert "minimax-2" in capsys.readouterr().out
    assert main(["lm", "accounts", "list", "--format", "json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [account["name"] for account in listed["accounts"]] == ["minimax-1", "minimax-2"]


def test_cli_doctor_reports_missing_environment_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DSPY_ACCOUNT_CONFIG_DIR", str(tmp_path))
    assert (
        main(
            [
                "lm",
                "accounts",
                "add",
                "minimax",
                "--name",
                "mini",
                "--env-key",
                "MISSING_MINIMAX_KEY",
                "--model",
                "MiniMax-M2.7",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert main(["lm", "accounts", "doctor"]) == 1
    assert "MISSING_MINIMAX_KEY" in capsys.readouterr().out


def test_cli_smoke_refuses_live_provider_call_without_explicit_confirmation(capsys):
    assert main(["lm", "accounts", "smoke", "--prompt", "reply OK"]) == 2

    assert "--yes-live" in capsys.readouterr().out


def test_cli_smoke_uses_registry_backed_subscription_lm(monkeypatch, capsys):
    calls = []

    class FakeLM:
        def __call__(self, prompt, **kwargs):
            calls.append(("call", prompt, kwargs))
            return ["OK"]

    def fake_from_registry(**kwargs):
        calls.append(("from_registry", kwargs))
        return FakeLM()

    monkeypatch.setattr("dspy.cli.SubscriptionLM.from_registry", fake_from_registry)

    assert (
        main(
            [
                "lm",
                "accounts",
                "smoke",
                "--provider",
                "codex",
                "--account",
                "codex-pro",
                "--model",
                "subscription/live-check",
                "--prompt",
                "reply OK",
                "--yes-live",
                "--format",
                "json",
            ]
        )
        == 0
    )

    assert calls[0] == (
        "from_registry",
        {
            "model": "subscription/live-check",
            "providers": ["codex"],
            "account_names": ["codex-pro"],
            "cache": False,
        },
    )
    assert calls[1] == ("call", "reply OK", {"cache": False})
    output = json.loads(capsys.readouterr().out)
    assert output == {"model": "subscription/live-check", "outputs": ["OK"]}


def test_cursor_login_uses_home_for_oauth_account_isolation(monkeypatch):
    calls = []

    def fake_run(command, env, check):
        calls.append((command, env, check))
        return CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    from dspy.cli import run_provider_login

    message = run_provider_login(AccountRef(name="cursor-a", provider="cursor", home="/tmp/cursor-home"))

    assert message == "cursor login completed"
    assert calls[0][0] == ["agent", "login"]
    assert calls[0][1]["HOME"] == "/tmp/cursor-home"


def test_cli_login_creates_missing_account_home(tmp_path, monkeypatch):
    home = tmp_path / "codex-home"
    calls = []

    def fake_run(command, env, check):
        calls.append((command, env, check))
        assert home.exists()
        return CompletedProcess(args=command, returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)

    from dspy.cli import run_provider_login

    message = run_provider_login(AccountRef(name="codex-a", provider="codex", home=str(home)))

    assert message == "codex login completed"
    assert calls[0][0] == ["codex", "login"]
    assert calls[0][1]["CODEX_HOME"] == str(home)
