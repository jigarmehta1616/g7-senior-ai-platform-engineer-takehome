"""Shared fixtures. The API runs in-process against the mock upstreams (also in-process,
via httpx.ASGITransport) with a frozen clock at the fixture anchor, so every test is
deterministic and needs no network or open ports."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from mock_upstreams.app import DEFAULT_RECEIVER_SECRET, create_mock_app
from support_platform.api.app import create_app
from support_platform.config import Settings

ANCHOR = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[1]
PERSONA_GRANT = "urn:dev:grant-type:persona"
TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    base = dict(env="test", db_path=str(tmp_path / "platform.db"), upstream_base_url="http://upstream",
                upstream_timeout_s=0.5, upstream_deadline_s=2.0, retry_base_delay_s=0.0, retry_max_delay_s=0.0,
                breaker_failure_threshold=3, breaker_reset_timeout_s=60.0,
                demo_receiver_secret=DEFAULT_RECEIVER_SECRET, log_level="WARNING")
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def mock_app() -> FastAPI:
    return create_mock_app(rebase_time=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def app(settings: Settings, mock_app: FastAPI) -> Iterator[FastAPI]:
    application = create_app(settings, clock=lambda: ANCHOR, upstream_transport=httpx.ASGITransport(app=mock_app),
                             run_background=False)
    yield application
    application.state.container.db.close()   # idempotent; also covers tests that never start the app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


def persona_token(client: TestClient, persona: str) -> str:
    r = client.post("/dev/oauth/token", data={"grant_type": PERSONA_GRANT, "persona": persona})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def delegated_token(client: TestClient, persona: str, actor: str = "support-copilot") -> str:
    r = client.post("/dev/oauth/token", data={"grant_type": TOKEN_EXCHANGE,
                                              "subject_token": persona_token(client, persona),
                                              "actor_client": actor})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.fixture
def auth(client: TestClient) -> Callable[[str], dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}

    def _headers(persona: str) -> dict[str, str]:
        if persona not in cache:
            cache[persona] = {"Authorization": f"Bearer {persona_token(client, persona)}"}
        return cache[persona]

    return _headers


def set_fault(mock_app: FastAPI, target: str, mode: str, fail_next: int = 0) -> None:
    mock_app.state.mock.faults[target] = {"mode": mode, "latency_ms": 0, "fail_next": fail_next}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
