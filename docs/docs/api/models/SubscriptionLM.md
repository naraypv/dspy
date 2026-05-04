# dspy.SubscriptionLM

`dspy.SubscriptionLM` is a fork-local LM facade for rotating across locally configured Codex, Claude Code, Cursor, and MiniMax accounts. It follows the `dspy.BaseLM` response contract, so it can be passed to `dspy.configure(lm=...)` like other DSPy LMs.

For a command-oriented setup guide, see [SubscriptionLM Usage](SubscriptionLMUsage.md).

Use it when the credentials live outside Python source code:

- Codex, Claude Code, and Cursor use their own CLI login stores.
- MiniMax uses environment variables that hold API keys.
- The DSPy registry stores only account metadata, command names, config directories, model names, and environment variable names.

## Account Login And Registration

Register accounts with the installed `dspy` command:

```bash
dspy lm accounts add codex --name codex-pro --codex-home ~/.codex-codex-pro --auth chatgpt --login
dspy lm accounts add claude --name claude-max --claude-config-dir ~/.claude-claude-max --auth oauth --login
dspy lm accounts add cursor --name cursor-pro --cursor-home ~/.cursor-cursor-pro --auth browser --model auto --login
dspy lm accounts add minimax --name minimax-main --env-key MINIMAX_API_KEY_1 --model openai/MiniMax-M2.7
```

`--codex-home` maps to `CODEX_HOME`, `--claude-config-dir` maps to `CLAUDE_CONFIG_DIR`, and `--cursor-home` is used as the subprocess `HOME` for Cursor CLI account isolation. For CLI-backed accounts, `--model` is forwarded to the provider command when present; for Cursor accounts that cannot use a named model in headless mode, use `--model auto`.

Claude Code calls run in a minimal non-bare print-mode configuration that still reads OAuth credentials but disables user/local settings, session persistence, auto MCP loading, slash commands, and tools. This keeps DSPy LM calls isolated from local hooks and project automation while preserving subscription authentication.

Inspect the registry without printing secret values:

```bash
dspy lm accounts list
dspy lm accounts status
dspy lm accounts doctor
dspy lm accounts remove cursor-pro
```

Run an explicit live smoke call only when you are ready to spend provider credits:

```bash
dspy lm accounts smoke --account codex-pro --prompt "Reply with OK only." --yes-live
```

By default, registry metadata is written under `~/.dspy/accounts/accounts.json`. Set `DSPY_ACCOUNT_CONFIG_DIR` to use a different directory.

## Using Registered Accounts

```python
import dspy

lm = dspy.SubscriptionLM.from_registry(
    model="subscription/research-pool",
    providers=["codex", "claude", "cursor", "minimax"],
    temperature=0.0,
)

dspy.configure(lm=lm)
```

`SubscriptionLM` rotates deterministically by account priority, uses round-robin within the same priority, skips accounts that hit retryable provider limits, and uses DSPy's request cache for repeated calls unless `cache=False` is set.

Customize retry and cooldown behavior with `RateLimitPolicy`:

```python
import dspy
from dspy.clients.subscription_lm import RateLimitPolicy

lm = dspy.SubscriptionLM.from_registry(
    model="subscription/research-pool",
    providers=["codex", "claude", "cursor", "minimax"],
    rate_limit_policy=RateLimitPolicy(
        max_attempts=4,
        cooldown_seconds=300,
        backoff_seconds=0.25,
    ),
)
```

Responses include sanitized `provider_metadata` with the provider and account name plus allow-listed provider fields such as request IDs or versions. Raw provider output, auth homes, environment variable names, and token-like values are not attached to the DSPy response.

## Direct Construction

For tests or explicit configuration, construct account references directly:

```python
import dspy
from dspy.clients.subscription_lm import AccountRef

lm = dspy.SubscriptionLM(
    model="subscription/codex-pool",
    accounts=[
        AccountRef(name="codex-a", provider="codex", home="~/.codex-a", priority=1),
        AccountRef(name="codex-b", provider="codex", home="~/.codex-b", priority=1),
    ],
)
```

## API Reference

<!-- START_API_REF -->
::: dspy.SubscriptionLM
    handler: python
    options:
        members:
            - __call__
            - copy
            - forward
            - from_registry
            - inspect_history
        show_source: true
        show_root_heading: true
        heading_level: 2
        docstring_style: google
        show_root_full_path: true
        show_object_full_path: false
        separate_signature: false
        inherited_members: true
<!-- END_API_REF -->
