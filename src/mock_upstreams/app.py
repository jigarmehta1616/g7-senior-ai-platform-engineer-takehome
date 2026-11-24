"""Mock upstream systems: case system (Salesforce-like REST), entitlement system
(NetSuite-like REST + CSV export + XML change feed) and usage warehouse
(Snowflake-like SQL statements API).

Also exposes:
  * ``/_admin/faults``   - fault injection (error / timeout / slow / flaky) per upstream
  * ``/_receiver/webhooks`` - a sample webhook consumer that verifies signatures

This process is deliberately *not* well-behaved: inconsistent field casing, string-typed
SQL results and injectable failures are what the platform's adapters must absorb.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import io
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from support_platform.security.webhook_signing import WebhookVerificationError, verify_webhook

DATA_DIR = Path(__file__).parent / "data"
FIXTURE_ANCHOR = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
DEFAULT_RECEIVER_SECRET = "whsec_ZGVtby1yZWNlaXZlci1zZWNyZXQtZm9yLWxvY2FsLW9ubHk="  # noqa: S105 - local demo


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FaultConfig(BaseModel):
    target: str = Field(pattern="^(cases|entitlements|usage)$")
    mode: str = Field(default="ok", pattern="^(ok|error|timeout|slow|flaky)$")
    latency_ms: int = Field(default=0, ge=0, le=30000)
    fail_next: int = Field(default=0, ge=0, le=100, description="flaky: fail the next N calls then recover")


class CommentIn(BaseModel):
    author: str
    body: str
    visibility: str = "internal"

class CasePatch(BaseModel):
    escalationLevel: int | None = None
    escalatedTo: str | None = None
    escalationReason: str | None = None
    Status: str | None = None

class Statement(BaseModel):
    statement: str = Field(max_length=2000)
    bindings: dict[str, dict[str, Any]] = Field(default_factory=dict)


class MockState:
    def __init__(self, *, rebase_time: bool, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        self.shift = (now - FIXTURE_ANCHOR) if rebase_time else timedelta(0)
        self.day_shift = timedelta(days=self.shift.days)
        self.faults: dict[str, dict[str, Any]] = {
            t: {"mode": "ok", "latency_ms": 0, "fail_next": 0} for t in ("cases", "entitlements", "usage")
        }
        self.calls: dict[str, int] = {"cases": 0, "entitlements": 0, "usage": 0}
        self.cases: dict[str, dict[str, Any]] = {}
        self.comment_idempotency: dict[str, dict[str, Any]] = {}
        self.received_webhooks: list[dict[str, Any]] = []
        self._comment_seq = 100
        self._load_cases()
        self.accounts = self._load_accounts()
        self.usage_db = self._load_usage()

    # ---- fixtures -------------------------------------------------------------------
    def _shift_ts(self, value: str) -> str:
        return _iso(_parse_iso(value) + self.shift)

    def _load_cases(self) -> None:
        raw = json.loads((DATA_DIR / "cases.json").read_text(encoding="utf-8"))
        for rec in raw["records"]:
            rec = copy.deepcopy(rec)
            rec["openedAt"] = self._shift_ts(rec["openedAt"])
            for c in rec.get("Comments", []):
                c["at"] = self._shift_ts(c["at"])
            rec["updatedAt"] = rec["Comments"][-1]["at"] if rec.get("Comments") else rec["openedAt"]
            rec.setdefault("escalationLevel", 0)
            self.cases[rec["id"]] = rec

    def csv_rows(self) -> list[dict[str, str]]:
        text = (DATA_DIR / "entitlements.csv").read_text(encoding="utf-8")
        rows = list(csv.DictReader(io.StringIO(text)))
        for r in rows:
            r["contract_end"] = (date.fromisoformat(r["contract_end"]) + self.day_shift).isoformat()
        return rows

    def xml_feed(self) -> str:
        tree = ET.parse(DATA_DIR / "entitlements_feed.xml")  # noqa: S314 - trusted local fixture
        for acc in tree.getroot().iter("account"):
            ren = acc.find("renewal")
            if ren is not None and ren.text:
                ren.text = (date.fromisoformat(ren.text) + self.day_shift).isoformat()
        return ET.tostring(tree.getroot(), encoding="unicode")

    def _load_accounts(self) -> dict[str, dict[str, Any]]:
        accounts = {r["account_id"]: dict(r) for r in self.csv_rows()}
        root = ET.fromstring(self.xml_feed())  # noqa: S314 - trusted
        for acc in root.iter("account"):
            target = accounts.get(acc.get("id", ""))
            if not target:
                continue
            tier, ren = acc.findtext("tier"), acc.findtext("renewal")
            if tier:
                target["support_tier"] = tier
            if ren:
                target["contract_end"] = ren
        return accounts

    def _load_usage(self) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.executescript((DATA_DIR / "usage_seed.sql").read_text(encoding="utf-8"))
        return conn

    def next_comment_id(self) -> str:
        self._comment_seq += 1
        return f"CM-{self._comment_seq}"


def _target_for(path: str) -> str | None:
    for t in ("cases", "entitlements", "usage"):
        if path.startswith(f"/{t}/"):
            return t
    return None


def create_mock_app(*, rebase_time: bool | None = None, now: datetime | None = None) -> FastAPI:
    if rebase_time is None:
        rebase_time = os.getenv("MOCK_REBASE_TIME", "true").lower() == "true"
    state = MockState(rebase_time=rebase_time, now=now)
    app = FastAPI(title="Mock upstreams", docs_url="/docs", openapi_url="/openapi.json")
    app.state.mock = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"],
        allow_methods=["GET", "POST"],
        allow_headers=["content-type"],
    )

    @app.middleware("http")
    async def fault_injection(request: Request, call_next):
        target = _target_for(request.url.path)
        if target:
            state.calls[target] += 1
            fault = state.faults[target]
            mode = fault["mode"]
            if fault["latency_ms"] and mode in ("slow", "timeout"):
                await asyncio.sleep(fault["latency_ms"] / 1000)
            if mode == "timeout":
                await asyncio.sleep(30)
            if mode == "error":
                return JSONResponse({"error": f"{target} unavailable (injected)"}, status_code=503)
            if mode == "flaky" and fault["fail_next"] > 0:
                fault["fail_next"] -= 1
                return JSONResponse({"error": f"{target} transient failure (injected)"}, status_code=503)
        return await call_next(request)

    # ---- admin ----------------------------------------------------------------------
    @app.post("/_admin/faults")
    async def set_fault(cfg: FaultConfig) -> dict[str, Any]:
        state.faults[cfg.target] = {"mode": cfg.mode, "latency_ms": cfg.latency_ms, "fail_next": cfg.fail_next}
        return {"faults": state.faults}

    @app.get("/_admin/faults")
    async def get_faults() -> dict[str, Any]:
        return {"faults": state.faults, "calls": state.calls}

    @app.post("/_admin/reset")
    async def reset() -> dict[str, str]:
        fresh = MockState(rebase_time=rebase_time, now=now)
        state.__dict__.update(fresh.__dict__)
        return {"status": "reset"}

    # ---- case system ----------------------------------------------------------------
    @app.get("/cases/api/cases")
    async def list_cases(
        accountId: str | None = None,
        status: str | None = None,
        priority: str | None = None,
    ) -> dict[str, Any]:
        statuses = set(status.split(",")) if status else None
        priorities = set(priority.split(",")) if priority else None
        out = []
        for rec in state.cases.values():
            if accountId and rec["accountId"] != accountId:
                continue
            if statuses and rec["Status"] not in statuses:
                continue
            if priorities and rec["priority"] not in priorities:
                continue
            summary = {k: v for k, v in rec.items() if k != "Comments"}
            summary["commentCount"] = len(rec.get("Comments", []))
            out.append(summary)
        return {"totalSize": len(out), "done": True, "records": out}

    @app.get("/cases/api/cases/{case_id}")
    async def get_case(case_id: str) -> dict[str, Any]:
        rec = state.cases.get(case_id)
        if not rec:
            raise HTTPException(404, detail={"errorCode": "NOT_FOUND", "message": "case not found"})
        return rec

    @app.post("/cases/api/cases/{case_id}/comments", status_code=201)
    async def add_comment(
        case_id: str, body: CommentIn, idempotency_key: str | None = Header(default=None)
    ) -> dict[str, Any]:
        rec = state.cases.get(case_id)
        if not rec:
            raise HTTPException(404, detail={"errorCode": "NOT_FOUND"})
        if idempotency_key and idempotency_key in state.comment_idempotency:
            return state.comment_idempotency[idempotency_key]
        comment = {
            "id": state.next_comment_id(),
            "author": body.author,
            "body": body.body,
            "at": _iso(datetime.now(UTC)),
            "visibility": body.visibility,
        }
        rec.setdefault("Comments", []).append(comment)
        rec["version"] += 1
        rec["updatedAt"] = comment["at"]
        if idempotency_key:
            state.comment_idempotency[idempotency_key] = comment
        return comment

    @app.patch("/cases/api/cases/{case_id}")
    async def patch_case(case_id: str, patch: CasePatch, if_match: str | None = Header(default=None)):
        rec = state.cases.get(case_id)
        if not rec:
            raise HTTPException(404, detail={"errorCode": "NOT_FOUND"})
        if if_match is not None and str(rec["version"]) != if_match:
            return JSONResponse({"errorCode": "VERSION_CONFLICT", "currentVersion": rec["version"]}, 412)
        for k, v in patch.model_dump(exclude_none=True).items():
            rec[k] = v
        rec["version"] += 1
        rec["updatedAt"] = _iso(datetime.now(UTC))
        return rec

    # ---- entitlement system ---------------------------------------------------------
    @app.get("/entitlements/api/accounts/{account_id}")
    async def get_account(account_id: str) -> dict[str, Any]:
        acc = state.accounts.get(account_id)
        if not acc:
            raise HTTPException(404, detail={"code": "RCRD_DSNT_EXIST"})
        return acc

    @app.get("/entitlements/api/accounts")
    async def list_accounts() -> dict[str, Any]:
        return {"items": list(state.accounts.values()), "count": len(state.accounts)}

    @app.get("/entitlements/export.csv")
    async def export_csv() -> PlainTextResponse:
        rows = state.csv_rows()
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return PlainTextResponse(buf.getvalue(), media_type="text/csv")

    @app.get("/entitlements/feed.xml")
    async def feed_xml() -> Response:
        return Response(state.xml_feed(), media_type="application/xml")

    # ---- usage warehouse ------------------------------------------------------------
    @app.post("/usage/api/v2/statements")
    async def run_statement(stmt: Statement) -> dict[str, Any]:
        sql = stmt.statement.strip()
        if not sql.lower().startswith("select") or ";" in sql:
            raise HTTPException(422, detail={"code": "002003", "message": "only single SELECT allowed"})
        params = [stmt.bindings[k]["value"] for k in sorted(stmt.bindings, key=int)]
        try:
            cur = state.usage_db.execute(sql, params)
        except sqlite3.Error as exc:
            raise HTTPException(422, detail={"code": "001003", "message": str(exc)}) from exc
        cols = [d[0] for d in cur.description or []]
        # Snowflake's SQL API returns every value as a string - adapters must coerce.
        data = [[None if v is None else str(v) for v in row] for row in cur.fetchall()]
        return {
            "resultSetMetaData": {"numRows": len(data), "rowType": [{"name": c} for c in cols]},
            "data": data,
            "code": "090001",
            "message": "Statement executed successfully.",
        }

    # ---- sample webhook consumer ----------------------------------------------------
    @app.post("/_receiver/webhooks")
    async def receive_webhook(request: Request) -> JSONResponse:
        body = await request.body()
        secret = os.getenv("RECEIVER_WEBHOOK_SECRET", DEFAULT_RECEIVER_SECRET)
        try:
            verify_webhook(secret, dict(request.headers), body)
            verified = True
        except WebhookVerificationError as exc:
            state.received_webhooks.append({"verified": False, "error": str(exc)})
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        event = json.loads(body)
        state.received_webhooks.append(
            {"verified": verified, "webhookId": request.headers.get("webhook-id"), "event": event}
        )
        return JSONResponse({"received": True}, status_code=202)

    @app.get("/_receiver/webhooks")
    async def list_received() -> dict[str, Any]:
        return {"count": len(state.received_webhooks), "items": state.received_webhooks[-50:]}

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
