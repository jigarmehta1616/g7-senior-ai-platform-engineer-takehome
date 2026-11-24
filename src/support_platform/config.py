"""Runtime configuration. Twelve-factor: everything comes from the environment, with
safe local defaults. Secrets defaults are *local-only* and the app refuses to start
with them outside ``ENV=local``/``ENV=test``."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

_LOCAL_JWT_SECRET = "local-dev-only-jwt-secret-change-me-0123456789"  # noqa: S105
_LOCAL_CURSOR_SECRET = "local-dev-only-cursor-secret-0123456789"  # noqa: S105
_LOCAL_RECEIVER_SECRET = "whsec_ZGVtby1yZWNlaXZlci1zZWNyZXQtZm9yLWxvY2FsLW9ubHk="  # noqa: S105


def utc_now() -> datetime:
    return datetime.now(UTC)


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    env: str = "local"
    db_path: str = "var/platform.db"
    upstream_base_url: str = "http://127.0.0.1:8081"

    jwt_secret: str = _LOCAL_JWT_SECRET
    jwt_issuer: str = "https://idp.local.example"
    jwt_audience: str = "support-platform-api"
    cursor_secret: str = _LOCAL_CURSOR_SECRET

    upstream_timeout_s: float = 2.0
    upstream_deadline_s: float = 5.0
    retry_attempts: int = 3
    retry_base_delay_s: float = 0.1
    retry_max_delay_s: float = 1.0
    breaker_failure_threshold: int = 5
    breaker_reset_timeout_s: float = 30.0

    rate_limit_user_per_min: int = 120
    rate_limit_agent_per_min: int = 30
    idempotency_ttl_hours: int = 24
    max_body_bytes: int = 64 * 1024

    webhook_max_attempts: int = 6
    webhook_poll_interval_s: float = 1.0
    seed_demo_webhook: bool = True
    demo_receiver_secret: str = _LOCAL_RECEIVER_SECRET

    enable_console: bool = True
    enable_dev_idp: bool = True
    log_level: str = "INFO"

    @property
    def is_local(self) -> bool:
        return self.env in ("local", "test")

    @classmethod
    def from_env(cls) -> Settings:
        env = _env("ENV", "local")
        s = cls(
            env=env,
            db_path=_env("DB_PATH", "var/platform.db"),
            upstream_base_url=_env("UPSTREAM_BASE_URL", "http://127.0.0.1:8081"),
            jwt_secret=_env("JWT_SECRET", _LOCAL_JWT_SECRET),
            jwt_issuer=_env("JWT_ISSUER", "https://idp.local.example"),
            jwt_audience=_env("JWT_AUDIENCE", "support-platform-api"),
            cursor_secret=_env("CURSOR_SECRET", _LOCAL_CURSOR_SECRET),
            upstream_timeout_s=float(_env("UPSTREAM_TIMEOUT_S", "2.0")),
            rate_limit_user_per_min=int(_env("RATE_LIMIT_USER_PER_MIN", "120")),
            rate_limit_agent_per_min=int(_env("RATE_LIMIT_AGENT_PER_MIN", "30")),
            seed_demo_webhook=_env("SEED_DEMO_WEBHOOK", "true") == "true",
            demo_receiver_secret=_env("RECEIVER_WEBHOOK_SECRET", _LOCAL_RECEIVER_SECRET),
            enable_console=_env("ENABLE_CONSOLE", "true" if env == "local" else "false") == "true",
            enable_dev_idp=_env("ENABLE_DEV_IDP", "true" if env == "local" else "false") == "true",
            log_level=_env("LOG_LEVEL", "INFO"),
        )
        s.validate()
        return s

    def validate(self) -> None:
        if self.is_local:
            return
        if self.jwt_secret == _LOCAL_JWT_SECRET or self.cursor_secret == _LOCAL_CURSOR_SECRET:
            raise RuntimeError("Refusing to start: local-only secrets configured outside ENV=local")
        if self.enable_dev_idp:
            raise RuntimeError("Refusing to start: the dev IdP must never be enabled outside ENV=local")
