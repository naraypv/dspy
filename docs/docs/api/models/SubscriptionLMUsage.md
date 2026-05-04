# SubscriptionLM Usage

This page is the operational quickstart for this fork's `dspy.SubscriptionLM` account registry. It shows how to invoke the local development environment, add provider accounts, verify them, and use the resulting pool from Python.

## Invoke The Local Environment

From the fork checkout, run the CLI through `uv`:

```bash
cd /media/naray/backup_np_2/github/dspy

uv run dspy lm accounts list
uv run dspy lm accounts doctor
```

For MiniMax, load the ignored `.env` file before running commands that need the API key:

```bash
set -a
source .env
set +a
```

By default, account metadata is stored in `~/.dspy/accounts/accounts.json`. Set `DSPY_ACCOUNT_CONFIG_DIR` only when you want an isolated registry for testing or validation:

```bash
export DSPY_ACCOUNT_CONFIG_DIR=/path/to/account-registry
```

## Add Accounts

Register the default Codex, Claude Code, Cursor, and MiniMax accounts:

```bash
uv run dspy lm accounts add codex \
  --name codex-main \
  --auth chatgpt \
  --login

uv run dspy lm accounts add claude \
  --name claude-max \
  --auth oauth \
  --model sonnet \
  --login

uv run dspy lm accounts add cursor \
  --name cursor-main \
  --auth browser \
  --model auto \
  --login

uv run dspy lm accounts add minimax \
  --name minimax-main \
  --env-key MINIMAX_API_KEY_1 \
  --model openai/MiniMax-M2.7
```

`--login` starts the provider's native OAuth login flow for Codex, Claude Code, or Cursor. MiniMax uses an environment variable name and does not store the raw API key in the DSPy registry.

## Add Multiple OAuth Accounts

Use separate provider home directories to isolate multiple OAuth accounts:

```bash
uv run dspy lm accounts add codex \
  --name codex-2 \
  --codex-home ~/.codex-dspy-2 \
  --auth chatgpt \
  --login

uv run dspy lm accounts add claude \
  --name claude-2 \
  --claude-config-dir ~/.claude-dspy-2 \
  --auth oauth \
  --model sonnet \
  --login

uv run dspy lm accounts add cursor \
  --name cursor-2 \
  --cursor-home ~/.cursor-dspy-2 \
  --auth browser \
  --model auto \
  --login
```

The CLI creates these provider home directories automatically with private permissions before invoking the provider login command.

Lower `--priority` values are selected first. Accounts with the same priority rotate round-robin:

```bash
uv run dspy lm accounts add codex --name codex-primary --priority 10 --auth chatgpt --login
uv run dspy lm accounts add codex --name codex-secondary --priority 20 --auth chatgpt --login
```

## Verify Accounts

Inspect the registry without printing secret values:

```bash
uv run dspy lm accounts list
uv run dspy lm accounts status
uv run dspy lm accounts doctor
```

Run live smoke tests only when provider usage is acceptable:

```bash
uv run dspy lm accounts smoke --account codex-main --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account claude-max --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account cursor-main --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account minimax-main --prompt "Reply with OK only." --yes-live
```

The smoke command intentionally refuses to call a live provider unless `--yes-live` is present.

## Use From Python

Load the registered pool and configure DSPy:

```python
import dspy

lm = dspy.SubscriptionLM.from_registry(
    model="subscription/research-pool",
    providers=["codex", "claude", "cursor", "minimax"],
    temperature=0.0,
)

dspy.configure(lm=lm)
```

`SubscriptionLM` rotates accounts by priority, round-robins accounts at the same priority, skips retryable rate-limited accounts during cooldown, and uses DSPy's normal request cache unless `cache=False` is set.

To tune retry behavior:

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

## Remove Accounts

```bash
uv run dspy lm accounts remove cursor-main
```
