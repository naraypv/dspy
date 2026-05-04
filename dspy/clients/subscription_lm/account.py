from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ALLOWED_PROVIDERS = {"claude", "codex", "cursor", "minimax"}
SECRET_PREFIXES = ("sk-", "ghp_", "gho_", "ghu_", "ghs_", "github_pat_", "xoxb-", "xoxp-", "eyJ")
SECRET_FRAGMENTS = ("-----BEGIN ",)


class SecretValueError(ValueError):
    """Raised when account metadata appears to contain a raw credential value."""


@dataclass(frozen=True)
class AccountRef:
    name: str
    provider: str
    model: str | None = None
    auth: str | None = None
    env_key: str | None = None
    command: str | None = None
    home: str | None = None
    priority: int = 100
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Account name is required.")
        if self.provider not in ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported subscription LM provider: {self.provider}")
        if self.priority < 0:
            raise ValueError("Account priority must be non-negative.")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AccountRef:
        fields = {
            "name",
            "provider",
            "model",
            "auth",
            "env_key",
            "command",
            "home",
            "priority",
            "metadata",
        }
        return cls(**{key: value for key, value in data.items() if key in fields})

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "provider": self.provider,
            "priority": self.priority,
        }
        optional_values = {
            "model": self.model,
            "auth": self.auth,
            "env_key": self.env_key,
            "command": self.command,
            "home": self.home,
            "metadata": self.metadata,
        }
        for key, value in optional_values.items():
            if value not in (None, {}, ""):
                data[key] = value
        return data

    def safe_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def provider_command(self) -> str | None:
        if self.command:
            return self.command
        return {"claude": "claude", "codex": "codex", "cursor": "agent"}.get(self.provider)


def assert_no_secret_values(value: Any) -> None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(SECRET_PREFIXES) or any(fragment in stripped for fragment in SECRET_FRAGMENTS):
            raise SecretValueError("Account metadata must not contain raw secret values.")
    elif isinstance(value, dict):
        for nested_value in value.values():
            assert_no_secret_values(nested_value)
    elif isinstance(value, list | tuple):
        for nested_value in value:
            assert_no_secret_values(nested_value)
