from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from dspy.clients.subscription_lm.account import AccountRef

REDACTED = "[redacted]"
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]+"),
    re.compile(r"gh[pous]_[A-Za-z0-9_]+"),
    re.compile(r"github_pat_[A-Za-z0-9_]+"),
    re.compile(r"xox[bp]-[A-Za-z0-9\-]+"),
    re.compile(r"eyJ[A-Za-z0-9_\-.]+"),
    re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL),
)
SAFE_RAW_METADATA_KEYS = {"finish_reason", "model", "provider_version", "request_id", "version"}


def redact_text(
    text: str,
    *,
    account: AccountRef | None = None,
    command: Sequence[str] | None = None,
    extra_values: Sequence[str | None] = (),
) -> str:
    redacted = str(text)
    sensitive_values: list[str | None] = list(extra_values)
    if account is not None:
        sensitive_values.extend([account.env_key, account.home, account.command])
    if command is not None:
        sensitive_values.extend(command)

    for value in sensitive_values:
        if value:
            redacted = redacted.replace(str(value), REDACTED)
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def sanitize_provider_metadata(*, account: AccountRef, raw: dict[str, Any]) -> dict[str, str]:
    metadata = {"provider": account.provider, "account": account.name}
    for key, value in raw.items():
        if key not in SAFE_RAW_METADATA_KEYS or not isinstance(value, str | int | float | bool):
            continue
        rendered = str(value)
        if redact_text(rendered, account=account) == rendered:
            metadata[key] = rendered
    return metadata
