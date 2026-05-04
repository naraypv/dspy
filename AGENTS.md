# DSPy Fork Agent Instructions

## Project Role

This checkout is a fork of `stanfordnlp/dspy`. Treat upstream DSPy as the stable base and keep fork-specific work modular, reversible, and easy to rebase.

## Required First Steps

Before code changes:

1. Check `git status --short --branch`.
2. Check upstream state with `git ls-remote upstream HEAD` or the equivalent original repository URL.
3. Read `CONTRIBUTING.md` and the relevant checked-in DSPy docs for the surface being changed.
4. Inspect the current implementation and tests before choosing an architecture.

Never make structural decisions from memory. Verify against the live files and current documentation.

## Fork Compatibility Rules

- Do not edit upstream DSPy behavior unless the change is required and covered by tests.
- Keep fork-only providers, brokers, account pools, and CLI transports in narrowly scoped modules.
- Prefer extension points already present in DSPy, especially `dspy.BaseLM`, `dspy.LM`, `dspy.configure`, adapters, cache, callbacks, and history.
- Preserve OpenAI-shaped response compatibility for custom `BaseLM` implementations.
- Do not vendor secrets, local auth caches, session logs, agent plans, or active worktrees.
- Keep OpenAI/Codex, Claude Code, Cursor, and MiniMax integrations credential-isolated and configurable through environment variables or local ignored config.
- Provide CLI-based account onboarding and management for multi-account LM integrations; users should be able to add, list, check, and remove accounts without editing Python code.

## Contribution Rules

Follow DSPy's contribution guide:

- Discuss major features before upstream PRs.
- Use Python 3.10+ and the repository `uv` workflow.
- Run focused tests before broad tests.
- Use `ruff`/pre-commit-compatible style.
- Do not open PRs as an autonomous AI agent. The user must own any upstream contribution.

## Implementation Standards

- Python functions need type hints.
- Use standard library imports, then third-party imports, then local imports.
- Avoid global mutable runtime state unless it is existing DSPy infrastructure.
- Avoid hardcoded models, credentials, endpoints, paths, quotas, or account IDs.
- Use loggers instead of debug `print()`.
- Add tests for cache keys, history shape, retry/fallback behavior, auth selection, and subprocess output parsing.

## Local Working Files

Use `plan/` for local planning and documentation archives. Use `temp/` for scratch files. These directories are intentionally ignored by Git.
