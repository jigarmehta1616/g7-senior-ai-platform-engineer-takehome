"""RFC 9457 problem types. One exception type, many named constructors, so every error
path in the codebase produces the same wire shape (``application/problem+json``)."""

from __future__ import annotations

from typing import Any

PROBLEM_BASE = "https://api.example.com/problems/"


class ProblemError(Exception):
    def __init__(
        self,
        status: int,
        slug: str,
        title: str,
        detail: str | None = None,
        *,
        headers: dict[str, str] | None = None,
        errors: list[dict[str, str]] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status = status
        self.slug = slug
        self.title = title
        self.detail = detail
        self.headers = headers or {}
        self.errors = errors
        self.extensions = extensions or {}

    @property
    def type_uri(self) -> str:
        return PROBLEM_BASE + self.slug

    def to_body(self, *, instance: str, correlation_id: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": self.type_uri,
            "title": self.title,
            "status": self.status,
            "instance": instance,
            "correlationId": correlation_id,
        }
        if self.detail:
            body["detail"] = self.detail
        if self.errors:
            body["errors"] = self.errors
        body.update(self.extensions)
        return body


# ---- named constructors ---------------------------------------------------------------

def validation_error(detail: str, errors: list[dict[str, str]] | None = None) -> ProblemError:
    return ProblemError(400, "validation-error", "Request validation failed", detail, errors=errors)


def invalid_cursor() -> ProblemError:
    return ProblemError(400, "invalid-cursor", "Invalid pagination cursor",
                        "The cursor is malformed, tampered with, or was issued for different filters.")


def unauthenticated(detail: str = "A valid bearer token is required.") -> ProblemError:
    return ProblemError(401, "unauthenticated", "Authentication required", detail,
                        headers={"WWW-Authenticate": 'Bearer realm="support-platform"'})


def insufficient_scope(required: list[str]) -> ProblemError:
    return ProblemError(
        403, "insufficient-scope", "Insufficient scope",
        f"This operation requires scope(s): {' '.join(required)}",
        headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{" ".join(required)}"'},
        extensions={"requiredScopes": required},
    )


def not_found(resource: str, resource_id: str) -> ProblemError:
    return ProblemError(404, "not-found", "Resource not found", f"{resource} '{resource_id}' does not exist.")


def payload_too_large(limit: int) -> ProblemError:
    return ProblemError(413, "payload-too-large", "Payload too large", f"Request body exceeds {limit} bytes.")


def precondition_required() -> ProblemError:
    return ProblemError(428, "precondition-required", "Precondition required",
                        "Send If-Match with the case ETag from GET /v1/cases/{caseId}.")


def etag_mismatch(current_etag: str) -> ProblemError:
    return ProblemError(412, "etag-mismatch", "Precondition failed",
                        "The case was modified since you read it. Re-fetch and retry.",
                        headers={"ETag": current_etag}, extensions={"currentEtag": current_etag})


def idempotency_key_reused() -> ProblemError:
    return ProblemError(422, "idempotency-key-reuse", "Idempotency key reused",
                        "This Idempotency-Key was already used with a different request payload.")


def idempotency_in_progress() -> ProblemError:
    return ProblemError(409, "idempotency-in-progress", "Request in progress",
                        "A request with this Idempotency-Key is still being processed. Retry shortly.",
                        headers={"Retry-After": "1"})


def invalid_state_transition(detail: str, code: str) -> ProblemError:
    return ProblemError(409, "invalid-state-transition", "Invalid state transition", detail,
                        extensions={"code": code})


def business_rule_violation(detail: str, code: str) -> ProblemError:
    return ProblemError(422, "business-rule-violation", "Business rule violation", detail,
                        extensions={"code": code})


def rate_limited(retry_after_s: int, limit: int) -> ProblemError:
    return ProblemError(
        429, "rate-limited", "Too many requests", f"Rate limit of {limit} requests/minute exceeded.",
        headers={"Retry-After": str(retry_after_s), "RateLimit-Limit": str(limit),
                 "RateLimit-Remaining": "0", "RateLimit-Reset": str(retry_after_s)},
    )


def upstream_unavailable(source: str, reason: str) -> ProblemError:
    return ProblemError(503, "upstream-unavailable", "Upstream system unavailable",
                        f"The {source} system is unavailable ({reason}). Retry later.",
                        headers={"Retry-After": "5"}, extensions={"upstream": source, "reason": reason})


def upstream_bad_response(source: str) -> ProblemError:
    return ProblemError(502, "upstream-bad-response", "Bad upstream response",
                        f"The {source} system returned data we couldn't interpret.", extensions={"upstream": source})


def upstream_timeout(source: str) -> ProblemError:
    return ProblemError(504, "upstream-timeout", "Upstream timeout",
                        f"The {source} system did not respond in time.", extensions={"upstream": source})
