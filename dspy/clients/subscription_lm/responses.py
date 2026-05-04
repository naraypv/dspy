from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def build_chat_response(
    *,
    model: str,
    text: str,
    usage: dict[str, Any] | None = None,
    finish_reason: str = "stop",
    provider_metadata: dict[str, Any] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(role="assistant", content=text),
            )
        ],
        model=model,
        provider_metadata=provider_metadata or {},
        usage=usage or {},
    )
