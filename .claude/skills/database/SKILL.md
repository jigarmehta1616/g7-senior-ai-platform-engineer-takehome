---
name: database
description: Change platform-owned persistence (SQLite now, Postgres-portable) - new tables, columns, indexes, migrations, idempotency, audit log, outbox or webhook delivery storage. Use for any schema or query change under src/support_platform/persistence.
---

# Database playbook

## What lives here (and what never does)
We store only state the platform **owns**: idempotency records, the audit log, webhook
subscriptions/deliveries, the event outbox. Cases, accounts and usage stay in their systems of
record — never cache or copy business data into this DB.

## Migrations
- Forward-only numbered files: `persistence/migrations/000N_<what>.sql`. Never edit an applied file.
- `Database.migrate()` applies pending files in one transaction each and records them in
  `schema_migrations`.
- Write portable SQL (TEXT timestamps in ISO-8601 UTC, no SQLite-only types) so the schema moves to
  Postgres unchanged. Partial indexes (`WHERE ...`) are fine in both.
- Additive first: add nullable column -> backfill -> enforce. No destructive change without a
  documented data-retention decision.

## Indexing rules
- Every query path has an index that matches its WHERE + ORDER BY (see comments in `0001_init.sql`).
- Hot "pending work" queues use partial indexes (`ix_outbox_unpublished`, `ix_deliveries_due`).
- Composite primary keys double as lookup indexes (`idempotency_records (principal, key)`).

## Invariants to preserve
- `audit_events` is append-only (triggers block UPDATE/DELETE) and hash-chained; never add a code
  path that rewrites rows. `AuditService.verify_chain()` must stay O(n) and side-effect free.
- Idempotency keys are scoped per principal; responses are replayed verbatim; TTL 24h via
  `expires_at` (sweeper: `IdempotencyService.purge_expired`).
- Outbox writes happen in the same transaction boundary as the state they describe.

## Access pattern
`Database.tx()` = `BEGIN IMMEDIATE` under a lock; `Database.query()` for reads. All statements
are parameterised — no f-string SQL with user input (ruff `S608` will flag it).

## Verify
```
rtk test .venv/Scripts/python -m pytest tests/unit/test_domain_rules.py -q
sqlite3 var/platform.db ".schema"     # inspect a local DB
```
