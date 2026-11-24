from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from support_platform.domain.cursor import CursorCodec
from support_platform.domain.errors import ProblemError
from support_platform.domain.escalation import plan_escalation
from support_platform.domain.models import (
    Case,
    CaseStatus,
    Escalation,
    EscalationReason,
    Priority,
    SupportTier,
)
from support_platform.persistence.db import Database
from support_platform.services.audit import AuditEntry, AuditService
from support_platform.services.idempotency import IdempotencyService, request_fingerprint
from support_platform.services.rate_limit import RateLimiter

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)


def _case(status=CaseStatus.OPEN, priority=Priority.P1, level=0) -> Case:
    return Case(id="CS-1", account_id="ACC-1", priority=priority, status=status, subject="s", opened_at=NOW,
                updated_at=NOW, version=1, escalation=Escalation(level=level))


# ---- escalation rules ------------------------------------------------------------------

@pytest.mark.parametrize("status", [CaseStatus.RESOLVED, CaseStatus.CLOSED])
def test_r1_inactive_cases_cannot_be_escalated(status):
    with pytest.raises(ProblemError) as ei:
        plan_escalation(_case(status=status), SupportTier.PLATINUM, EscalationReason.CUSTOMER_IMPACT, None)
    assert ei.value.status == 409 and ei.value.extensions["code"] == "CASE_NOT_ACTIVE"


def test_r2_max_level():
    with pytest.raises(ProblemError) as ei:
        plan_escalation(_case(level=2), SupportTier.PLATINUM, EscalationReason.CUSTOMER_IMPACT, None)
    assert ei.value.extensions["code"] == "ESCALATION_LIMIT_REACHED"


def test_r3_standard_tier_p3_not_entitled():
    with pytest.raises(ProblemError) as ei:
        plan_escalation(_case(priority=Priority.P3), SupportTier.STANDARD, EscalationReason.CUSTOMER_IMPACT, None)
    assert ei.value.status == 422 and ei.value.extensions["code"] == "NOT_ENTITLED"


def test_r4_other_requires_note():
    with pytest.raises(ProblemError):
        plan_escalation(_case(), SupportTier.GOLD, EscalationReason.OTHER, "  ")
    assert plan_escalation(_case(), SupportTier.GOLD, EscalationReason.OTHER, "exec asked").new_level == 1


@pytest.mark.parametrize(("tier", "level", "team"), [
    (SupportTier.PLATINUM, 0, "engineering_on_call"),
    (SupportTier.GOLD, 0, "tier2_support"),
    (SupportTier.PLATINUM, 1, "duty_manager"),
])
def test_r5_target_team_is_derived(tier, level, team):
    assert plan_escalation(_case(level=level), tier, EscalationReason.SLA_BREACH_RISK, None).target_team == team


# ---- cursor ----------------------------------------------------------------------------

def test_cursor_roundtrip_and_tamper_and_filter_binding():
    codec = CursorCodec("secret")
    cur = codec.encode(["2026-11-20T00:00:00+00:00", "CS-1"], "f1")
    assert codec.decode(cur, "f1") == ["2026-11-20T00:00:00+00:00", "CS-1"]
    with pytest.raises(ProblemError):
        codec.decode(cur, "f2")                                   # different filters
    with pytest.raises(ProblemError):
        codec.decode(cur[:-2] + ("AA" if not cur.endswith("AA") else "BB"), "f1")   # tampered
    with pytest.raises(ProblemError):
        CursorCodec("other").decode(cur, "f1")                    # forged with another key
    with pytest.raises(ProblemError):
        codec.decode("garbage", "f1")


# ---- idempotency -----------------------------------------------------------------------

@pytest.fixture
def db(tmp_path) -> Iterator[Database]:
    database = Database(str(tmp_path / "platform.db"))
    database.migrate()
    yield database
    database.close()


def test_idempotency_lifecycle(db):
    svc = IdempotencyService(db, lambda: NOW, ttl_hours=24)
    fp = request_fingerprint("POST", "/x", {"body": "a"})
    assert svc.begin("alice", "key-12345678", "POST", "/x", fp) is None
    with pytest.raises(ProblemError) as ei:                       # concurrent duplicate
        svc.begin("alice", "key-12345678", "POST", "/x", fp)
    assert ei.value.status == 409
    svc.complete("alice", "key-12345678", 201, {"id": "CM-1"}, {"Location": "/x/CM-1"})
    replay = svc.begin("alice", "key-12345678", "POST", "/x", fp)
    assert replay and replay.status == 201 and replay.body == {"id": "CM-1"}
    with pytest.raises(ProblemError) as ei:                       # same key, different body
        svc.begin("alice", "key-12345678", "POST", "/x", request_fingerprint("POST", "/x", {"body": "b"}))
    assert ei.value.status == 422
    assert svc.begin("bob", "key-12345678", "POST", "/x", fp) is None   # keys are per principal


def test_idempotency_abandon_allows_retry(db):
    svc = IdempotencyService(db, lambda: NOW, ttl_hours=24)
    fp = request_fingerprint("POST", "/x", {})
    svc.begin("alice", "key-abcdefgh", "POST", "/x", fp)
    svc.abandon("alice", "key-abcdefgh")
    assert svc.begin("alice", "key-abcdefgh", "POST", "/x", fp) is None


# ---- audit chain -----------------------------------------------------------------------

def test_audit_chain_detects_tampering(db):
    audit = AuditService(db, lambda: NOW)
    for i in range(3):
        audit.record(AuditEntry("cid-00000001", "alice", None, "console", f"POST /v1/x/{i}", "case", f"CS-{i}",
                                "success", 200, {}))
    assert audit.verify_chain() == (True, 3)
    with pytest.raises(Exception, match="append-only"):
        db.query("UPDATE audit_events SET outcome = 'denied' WHERE seq = 2")
    # Bypass the trigger to simulate an attacker with raw file access:
    db._conn.execute("DROP TRIGGER audit_events_no_update")
    db._conn.execute("UPDATE audit_events SET outcome = 'denied' WHERE seq = 2")
    ok, bad_seq = audit.verify_chain()
    assert not ok and bad_seq == 2


# ---- rate limiter ----------------------------------------------------------------------

def test_token_bucket_refills():
    t = {"now": 0.0}
    rl = RateLimiter(clock=lambda: t["now"])
    assert all(rl.check("k", 3).allowed for _ in range(3))
    denied = rl.check("k", 3)
    assert not denied.allowed and denied.reset_s >= 1
    t["now"] = 20.0                                   # 3/min => one token per 20s
    assert rl.check("k", 3).allowed
