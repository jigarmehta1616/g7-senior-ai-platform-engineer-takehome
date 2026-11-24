"""Escalation business rules - pure functions, no I/O, exhaustively unit-tested.

Rules (documented in openapi.yaml under the escalate operation):
  R1  Only active cases (open / in_progress / pending_customer) can be escalated.     -> 409
  R2  Max escalation level is 2 (L1 = tier-2 support / engineering, L2 = duty manager). -> 409
  R3  Standard-tier customers cannot escalate P3 cases (not in their entitlement).    -> 422
  R4  reason=other requires a note (auditability).                                     -> 422
  R5  Target team is derived from entitlement: Platinum -> engineering on-call.
"""

from __future__ import annotations

from dataclasses import dataclass

from support_platform.domain import errors
from support_platform.domain.models import (
    ACTIVE_STATUSES,
    Case,
    EscalationReason,
    Priority,
    SupportTier,
)

MAX_LEVEL = 2


@dataclass(frozen=True)
class EscalationPlan:
    new_level: int
    target_team: str


def plan_escalation(case: Case, tier: SupportTier, reason: EscalationReason, note: str | None) -> EscalationPlan:
    if case.status not in ACTIVE_STATUSES:
        raise errors.invalid_state_transition(
            f"Case {case.id} is '{case.status.value}' and cannot be escalated.", "CASE_NOT_ACTIVE")
    if case.escalation.level >= MAX_LEVEL:
        raise errors.invalid_state_transition(
            f"Case {case.id} is already at the maximum escalation level ({MAX_LEVEL}).", "ESCALATION_LIMIT_REACHED")
    if tier is SupportTier.STANDARD and case.priority is Priority.P3:
        raise errors.business_rule_violation(
            "Standard-tier entitlements do not include escalation of P3 cases.", "NOT_ENTITLED")
    if reason is EscalationReason.OTHER and not (note and note.strip()):
        raise errors.business_rule_violation("A note is required when reason is 'other'.", "NOTE_REQUIRED")
    new_level = case.escalation.level + 1
    if new_level == MAX_LEVEL:
        team = "duty_manager"
    elif tier is SupportTier.PLATINUM:
        team = "engineering_on_call"
    else:
        team = "tier2_support"
    return EscalationPlan(new_level=new_level, target_team=team)
