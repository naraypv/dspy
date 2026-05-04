import json

import pytest

from dspy.clients.subscription_lm import (
    AccountRef,
    ClaudeCodeTransport,
    CodexExecTransport,
    CursorAgentTransport,
    FatalProviderError,
    RetryableProviderError,
    SubprocessResult,
    redact_text,
)


def test_codex_transport_parses_jsonl_agent_message_and_usage():
    def runner(command, input_text, env):
        assert command[:4] == ["codex", "exec", "-", "--json"]
        assert input_text == "hello"
        return SubprocessResult(
            returncode=0,
            stdout="\n".join(
                [
                    json.dumps({"type": "thread.started"}),
                    json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}}),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
                        }
                    ),
                ]
            ),
            stderr="",
        )

    result = CodexExecTransport(runner=runner).complete(AccountRef(name="codex", provider="codex"), "hello")
    assert result.text == "answer"
    assert result.usage["total_tokens"] == 6


def test_cursor_transport_parses_result_json():
    def runner(command, input_text, env):
        assert command[:4] == ["agent", "-p", "--output-format", "json"]
        assert command[-1] == "hello"
        assert input_text == ""
        return SubprocessResult(
            returncode=0,
            stdout=json.dumps({"type": "result", "subtype": "success", "result": "cursor answer"}),
            stderr="",
        )

    result = CursorAgentTransport(runner=runner).complete(AccountRef(name="cursor", provider="cursor"), "hello")
    assert result.text == "cursor answer"


def test_cursor_transport_uses_home_for_oauth_account_isolation():
    def runner(command, input_text, env):
        assert env["HOME"] == "/tmp/cursor-home"
        return SubprocessResult(
            returncode=0,
            stdout=json.dumps({"type": "result", "subtype": "success", "result": "cursor answer"}),
            stderr="",
        )

    result = CursorAgentTransport(runner=runner).complete(
        AccountRef(name="cursor", provider="cursor", home="/tmp/cursor-home"), "hello"
    )
    assert result.text == "cursor answer"


def test_cursor_transport_passes_registered_model():
    def runner(command, input_text, env):
        assert command[:4] == ["agent", "-p", "--output-format", "json"]
        assert "--model" in command
        assert command[command.index("--model") + 1] == "auto"
        return SubprocessResult(
            returncode=0,
            stdout=json.dumps({"type": "result", "subtype": "success", "result": "cursor answer"}),
            stderr="",
        )

    result = CursorAgentTransport(runner=runner).complete(
        AccountRef(name="cursor", provider="cursor", model="auto"), "hello"
    )
    assert result.text == "cursor answer"


def test_claude_transport_parses_result_json_usage():
    def runner(command, input_text, env):
        assert command[:4] == ["claude", "-p", "--output-format", "json"]
        assert command[command.index("--setting-sources") + 1] == "project"
        assert "--no-session-persistence" in command
        assert "--disable-slash-commands" in command
        assert command[command.index("--mcp-config") + 1] == '{"mcpServers":{}}'
        assert command[command.index("--tools") + 1] == ""
        assert command[-1] == "hello"
        assert input_text == ""
        return SubprocessResult(
            returncode=0,
            stdout=json.dumps(
                {
                    "type": "result",
                    "result": "claude answer",
                    "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
                }
            ),
            stderr="",
        )

    result = ClaudeCodeTransport(runner=runner).complete(AccountRef(name="claude", provider="claude"), "hello")
    assert result.text == "claude answer"
    assert result.usage["total_tokens"] == 3


def test_claude_transport_classifies_json_auth_failure():
    def runner(command, input_text, env):
        return SubprocessResult(
            returncode=1,
            stdout=json.dumps({"api_error_status": 401, "result": "Invalid authentication credentials"}),
            stderr="",
        )

    with pytest.raises(FatalProviderError) as exc_info:
        ClaudeCodeTransport(runner=runner).complete(AccountRef(name="claude", provider="claude"), "hello")

    assert "auth_failed" in str(exc_info.value)


def test_claude_transport_classifies_json_budget_failure():
    def runner(command, input_text, env):
        return SubprocessResult(
            returncode=1,
            stdout=json.dumps({"subtype": "error_max_budget_usd", "errors": ["Reached maximum budget"]}),
            stderr="",
        )

    with pytest.raises(FatalProviderError) as exc_info:
        ClaudeCodeTransport(runner=runner).complete(AccountRef(name="claude", provider="claude"), "hello")

    assert "budget_exceeded" in str(exc_info.value)


def test_cli_transport_normalizes_rate_limit_without_leaking_prompt():
    def runner(command, input_text, env):
        return SubprocessResult(returncode=1, stdout="prompt copy", stderr="429 Too Many Requests for secret prompt")

    with pytest.raises(RetryableProviderError) as exc_info:
        CodexExecTransport(runner=runner).complete(AccountRef(name="codex", provider="codex"), "secret prompt")

    assert "secret prompt" not in str(exc_info.value)
    assert "codex" in str(exc_info.value)


def test_cli_transport_wraps_malformed_output_without_leaking_provider_output():
    def runner(command, input_text, env):
        return SubprocessResult(returncode=0, stdout='{"token": "sk-secret-value"', stderr="")

    account = AccountRef(name="codex", provider="codex", home="/tmp/codex-secret", env_key="MINIMAX_API_KEY_1")

    with pytest.raises(FatalProviderError) as exc_info:
        CodexExecTransport(runner=runner).complete(account, "secret prompt")

    rendered = str(exc_info.value)
    assert "malformed_output" in rendered
    assert "sk-secret-value" not in rendered
    assert "/tmp/codex-secret" not in rendered
    assert "MINIMAX_API_KEY_1" not in rendered
    assert "secret prompt" not in rendered


def test_redact_text_hides_secret_patterns_env_names_auth_paths_and_command_args():
    account = AccountRef(
        name="codex",
        provider="codex",
        env_key="MINIMAX_API_KEY_1",
        home="/tmp/codex-secret",
        command="/opt/codex-secret-bin",
    )

    redacted = redact_text(
        "sk-secret-value eyJabc MINIMAX_API_KEY_1 /tmp/codex-secret /opt/codex-secret-bin prompt-secret",
        account=account,
        command=["/opt/codex-secret-bin", "exec", "prompt-secret"],
    )

    assert "sk-secret-value" not in redacted
    assert "eyJabc" not in redacted
    assert "MINIMAX_API_KEY_1" not in redacted
    assert "/tmp/codex-secret" not in redacted
    assert "/opt/codex-secret-bin" not in redacted
    assert "prompt-secret" not in redacted
    assert "[redacted]" in redacted
