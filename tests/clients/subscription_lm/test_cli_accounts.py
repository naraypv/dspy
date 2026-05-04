import json
from subprocess import CompletedProcess

from dspy.cli import main
from dspy.clients.subscription_lm import AccountRef


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
