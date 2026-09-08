"""Runtime settings, all of them from the environment.

Secrets never live in the repository. In production they arrive as GitHub
Actions secrets; locally they would come from the shell. Nothing reads a file
on disk for a credential, so there is no path by which one gets committed.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = REPO_ROOT / "state"
POLICY_FILE = REPO_ROOT / "policy.yml"

API_BASE = "https://fantasy-api.llt-services.com/api"
AUTH_BASE = "https://login.laliga.es/laligadspprob2c.onmicrosoft.com/oauth2/v2.0"

# The native app client is the only one that accepts a password grant.
CLIENT_ID = "af88bcff-1157-40a0-b579-030728aacf0b"
REDIRECT_URI = "authredirect://com.lfp.laligafantasy"
POLICY_PASSWORD_GRANT = "B2C_1A_ResourceOwnerv2"
POLICY_REFRESH = "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

# One request at a time, paced like a person. We are a guest on this API.
MIN_REQUEST_INTERVAL = float(os.environ.get("FANTASY_MIN_INTERVAL", "1.2"))


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    email: str = ""
    password: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            email=os.environ.get("FANTASY_EMAIL", ""),
            password=os.environ.get("FANTASY_PASSWORD", ""),
            telegram_token=os.environ.get("TELEGRAM_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        )

    @property
    def can_authenticate(self) -> bool:
        return bool(self.email and self.password)

    @property
    def can_notify(self) -> bool:
        return bool(self.telegram_token and self.telegram_chat_id)


__all__ = ["API_BASE", "POLICY_FILE", "REPO_ROOT", "STATE_DIR", "Settings"]
