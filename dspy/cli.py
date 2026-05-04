from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dspy.clients.subscription_lm import AccountRef, AccountRegistry, SubscriptionLM
from dspy.clients.subscription_lm.account_login import (
    account_home,
    discard_scratch_login_home,
    find_existing_cli_identity,
    find_existing_minimax_identity,
    identity_from_secret,
    identity_metadata,
    move_login_home,
    next_account_name,
    probe_provider_identity,
    provider_env,
    scratch_login_home,
)

DEFAULT_MINIMAX_ENV_KEY = "MINIMAX_API_KEY_1"
DEFAULT_MINIMAX_MODEL = "openai/MiniMax-M2.7"


@dataclass
class AccountStatus:
    name: str
    provider: str
    env_key: str | None
    env_present: bool | None
    command: str | None
    command_present: bool | None
    home: str | None
    home_exists: bool | None
    ok: bool


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


def run_provider_login(account: AccountRef) -> str:
    command = _login_command(account)
    env = provider_env(account)
    subprocess.run(command, env=env, check=True)
    return f"{account.provider} login completed"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dspy")
    subparsers = parser.add_subparsers(dest="command")
    lm_parser = subparsers.add_parser("lm")
    lm_subparsers = lm_parser.add_subparsers(dest="lm_command")
    accounts_parser = lm_subparsers.add_parser("accounts")
    accounts_subparsers = accounts_parser.add_subparsers(dest="accounts_command")

    add_parser = accounts_subparsers.add_parser("add")
    add_subparsers = add_parser.add_subparsers(dest="provider", required=True)
    _add_provider_parser(add_subparsers, "codex", _handle_add_codex)
    _add_provider_parser(add_subparsers, "claude", _handle_add_claude)
    _add_provider_parser(add_subparsers, "cursor", _handle_add_cursor)
    minimax_parser = add_subparsers.add_parser("minimax")
    minimax_parser.add_argument("--name", required=True)
    minimax_parser.add_argument("--env-key", required=True)
    minimax_parser.add_argument("--model", required=True)
    minimax_parser.add_argument("--priority", type=int, default=100)
    minimax_parser.set_defaults(handler=_handle_add_minimax)

    login_parser = accounts_subparsers.add_parser("login")
    login_subparsers = login_parser.add_subparsers(dest="provider", required=True)
    _add_login_provider_parser(login_subparsers, "codex", _handle_login_codex)
    _add_login_provider_parser(login_subparsers, "claude", _handle_login_claude)
    _add_login_provider_parser(login_subparsers, "cursor", _handle_login_cursor)
    minimax_login_parser = login_subparsers.add_parser("minimax")
    minimax_login_parser.add_argument("--env-key", default=DEFAULT_MINIMAX_ENV_KEY)
    minimax_login_parser.add_argument("--model", default=DEFAULT_MINIMAX_MODEL)
    minimax_login_parser.add_argument("--priority", type=int, default=100)
    minimax_login_parser.set_defaults(handler=_handle_login_minimax)

    list_parser = accounts_subparsers.add_parser("list")
    list_parser.add_argument("--format", choices=["text", "json"], default="text")
    list_parser.set_defaults(handler=_handle_list)

    status_parser = accounts_subparsers.add_parser("status")
    status_parser.add_argument("--format", choices=["text", "json"], default="text")
    status_parser.set_defaults(handler=_handle_status)

    remove_parser = accounts_subparsers.add_parser("remove")
    remove_parser.add_argument("name")
    remove_parser.set_defaults(handler=_handle_remove)

    doctor_parser = accounts_subparsers.add_parser("doctor")
    doctor_parser.set_defaults(handler=_handle_doctor)

    smoke_parser = accounts_subparsers.add_parser("smoke")
    smoke_parser.add_argument("--provider", action="append")
    smoke_parser.add_argument("--account", action="append")
    smoke_parser.add_argument("--model", default="subscription/live-smoke")
    smoke_parser.add_argument("--prompt", default="Reply with OK only.")
    smoke_parser.add_argument("--format", choices=["text", "json"], default="text")
    smoke_parser.add_argument("--yes-live", action="store_true")
    smoke_parser.set_defaults(handler=_handle_smoke)
    return parser


def _add_provider_parser(subparsers: Any, provider: str, handler: Callable[[argparse.Namespace], int]) -> None:
    provider_parser = subparsers.add_parser(provider)
    provider_parser.add_argument("--name", required=True)
    provider_parser.add_argument("--model")
    provider_parser.add_argument("--auth", default="oauth" if provider == "claude" else "browser")
    provider_parser.add_argument(
        "--command", default={"claude": "claude", "codex": "codex", "cursor": "agent"}[provider]
    )
    provider_parser.add_argument("--priority", type=int, default=100)
    provider_parser.add_argument("--login", action="store_true")
    if provider == "codex":
        provider_parser.add_argument("--codex-home", dest="home")
        provider_parser.set_defaults(auth="chatgpt")
    elif provider == "claude":
        provider_parser.add_argument("--claude-config-dir", dest="home")
    elif provider == "cursor":
        provider_parser.add_argument("--cursor-home", dest="home")
    provider_parser.set_defaults(handler=handler)


def _add_login_provider_parser(subparsers: Any, provider: str, handler: Callable[[argparse.Namespace], int]) -> None:
    provider_parser = subparsers.add_parser(provider)
    provider_parser.add_argument("--model", default={"codex": None, "claude": "sonnet", "cursor": "auto"}[provider])
    provider_parser.add_argument(
        "--auth", default={"codex": "chatgpt", "claude": "oauth", "cursor": "browser"}[provider]
    )
    provider_parser.add_argument(
        "--command", default={"claude": "claude", "codex": "codex", "cursor": "agent"}[provider]
    )
    provider_parser.add_argument("--priority", type=int, default=100)
    provider_parser.set_defaults(handler=handler)


def _handle_add_codex(args: argparse.Namespace) -> int:
    return _add_cli_account(args, provider="codex")


def _handle_add_claude(args: argparse.Namespace) -> int:
    return _add_cli_account(args, provider="claude")


def _handle_add_cursor(args: argparse.Namespace) -> int:
    return _add_cli_account(args, provider="cursor")


def _handle_login_codex(args: argparse.Namespace) -> int:
    return _login_cli_account(args, provider="codex")


def _handle_login_claude(args: argparse.Namespace) -> int:
    return _login_cli_account(args, provider="claude")


def _handle_login_cursor(args: argparse.Namespace) -> int:
    return _login_cli_account(args, provider="cursor")


def _handle_login_minimax(args: argparse.Namespace) -> int:
    registry = AccountRegistry.from_env()
    credential = os.environ.get(args.env_key)
    if credential is None:
        print(f"Missing MiniMax API key environment variable {args.env_key}.")
        return 1

    identity = identity_from_secret("minimax", credential, label=args.env_key)
    existing = find_existing_minimax_identity(registry.list(), identity=identity)
    if existing is not None:
        print(f"MiniMax account {args.env_key} is already registered as {existing.name}; no new account added.")
        return 0

    name = next_account_name("minimax", registry.list())
    account = AccountRef(
        name=name,
        provider="minimax",
        model=args.model,
        auth="token_plan_api_key",
        env_key=args.env_key,
        priority=args.priority,
        metadata=identity_metadata(identity, source="env_key"),
    )
    registry.upsert(account)
    print(f"Added MiniMax account {account.name} using env var {account.env_key}.")
    return 0


def _handle_add_minimax(args: argparse.Namespace) -> int:
    account = AccountRef(
        name=args.name,
        provider="minimax",
        model=args.model,
        auth="token_plan_api_key",
        env_key=args.env_key,
        priority=args.priority,
    )
    AccountRegistry.from_env().upsert(account)
    print(f"Added MiniMax account {account.name} using env var {account.env_key}.")
    return 0


def _add_cli_account(args: argparse.Namespace, *, provider: str) -> int:
    account = AccountRef(
        name=args.name,
        provider=provider,
        model=args.model,
        auth=args.auth,
        command=args.command,
        home=args.home,
        priority=args.priority,
    )
    if args.login:
        print(run_provider_login(account))
    AccountRegistry.from_env().upsert(account)
    print(f"Added {provider} account {account.name}.")
    return 0


def _login_cli_account(args: argparse.Namespace, *, provider: str) -> int:
    registry = AccountRegistry.from_env()
    scratch_home = scratch_login_home(registry.path, provider)
    scratch_account = AccountRef(
        name=f"{provider}-login",
        provider=provider,
        model=args.model,
        auth=args.auth,
        command=args.command,
        home=str(scratch_home),
        priority=args.priority,
    )
    print(run_provider_login(scratch_account))

    identity = probe_provider_identity(scratch_account)
    accounts = registry.list()
    existing = find_existing_cli_identity(
        accounts,
        provider=provider,
        identity=identity,
        identity_probe=probe_provider_identity,
    )
    if existing is not None:
        discard_scratch_login_home(scratch_home)
        print(f"{provider} account {identity.label} is already registered as {existing.name}; no new account added.")
        return 0

    name = _next_available_account_name(registry, provider)
    final_home = account_home(registry.path, provider, name)
    move_login_home(scratch_home, final_home)
    account = AccountRef(
        name=name,
        provider=provider,
        model=args.model,
        auth=args.auth,
        command=args.command,
        home=str(final_home),
        priority=args.priority,
        metadata=identity_metadata(identity, source="oauth_cli_login"),
    )
    registry.upsert(account)
    print(f"Added {provider} account {account.name} ({identity.label}).")
    return 0


def _next_available_account_name(registry: AccountRegistry, provider: str) -> str:
    accounts = registry.list()
    name = next_account_name(provider, accounts)
    while account_home(registry.path, provider, name).exists():
        accounts.append(AccountRef(name=name, provider=provider))
        name = next_account_name(provider, accounts)
    return name


def _handle_list(args: argparse.Namespace) -> int:
    accounts = [account.safe_dict() for account in AccountRegistry.from_env().list()]
    if args.format == "json":
        print(json.dumps({"accounts": accounts}, indent=2, sort_keys=True))
    else:
        for account in accounts:
            print(f"{account['name']}\t{account['provider']}\t{account.get('model', '')}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    statuses = [_account_status(account) for account in AccountRegistry.from_env().list()]
    if args.format == "json":
        print(json.dumps({"accounts": [asdict(status) for status in statuses]}, indent=2, sort_keys=True))
    else:
        for status in statuses:
            label = "ok" if status.ok else "needs-attention"
            print(f"{status.name}\t{status.provider}\t{label}")
    return 0


def _handle_remove(args: argparse.Namespace) -> int:
    removed = AccountRegistry.from_env().remove(args.name)
    if removed:
        print(f"Account {args.name} removed.")
        return 0
    print(f"Account {args.name} was not found.")
    return 1


def _handle_doctor(args: argparse.Namespace) -> int:
    del args
    statuses = [_account_status(account) for account in AccountRegistry.from_env().list()]
    for status in statuses:
        label = "ok" if status.ok else "needs-attention"
        details = []
        if status.env_key and not status.env_present:
            details.append(f"missing env {status.env_key}")
        if status.command and not status.command_present:
            details.append(f"missing command {status.command}")
        if status.home and not status.home_exists:
            details.append(f"missing home {status.home}")
        suffix = f" ({', '.join(details)})" if details else ""
        print(f"{status.name}\t{status.provider}\t{label}{suffix}")
    return 0 if all(status.ok for status in statuses) else 1


def _handle_smoke(args: argparse.Namespace) -> int:
    if not args.yes_live:
        print("Refusing to run a live provider call without --yes-live.")
        return 2
    lm = SubscriptionLM.from_registry(
        model=args.model,
        providers=args.provider,
        account_names=args.account,
        cache=False,
    )
    outputs = lm(args.prompt, cache=False)
    if args.format == "json":
        print(json.dumps({"model": args.model, "outputs": outputs}, indent=2, sort_keys=True))
    else:
        for output in outputs:
            print(output)
    return 0


def _account_status(account: AccountRef) -> AccountStatus:
    command = account.provider_command()
    env_present = None if not account.env_key else account.env_key in os.environ
    command_present = None if not command else shutil.which(command) is not None
    home_exists = None if not account.home else Path(account.home).expanduser().exists()
    checks = [
        True if env_present is None else env_present,
        True if command_present is None or account.provider == "minimax" else command_present,
        True if home_exists is None else home_exists,
    ]
    return AccountStatus(
        name=account.name,
        provider=account.provider,
        env_key=account.env_key,
        env_present=env_present,
        command=command,
        command_present=command_present,
        home=account.home,
        home_exists=home_exists,
        ok=all(checks),
    )


def _login_command(account: AccountRef) -> list[str]:
    command = account.provider_command()
    if command is None:
        raise ValueError(f"Provider {account.provider} does not have an interactive login command.")
    if account.provider == "codex":
        return [command, "login", "--device-auth"] if account.auth == "device" else [command, "login"]
    if account.provider == "claude":
        return [command, "setup-token"] if account.auth == "setup-token" else [command, "auth", "login"]
    if account.provider == "cursor":
        return [command, "login"]
    raise ValueError(f"Provider {account.provider} does not have an interactive login command.")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
