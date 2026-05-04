from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dspy.clients.subscription_lm.account import AccountRef, assert_no_secret_values

REGISTRY_VERSION = 1


@dataclass
class AccountRegistry:
    path: Path

    @classmethod
    def from_env(cls) -> AccountRegistry:
        config_dir = os.environ.get("DSPY_ACCOUNT_CONFIG_DIR")
        base_dir = Path(config_dir).expanduser() if config_dir else Path.home() / ".dspy" / "accounts"
        return cls(path=base_dir / "accounts.json")

    def list(self) -> list[AccountRef]:
        return self._load_accounts()

    def get(self, name: str) -> AccountRef:
        for account in self._load_accounts():
            if account.name == name:
                return account
        raise KeyError(name)

    def upsert(self, account: AccountRef) -> None:
        assert_no_secret_values(account.to_dict())
        accounts = [existing for existing in self._load_accounts() if existing.name != account.name]
        accounts.append(account)
        self._save_accounts(accounts)

    def remove(self, name: str) -> bool:
        accounts = self._load_accounts()
        kept = [account for account in accounts if account.name != name]
        if len(kept) == len(accounts):
            return False
        self._save_accounts(kept)
        return True

    def _load_accounts(self) -> list[AccountRef]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text())
        account_dicts = data.get("accounts", [])
        return [AccountRef.from_dict(account_data) for account_data in account_dicts]

    def _save_accounts(self, accounts: list[AccountRef]) -> None:
        payload: dict[str, Any] = {
            "version": REGISTRY_VERSION,
            "accounts": [account.to_dict() for account in accounts],
        }
        assert_no_secret_values(payload)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        if os.name == "posix":
            self.path.chmod(0o600)
