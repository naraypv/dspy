from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import ClassVar

from dspy.clients.subscription_lm.account import AccountRef
from dspy.clients.subscription_lm.security import redact_text
from dspy.clients.subscription_lm.transport import (
    FatalProviderError,
    RetryableProviderError,
    SubprocessResult,
    TransportResult,
)

Runner = Callable[[list[str], str, dict[str, str]], SubprocessResult]


def _default_runner(command: list[str], input_text: str, env: dict[str, str]) -> SubprocessResult:
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        env={**os.environ, **env},
        check=False,
    )
    return SubprocessResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)


class BaseCliTransport:
    command_name: ClassVar[str]
    args: ClassVar[tuple[str, ...]]
    prompt_via_stdin: ClassVar[bool] = False

    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner or _default_runner

    def complete(
        self,
        account: AccountRef,
        prompt: str,
        *,
        messages: list[dict] | None = None,
        kwargs: dict | None = None,
    ) -> TransportResult:
        del messages, kwargs
        command = [account.command or self.command_name, *self.args]
        command.extend(self._model_args(account))
        input_text = ""
        if self.prompt_via_stdin:
            input_text = prompt
        else:
            command.append(prompt)
        result = self.runner(command, input_text, self._account_env(account))
        if result.returncode != 0:
            self._raise_for_failure(account, result)
        return self._parse_success(account, result.stdout)

    def _parse_success(self, account: AccountRef, stdout: str) -> TransportResult:
        raise NotImplementedError

    def _model_args(self, account: AccountRef) -> list[str]:
        if not account.model:
            return []
        return ["--model", account.model]

    def _load_json(self, account: AccountRef, stdout: str) -> dict:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as error:
            reason = redact_text("malformed_output", account=account)
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason=reason) from error

    def _account_env(self, account: AccountRef) -> dict[str, str]:
        if not account.home:
            return {}
        home = str(Path(account.home).expanduser())
        if account.provider == "codex":
            return {"CODEX_HOME": home}
        if account.provider == "claude":
            return {"CLAUDE_CONFIG_DIR": home}
        if account.provider == "cursor":
            return {"HOME": home}
        return {}

    def _raise_for_failure(self, account: AccountRef, result: SubprocessResult) -> None:
        output_lower = f"{result.stderr}\n{result.stdout}".lower()
        if "429" in output_lower or "rate limit" in output_lower or "too many requests" in output_lower:
            raise RetryableProviderError(provider=account.provider, account_name=account.name, reason="rate_limit")
        raise FatalProviderError(provider=account.provider, account_name=account.name, reason="cli_failed")


class CodexExecTransport(BaseCliTransport):
    command_name = "codex"
    args = ("exec", "-", "--json")
    prompt_via_stdin = True

    def _parse_success(self, account: AccountRef, stdout: str) -> TransportResult:
        text = ""
        usage = {}
        raw = {}
        for line in stdout.splitlines():
            if not line.strip():
                continue
            event = self._load_json(account, line)
            raw = event
            if event.get("type") == "item.completed" and event.get("item", {}).get("type") == "agent_message":
                text = event["item"].get("text", text)
            if event.get("type") == "turn.completed":
                usage = event.get("usage", usage)
        if not text:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_result")
        return TransportResult(text=text, usage=usage, raw=raw)


class CursorAgentTransport(BaseCliTransport):
    command_name = "agent"
    args = ("-p", "--output-format", "json")

    def _parse_success(self, account: AccountRef, stdout: str) -> TransportResult:
        event = self._load_json(account, stdout)
        text = event.get("result", "")
        if not text:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_result")
        return TransportResult(text=text, raw=event)


class ClaudeCodeTransport(BaseCliTransport):
    command_name = "claude"
    args = (
        "-p",
        "--output-format",
        "json",
        "--setting-sources",
        "project",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--tools",
        "",
    )

    def _parse_success(self, account: AccountRef, stdout: str) -> TransportResult:
        event = self._load_json(account, stdout)
        text = event.get("result", "")
        if not text:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="missing_result")
        return TransportResult(text=text, usage=event.get("usage", {}), raw=event)

    def _raise_for_failure(self, account: AccountRef, result: SubprocessResult) -> None:
        try:
            event = json.loads(result.stdout)
        except json.JSONDecodeError:
            super()._raise_for_failure(account, result)
            return

        if event.get("api_error_status") == 429 or event.get("subtype") == "rate_limit":
            raise RetryableProviderError(provider=account.provider, account_name=account.name, reason="rate_limit")
        if event.get("api_error_status") == 401:
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="auth_failed")
        if event.get("subtype") == "error_max_budget_usd":
            raise FatalProviderError(provider=account.provider, account_name=account.name, reason="budget_exceeded")
        raise FatalProviderError(provider=account.provider, account_name=account.name, reason="cli_failed")
