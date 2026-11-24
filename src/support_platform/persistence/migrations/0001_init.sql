-- 0001_init: tables for state the platform OWNS. Business data (cases, accounts, usage)
-- stays in the systems of record; we never copy it here.

-- Idempotency records: replay protection for POSTs. Scoped per principal so one caller's
-- key can never return another caller's response.
CREATE TABLE idempotency_records (
    principal        TEXT    NOT NULL,
    idempotency_key  TEXT    NOT NULL,
    method           TEXT    NOT NULL,
    path             TEXT    NOT NULL,
    request_hash     TEXT    NOT NULL,            -- sha256 of canonical JSON body
    state            TEXT    NOT NULL CHECK (state IN ('in_progress', 'completed')),
    response_status  INTEGER,
    response_body    TEXT,
    response_headers TEXT,
    created_at       TEXT    NOT NULL,
    expires_at       TEXT    NOT NULL,
    PRIMARY KEY (principal, idempotency_key)      -- also the lookup index
);
CREATE INDEX ix_idempotency_expires ON idempotency_records (expires_at);   -- TTL sweeper

-- Append-only, hash-chained audit log. Every mutation and every agent (delegated) call.
CREATE TABLE audit_events (
    seq             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id        TEXT    NOT NULL UNIQUE,
    occurred_at     TEXT    NOT NULL,
    correlation_id  TEXT    NOT NULL,
    actor_subject   TEXT    NOT NULL,             -- the human
    actor_agent     TEXT,                         -- the agent acting on their behalf, if any
    client_id       TEXT    NOT NULL,
    action          TEXT    NOT NULL,             -- e.g. "POST /v1/cases/{caseId}/escalate"
    resource_type   TEXT,
    resource_id     TEXT,
    outcome         TEXT    NOT NULL CHECK (outcome IN ('success', 'denied', 'failed')),
    http_status     INTEGER NOT NULL,
    details         TEXT    NOT NULL DEFAULT '{}',
    prev_hash       TEXT    NOT NULL,
    hash            TEXT    NOT NULL
);
CREATE INDEX ix_audit_actor_time    ON audit_events (actor_subject, occurred_at);
CREATE INDEX ix_audit_resource_time ON audit_events (resource_type, resource_id, occurred_at);
CREATE INDEX ix_audit_agent_time    ON audit_events (actor_agent, occurred_at) WHERE actor_agent IS NOT NULL;

-- No UPDATE/DELETE on the audit log, enforced in the database not just in code.
CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

CREATE TABLE webhook_subscriptions (
    id           TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    event_types  TEXT NOT NULL,                   -- JSON array
    secret       TEXT NOT NULL,                   -- prod: KMS-encrypted / secret-manager reference
    description  TEXT,
    status       TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    created_by   TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX ix_subscriptions_status ON webhook_subscriptions (status);

-- Transactional outbox: domain events are written here first, then published to the
-- local event bus / webhooks by the dispatcher (at-least-once).
CREATE TABLE outbox_events (
    id            TEXT PRIMARY KEY,
    event_type    TEXT NOT NULL,
    payload       TEXT NOT NULL,
    occurred_at   TEXT NOT NULL,
    published_at  TEXT
);
CREATE INDEX ix_outbox_unpublished ON outbox_events (occurred_at) WHERE published_at IS NULL;

CREATE TABLE webhook_deliveries (
    id               TEXT PRIMARY KEY,
    event_id         TEXT NOT NULL REFERENCES outbox_events (id),
    subscription_id  TEXT NOT NULL REFERENCES webhook_subscriptions (id),
    status           TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'dead')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    next_attempt_at  TEXT NOT NULL,
    last_status_code INTEGER,
    last_error       TEXT,
    updated_at       TEXT NOT NULL,
    UNIQUE (event_id, subscription_id)
);
CREATE INDEX ix_deliveries_due ON webhook_deliveries (status, next_attempt_at);
