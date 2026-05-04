from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dspy.clients.subscription_lm.account import AccountRef

IDENTITY_FINGERPRINT_KEY = "identity_fingerprint"
IDENTITY_LABEL_KEY = "identity_label"
IDENTITY_PROBE_TIMEOUT_SECONDS = 30
LOGIN_SOURCE_KEY = "login_source"


@dataclass(frozen=True)
class AccountIdentity:
    fingerprint: str
    label: str


def provider_env(account: AccountRef) -> dict[str, str]:
    env = {**os.environ}
    home = str(Path(account.home).expanduser()) if account.home else None
    if home:
        _ensure_account_home(Path(home))
    if home and account.provider == "codex":
        env["CODEX_HOME"] = home
    if home and account.provider == "claude":
        env["CLAUDE_CONFIG_DIR"] = home
    if home and account.provider == "cursor":
        env["HOME"] = home
    return env


def probe_provider_identity(account: AccountRef) -> AccountIdentity:
    if account.provider == "codex":
        codex_identity = codex_identity_from_home(account.home)
        if codex_identity is not None:
            return codex_identity
        raise ValueError("Could not identify Codex account from auth.json.")
    command = _identity_command(account)
    env = provider_env(account)
    try:
        result = subprocess.run(
            command,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=IDENTITY_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"Timed out while checking {account.provider} account identity.") from exc
    status_text = "\n".join(text for text in (result.stdout, result.stderr) if text).strip()
    if result.returncode != 0:
        raise ValueError(f"Could not check {account.provider} account identity: {status_text}")
    return identity_from_status_text(account.provider, status_text)


def identity_from_status_text(provider: str, status_text: str) -> AccountIdentity:
    normalized = _normalize_text(status_text)
    if not normalized:
        raise ValueError(f"{provider} did not return account identity details.")
    return AccountIdentity(
        fingerprint=_stable_hash(provider, normalized),
        label=_identity_label_from_text(normalized),
    )


def identity_from_secret(provider: str, secret_value: str, *, label: str) -> AccountIdentity:
    stripped = secret_value.strip()
    if not stripped:
        raise ValueError(f"{provider} credential value is empty.")
    return AccountIdentity(fingerprint=_stable_hash(provider, stripped), label=label)


def codex_identity_from_home(home: str | None) -> AccountIdentity | None:
    auth_path = _codex_auth_path(home)
    if not auth_path.exists():
        return None

    data = json.loads(auth_path.read_text())
    tokens = data.get("tokens", {})
    if not isinstance(tokens, dict):
        return None

    token = tokens.get("id_token")
    if not isinstance(token, str) or "." not in token:
        account_id = _first_string(tokens.get("account_id"))
        if account_id:
            return AccountIdentity(fingerprint=_stable_hash("codex", account_id), label="codex ChatGPT account")
        return None

    claims = _decode_jwt_payload(token)
    label = _first_string(claims.get("email"), claims.get("name")) or "codex ChatGPT account"
    fingerprint_material = _codex_fingerprint_material(claims)
    if not fingerprint_material:
        return None
    return AccountIdentity(fingerprint=_stable_hash("codex", fingerprint_material), label=label)


def next_account_name(provider: str, accounts: list[AccountRef]) -> str:
    index = 1
    existing_names = {account.name for account in accounts}
    while f"{provider}-{index}" in existing_names:
        index += 1
    return f"{provider}-{index}"


def account_home(registry_path: Path, provider: str, name: str) -> Path:
    return registry_path.parent / "homes" / provider / name


def scratch_login_home(registry_path: Path, provider: str) -> Path:
    return registry_path.parent / "homes" / provider / "_login"


def find_existing_identity(
    accounts: list[AccountRef],
    *,
    provider: str,
    identity: AccountIdentity,
) -> AccountRef | None:
    for account in accounts:
        if account.provider == provider and account.metadata.get(IDENTITY_FINGERPRINT_KEY) == identity.fingerprint:
            return account
    return None


def find_existing_cli_identity(
    accounts: list[AccountRef],
    *,
    provider: str,
    identity: AccountIdentity,
    identity_probe: Callable[[AccountRef], AccountIdentity],
) -> AccountRef | None:
    existing = find_existing_identity(accounts, provider=provider, identity=identity)
    if existing is not None:
        return existing
    for account in accounts:
        if account.provider != provider or account.metadata.get(IDENTITY_FINGERPRINT_KEY):
            continue
        if account.home and not Path(account.home).expanduser().exists():
            continue
        try:
            existing_identity = identity_probe(account)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        if existing_identity.fingerprint == identity.fingerprint:
            return account
    return None


def find_existing_minimax_identity(
    accounts: list[AccountRef],
    *,
    identity: AccountIdentity,
) -> AccountRef | None:
    existing = find_existing_identity(accounts, provider="minimax", identity=identity)
    if existing is not None:
        return existing
    for account in accounts:
        if account.provider != "minimax" or not account.env_key:
            continue
        credential = os.environ.get(account.env_key)
        if credential is None:
            continue
        try:
            existing_identity = identity_from_secret("minimax", credential, label=account.env_key)
        except ValueError:
            continue
        if existing_identity.fingerprint == identity.fingerprint:
            return account
    return None


def identity_metadata(identity: AccountIdentity, *, source: str) -> dict[str, str]:
    return {
        IDENTITY_FINGERPRINT_KEY: identity.fingerprint,
        IDENTITY_LABEL_KEY: identity.label,
        LOGIN_SOURCE_KEY: source,
    }


def move_login_home(scratch_home: Path, final_home: Path) -> None:
    if scratch_home == final_home:
        return
    final_home.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if final_home.exists():
        raise FileExistsError(f"Account home already exists: {final_home}")
    if scratch_home.exists():
        shutil.move(str(scratch_home), str(final_home))
    else:
        final_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if final_home.exists():
        final_home.chmod(0o700)


def discard_scratch_login_home(scratch_home: Path) -> None:
    if scratch_home.name != "_login":
        raise ValueError(f"Refusing to discard non-scratch account home: {scratch_home}")
    if scratch_home.exists():
        shutil.rmtree(scratch_home)


def _ensure_account_home(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix":
        path.chmod(0o700)


def _identity_command(account: AccountRef) -> list[str]:
    command = account.provider_command()
    if command is None:
        raise ValueError(f"Provider {account.provider} does not have an identity check command.")
    if account.provider == "codex":
        return [command, "login", "status"]
    if account.provider == "claude":
        return [command, "auth", "status", "--text"]
    if account.provider == "cursor":
        return [command, "status"]
    raise ValueError(f"Provider {account.provider} does not have an identity check command.")


def _codex_auth_path(home: str | None) -> Path:
    base = Path(home).expanduser() if home else Path.home() / ".codex"
    return base / "auth.json"


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    padding = "=" * (-len(payload) % 4)
    decoded = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
    loaded = json.loads(decoded)
    return loaded if isinstance(loaded, dict) else {}


def _codex_fingerprint_material(claims: dict[str, Any]) -> str | None:
    auth_claims = claims.get("https://api.openai.com/auth")
    if not isinstance(auth_claims, dict):
        auth_claims = {}
    return _first_string(
        auth_claims.get("chatgpt_account_id"),
        auth_claims.get("chatgpt_user_id"),
        auth_claims.get("user_id"),
        claims.get("sub"),
        claims.get("email"),
    )


def _first_string(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _identity_label_from_text(text: str) -> str:
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)
    if email_match:
        return email_match.group(0)
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return "authenticated account"


def _normalize_text(text: str) -> str:
    return "\n".join(line.strip() for line in text.strip().splitlines() if line.strip())


def _stable_hash(provider: str, value: str) -> str:
    digest = hashlib.sha256(f"{provider}\0{value}".encode()).hexdigest()
    return f"sha256:{digest}"
