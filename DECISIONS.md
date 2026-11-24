# My decisions

_Author: **Jigar Mehta**_

This file explains the main choices I made, what I assumed, and what I left out on purpose.

## The basic idea

I built one API that sits in front of the three systems. Every user of the API (integration tools,
the console and the AI helper) sees the same names, the same login rules and the same error format.

The three systems are a bit messy. For example, the case system writes `Status` with a capital S,
and the usage warehouse sends every number as text. I clean all of that up in one file,
`upstreams/translators.py`, so the rest of the code never has to worry about it.

The AI helper's MCP server does not talk to the three systems directly. It calls my API like any
other app. That means the permission checks, the hiding of revenue (ARR), the business rules and the
audit log are all done in one place. The AI can't take a shortcut around them.

I used Python with FastAPI for the API. The customer page asks three systems at once, so an async
framework fits well, and the official MCP library works well in Python. The console uses React,
TypeScript and Tailwind, and the API serves it.

I didn't deploy anything. In a MuleSoft-style setup, this API would be the "process API", sitting on
top of separate APIs for Salesforce, NetSuite and Snowflake. On AWS, I would run it in containers on
ECS Fargate behind an API gateway, keep my own tables in Aurora Postgres, and send events through
EventBridge.

## How I designed the API

The full details are in `openapi.yaml`. These are the main points:

- **Combine or pass through?** The customer endpoint combines data from all three systems, because
  people want one answer about a customer. Cases and comments are passed through as they are, because
  the case system owns them. When you add a comment, it goes straight to the case system.
- **Filters that use two systems.** You can filter cases by the customer's tier and renewal date.
  Without this, every app would need many extra calls just to answer the example question.
  Adding account details to each case is optional (`include=account`).
- **Paging.** Each page gives you a "cursor" to get the next page. The cursor is signed and tied to
  your filters. If you change the filters and reuse an old cursor, you get a clear error, not wrong
  results. I don't return a total count, because that would mean reading everything every time.
- **Errors.** Every error uses the same standard format (RFC 9457) and includes a tracking ID. When
  one of the three systems fails, the error says which one.
- **No duplicate comments.** Adding a comment needs an `Idempotency-Key`, which is a unique ID for
  that request. If the same request is sent twice, the second one returns the first result and no
  duplicate is made. Same key with different text is an error.
- **No overwriting someone else's change.** To escalate a case you must send its current version
  number (the `ETag`, in an `If-Match` header). If someone changed the case since you read it, you
  get an error instead of overwriting their change.
- **Versions.** The version is in the URL (`/v1`). Inside v1, I only add things and never break old
  ones. When something is being retired, the API says so with `Deprecation` and `Sunset` headers.
  You can see this working on the old `account_id` filter.
- **Permissions.** Each action needs a permission ("scope"). Some fields need their own permission
  too: only Finance (`finance:read`) can see revenue, and only people with `pii:read` can see contact
  details. Hidden fields are left out, and their names are listed in `redactedFields`.
- **Who wrote a comment** is taken from the login token, never from the request, so nobody can fake it.
- **REST, GraphQL or gRPC?** REST suits these users best. GraphQL would be better for a big dashboard
  that needs lots of linked data at once. gRPC would be better for fast, high-volume calls between
  internal services.

## The data I store

I only store data that belongs to this platform. Cases, accounts and usage stay in their own systems.

| Table | Why I need it | Indexes, and why |
|---|---|---|
| `idempotency_records` | Remembers recent requests so repeats don't create duplicates | Key on (who sent it, request ID), checked on every POST; a date index for cleaning up old entries |
| `audit_events` | A log of every important action. Rows can't be edited or deleted. | By person and time, by case and time, and by AI agent and time. These answer "what did this person do?", "what happened to this case?" and "what did the AI do?" |
| `webhook_subscriptions` | Who wants to be told about events | By status, to find active subscribers quickly |
| `outbox_events` | Events waiting to be sent | Only unsent events are indexed, so this stays small and fast |
| `webhook_deliveries` | Whether each subscriber got each event | One row per event and subscriber, so nothing is sent twice; by status and next try time, to find what's due |

I used SQLite because it needs no setup. The SQL also works on Postgres.

## When the other systems are slow or down

- Each call to another system waits at most 2 seconds, and at most 5 seconds in total with retries.
  Retries wait a little longer each time, and only happen when it is safe to repeat the call.
  Escalating a case is never retried, because the version check already protects it.
- Each system has a "circuit breaker". After 5 failures in a row, I stop calling that system for
  30 seconds and fail fast instead. "Not found" type answers don't count as failures.
- If usage or cases are down, the customer page still answers. The missing part is empty and the
  response says `degraded: true`. If the entitlement system is down, I use a saved copy (from its CSV
  and XML files) and mark it as `stale`. I only give up with an error if I have no customer data at all.
- If a filter needs the entitlement system and it is down, I return an error instead of guessing.
- The case search asks the entitlement and case systems at the same time, so in an outage you wait
  for one timeout, not two.

## How I designed the AI tools

The AI tools are not a copy of the REST API. AI models are good at understanding what someone means,
but bad at date maths, so I shaped the tools around that.

| REST API | AI tool | Why it's different |
|---|---|---|
| `GET /v1/cases?openedBefore=<date>&renewalBefore=<date>&...` | `search_cases(priority, support_tier, min_open_hours, renewal_within_days, ...)` | The AI just says "48 hours" or "90 days" and the server works out the dates. Account details are always included, and the tool repeats back the filters it used. |
| Full records | Small results with only the fields needed | Uses fewer tokens. The example answer is about 2 KB. |
| `GET /v1/cases/{id}` | `get_case_details` | Only the latest comments, checked for tricks, and marked as "not trusted". |
| `GET /v1/customers/{id}` | `get_customer_summary` | Simpler shape, and it says clearly what is hidden or missing. |
| `POST .../comments` | `add_case_comment` | A person must approve. The duplicate-protection ID is made automatically. |
| `POST .../escalate` | `escalate_case` | A person must approve that exact version of the case. There is no "escalate many" tool on purpose. |

The tool inputs use fixed lists of allowed values (for priority, status, tier and reason), limits on
numbers (at most 25 results), and patterns for IDs. Each description says when to use the tool. When
something fails, the tool returns a short hint so the AI knows what to tell the user.

I added a fifth tool, `get_case_details`, so I could properly test the "harmful instructions hidden
in a comment" case.

## What I assumed

- I kept the odd details in the sample data (`Status` with a capital S, and both `ACC-77` and
  `ACC-007`). I treat IDs exactly as given. Changing `ACC-77` to `ACC-077` could mix up two customers.
- "Open" in the example question means any active case (open, in progress, or waiting on the
  customer). If you use only status `open`, you still get the same four customers.
- When the XML feed and the CSV file disagree about tier or renewal date, the XML feed wins, because
  it is newer.
- The sample dates move with today's date when the fake systems start, so questions like "open for
  more than 48 hours" always make sense.
- The local login service is only a stand-in for a real company login, and it is switched off
  outside local mode.

## What I skipped, and what I would do with more time

| Skipped | What I would do |
|---|---|
| A real company login (I use a simple local one) | Use proper signed tokens from Okta or Entra, which also support handing a user's rights to an agent |
| Postgres and running several copies | Move the same tables to Aurora, and move rate limits to Redis or the API gateway |
| A real message queue | Send events to EventBridge or Kafka. The outbox already makes sure no event is lost. |
| Paging inside the case system | Ask Salesforce for one page at a time instead of paging in my code |
| Refreshing the saved entitlement copy | Refresh it on a schedule and alert if it gets too old |
| AI conversation tests in CI | Run the conversation scenarios from TESTEVALS.md every night |
| Tracing | Add OpenTelemetry. Tracking IDs already flow through every step. |
| Kubernetes or serverless example | The brief allowed one extra, and I chose the event-driven part instead |
