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

## Login Accounts

Use `login` for daily setup. DSPy starts the provider's native auth flow, assigns the next account name automatically, isolates OAuth accounts under `~/.dspy/accounts/homes/`, and skips duplicate registrations when the same authenticated account is detected again:

```bash
uv run dspy lm accounts login codex
uv run dspy lm accounts login claude
uv run dspy lm accounts login cursor
uv run dspy lm accounts login minimax
```

The default MiniMax command reads `MINIMAX_API_KEY_1` and uses `openai/MiniMax-M2.7`. Register another MiniMax token plan by pointing to a different loaded environment variable:

```bash
uv run dspy lm accounts login minimax --env-key MINIMAX_API_KEY_2
```

Lower `--priority` values are selected first. Accounts with the same priority rotate round-robin:

```bash
uv run dspy lm accounts login codex --priority 10
uv run dspy lm accounts login claude --priority 20
```

## Advanced Explicit Registration

Use `add` only when you intentionally want to choose the account name or credential home yourself:

```bash
uv run dspy lm accounts add codex --name codex-main --auth chatgpt --login
uv run dspy lm accounts add claude --name claude-max --auth oauth --model sonnet --login
uv run dspy lm accounts add cursor --name cursor-main --auth browser --model auto --login
uv run dspy lm accounts add minimax --name minimax-main --env-key MINIMAX_API_KEY_1 --model openai/MiniMax-M2.7
```

`add` stores only non-secret metadata. MiniMax raw API keys must stay in environment variables or ignored `.env` files.

## Verify Accounts

Inspect the registry without printing secret values:

```bash
uv run dspy lm accounts list
uv run dspy lm accounts status
uv run dspy lm accounts doctor
```

Run live smoke tests only when provider usage is acceptable:

```bash
uv run dspy lm accounts smoke --account codex-1 --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account claude-1 --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account cursor-1 --prompt "Reply with OK only." --yes-live
uv run dspy lm accounts smoke --account minimax-1 --prompt "Reply with OK only." --yes-live
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
uv run dspy lm accounts remove cursor-1
```
