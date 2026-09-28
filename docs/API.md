# API Reference — v1

SkillBridge AI, version 1.0.0.

This document is the written contract. Two generated companions describe the
same API and are kept in step with it:

- **Interactive docs** — with the API running, open
  <http://127.0.0.1:8000/docs> to read every route and call it from the
  browser. Sign in with `POST /api/v1/auth/login`, copy the `accessToken`, and
  paste it into **Authorize**.
- **`docs/openapi.json`** — the OpenAPI 3.1 description, committed so contract
  changes show up in pull request diffs. Regenerate it with
  `python scripts/export_openapi.py`; CI fails if it is stale.

A test (`backend/tests/test_api_contract.py`) fails if a route exists that the
table below does not list, if the table lists a route that does not exist, or
if the code raises an error code this document never mentions.

Base URL (local): `http://127.0.0.1:8000`

Member identity is always derived from the verified access token. The API never
trusts a client-supplied identifier when deciding access to a member's
information.

All requests and responses are JSON. Every response carries an `X-Request-ID`
header; the same value appears as `requestId` in any error body.

---

## Authentication

`POST /api/v1/auth/login` → **200**

```json
{ "email": "member@example.com", "password": "DemoPassw0rd!" }
```

```json
{
  "accessToken": "eyJhbGciOi...",
  "tokenType": "Bearer",
  "expiresIn": 3600,
  "role": "CUSTOMER",
  "displayName": "Alex Rivera"
}
```

Send the token on every other call: `Authorization: Bearer <accessToken>`.

---

## Endpoint summary

| Method | Endpoint | Purpose | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | Sign in and receive a bearer token | 200 |
| POST | `/api/v1/conversations` | Create a conversation | 201 |
| POST | `/api/v1/conversations/{conversationId}/messages` | Submit a customer message | 200 |
| GET | `/api/v1/conversations/{conversationId}` | Retrieve authorized history | 200 |
| POST | `/api/v1/conversations/{conversationId}/escalate` | Request human escalation | 201 |
| POST | `/api/v1/conversations/{conversationId}/feedback` | Submit feedback | 201 |
| GET | `/api/v1/agent/cases` | List open cases (agent only) | 200 |
| GET | `/api/v1/agent/cases/{caseId}` | Retrieve a case (agent only) | 200 |
| PATCH | `/api/v1/agent/cases/{caseId}` | Update case status (agent only) | 200 |
| GET | `/api/v1/agent/recommendations` | List AI improvement candidates (agent only) | 200 |
| PATCH | `/api/v1/agent/recommendations/{recommendationId}` | Approve or reject a candidate (agent only) | 200 |
| POST | `/api/v1/agent/analytics/run` | Run the Learning Analytics Worker on demand (agent only) | 200 |
| POST | `/api/v1/agent/cases/{caseId}/reply` | Reply to the member in their conversation (agent only) | 201 |
| POST | `/api/v1/agent/cases/{caseId}/claim` | Take a case without replying yet (agent only) | 200 |
| GET | `/api/v1/agent/cases/{caseId}/replies` | Counsellor replies on a case (agent only) | 200 |
| GET | `/api/v1/agent/workload` | Open cases held by the signed-in counsellor (agent only) | 200 |
| GET | `/api/v1/ops/metrics` | Operational counters (agent only) | 200 |
| GET | `/api/v1/health` | Application health | 200 |

The seven endpoints from the System Design Specification are unchanged in shape
since the Alpha. Everything else in the table was added to support the
counsellor dashboard, human replies and operations, and none of it altered an
existing request or response.

---

## POST /api/v1/conversations

No request body. Creates a conversation for the authenticated customer.

```json
{
  "conversationId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ACTIVE",
  "createdAt": "2026-08-27T20:30:00Z"
}
```

Authentication failures return **401**.

---

## POST /api/v1/conversations/{conversationId}/messages

### Request

```json
{ "message": "Which certification should I work toward next?" }
```

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `message` | String | Yes | 1–2,000 characters; trimmed; cannot be blank |

| Path parameter | Type | Constraints |
| --- | --- | --- |
| `conversationId` | UUID | Must belong to the authenticated user |

### Response

```json
{
  "conversationId": "550e8400-e29b-41d4-a716-446655440000",
  "messageId": "179abb70-e469-44f8-aaf4-338288805024",
  "response": "A foundational IT certification is the closest next step.",
  "status": "ANSWERED",
  "escalationReason": null,
  "timestamp": "2026-08-27T20:30:00Z"
}
```

| Field | Type | Constraints |
| --- | --- | --- |
| `conversationId` | UUID | Matches the active conversation |
| `messageId` | UUID | Unique message identifier |
| `response` | String | Maximum 4,000 characters |
| `status` | Enum | `ANSWERED`, `ESCALATED` or `ERROR` |
| `escalationReason` | Enum \| null | Null unless escalation occurs |
| `timestamp` | ISO 8601 | UTC |

**Escalation is rule-based, not confidence-based.** The application does not
use an undefined numeric AI confidence score. `status` becomes `ESCALATED`
when one of these deterministic conditions holds:

| Condition | `escalationReason` | Evaluated |
| --- | --- | --- |
| Member asks for a person | `CUSTOMER_REQUEST` | Before the model is called |
| Security-sensitive content or a raw identifier in the message | `SECURITY_CONCERN` | Before the model is called |
| Assistant reports the request is outside supported material | `UNSUPPORTED_TOPIC` | After generation |
| Response fails a validation rule | `VALIDATION_FAILURE` | After generation |
| Provider unavailable after the retry policy | `AI_SERVICE_FAILURE` | After generation |

Errors: **400** malformed identifier · **401** · **403** not the caller's
conversation · **404** conversation missing · **409** conversation closed ·
**413** payload too large · **422** message length · **429** rate limit.

---

## GET /api/v1/conversations/{conversationId}

```json
{
  "conversationId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ACTIVE",
  "createdAt": "2026-08-27T20:30:00Z",
  "messages": [
    {
      "messageId": "179abb70-e469-44f8-aaf4-338288805024",
      "sender": "ASSISTANT",
      "content": "A foundational IT certification is the closest next step.",
      "status": "ANSWERED",
      "escalationReason": null,
      "sources": ["Certifications that build on training you have already completed"],
      "timestamp": "2026-08-27T20:30:00Z"
    }
  ]
}
```

`sources` names the approved knowledge-base articles the answer drew on, so a
customer or agent can see why an answer was given.

Errors: **401** · **403** not the caller's conversation · **404** missing.

---

## POST /api/v1/conversations/{conversationId}/escalate

```json
{ "reason": "CUSTOMER_REQUEST" }
```

Approved values: `CUSTOMER_REQUEST`, `UNSUPPORTED_TOPIC`, `SECURITY_CONCERN`,
`VALIDATION_FAILURE`, `AI_SERVICE_FAILURE`.

```json
{
  "caseId": "20858f25-ee13-49de-86cf-efcfbf35378a",
  "status": "QUEUED",
  "queue": "CAREER_COUNSELING"
}
```

`SECURITY_CONCERN` routes to the `ACCOUNT_SECURITY` queue; every other reason
routes to `CAREER_COUNSELING`.

A second escalation while one is still active returns **409**
`ESCALATION_ALREADY_ACTIVE` rather than creating a duplicate case.

---

## POST /api/v1/conversations/{conversationId}/feedback

```json
{
  "messageId": "179abb70-e469-44f8-aaf4-338288805024",
  "rating": "HELPFUL",
  "comment": "That gave me a clear next step."
}
```

| Field | Type | Required | Constraints |
| --- | --- | --- | --- |
| `messageId` | UUID | Yes | Must belong to the referenced conversation |
| `rating` | Enum | Yes | `HELPFUL` or `UNHELPFUL` |
| `comment` | String | No | Maximum 1,000 characters |

```json
{
  "feedbackId": "0f1e...",
  "conversationId": "550e8400-e29b-41d4-a716-446655440000",
  "messageId": "179abb70-e469-44f8-aaf4-338288805024",
  "rating": "HELPFUL",
  "recordedAt": "2026-08-27T20:31:00Z"
}
```

Feedback is recorded for later analysis and never modifies production AI
behaviour directly. Errors: **404** `MESSAGE_NOT_FOUND` · **422**
`INVALID_COMMENT` or `FEEDBACK_ALREADY_RECORDED`.

---

## Agent endpoints

All require the `AGENT` role; any other role receives **403**.

`GET /api/v1/agent/cases` returns the open queue.

`GET /api/v1/agent/cases/{caseId}` returns the case with its escalation reason,
status, queue, handover summary and the relevant conversation history, so the
customer does not have to restart the interaction.

`PATCH /api/v1/agent/cases/{caseId}` accepts `{"status": "ASSIGNED"}`,
`"RESOLVED"` or `"CLOSED"`. Resolving or closing a case closes the
conversation. Updating an already-closed case returns **409**.

---

## Counsellor replies

Owned by the Escalation Module. All four require the `AGENT` role.

A reply is written into the member's own conversation, so the member reads it
through `GET /api/v1/conversations/{conversationId}` like any other message —
there is no second inbox. The client polls that endpoint every five seconds
while a conversation is `ESCALATED`, and stops when it is not.

### POST /api/v1/agent/cases/{caseId}/reply → 201

```json
{ "message": "Happy to help. Based on your network coursework, let's look at two options." }
```

Returns the stored message, the same `MessageView` shape a conversation
returns. A counsellor reply has `sender: "AGENT"` and **no `status`** —
`ANSWERED` and `ESCALATED` describe what the assistant did with a turn, and
reusing them would inflate the operations counters.

```json
{
  "messageId": "0c4b8f7e-3a2d-4d6e-9f1a-5b7c2e8d9a10",
  "sender": "AGENT",
  "content": "Happy to help. Based on your network coursework, let's look at two options.",
  "status": null,
  "escalationReason": null,
  "sources": [],
  "timestamp": "2026-09-28T14:05:11Z"
}
```

Replying also claims the case if nobody holds it yet.

| HTTP | Code | When |
| --- | --- | --- |
| 403 | `FORBIDDEN` | The case is assigned to another counsellor |
| 404 | `CASE_NOT_FOUND` | No case with that id |
| 409 | `CASE_NOT_OPEN` | The case is resolved or closed |
| 422 | `INVALID_REPLY` | Empty, whitespace only, or longer than 4,000 characters |

### POST /api/v1/agent/cases/{caseId}/claim → 200

No body. Returns the case summary with `status: "ASSIGNED"`. Claiming a case
you already hold is a no-op, so a double click is harmless.

| HTTP | Code | When |
| --- | --- | --- |
| 404 | `CASE_NOT_FOUND` | No case with that id |
| 409 | `CASE_ALREADY_ASSIGNED` | Another counsellor holds it |
| 409 | `CASE_NOT_OPEN` | The case is resolved or closed |

### GET /api/v1/agent/cases/{caseId}/replies → 200

An array of `MessageView`, counsellor replies only, oldest first.

### GET /api/v1/agent/workload → 200

```json
{ "openCases": 2 }
```

Queued or assigned cases held by the signed-in counsellor. It is a count, not a
cap.

---

## Reviewed AI configuration

The Learning Analytics Worker aggregates feedback and escalation patterns into
improvement candidates. Every candidate starts as `PENDING_REVIEW`; an
individual conversation can never change production AI behaviour on its own.

`GET /api/v1/agent/recommendations` returns up to 50 candidates, newest first.
Add `?status=PENDING_REVIEW` to filter.

```json
[
  {
    "recommendationId": "8a1f...",
    "category": "ESCALATION_UNSUPPORTED_TOPIC",
    "detail": "2 conversations escalated with reason UNSUPPORTED_TOPIC during the review period. Review the knowledge base for a coverage gap and propose a new approved article.",
    "occurrences": 2,
    "reviewStatus": "PENDING_REVIEW",
    "periodStart": "2026-09-07T00:00:00Z",
    "periodEnd": "2026-09-14T00:00:00Z",
    "createdAt": "2026-09-14T03:15:00Z"
  }
]
```

`PATCH /api/v1/agent/recommendations/{recommendationId}` records a decision:

```json
{ "reviewStatus": "APPROVED" }
```

`PENDING_REVIEW` is rejected as a decision (**409** `INVALID_REVIEW_DECISION`),
and a candidate can only be decided once (**409**
`RECOMMENDATION_ALREADY_REVIEWED`) so the audit trail stays meaningful. A
missing candidate returns **404** `RECOMMENDATION_NOT_FOUND`.

`POST /api/v1/agent/analytics/run?days=7` runs the worker once and returns
`{"recommendationsCreated": 1, "ranAt": "..."}`. **Alpha scope:** in the target
system a scheduler drives the worker off the message queue; this endpoint runs
the same code so the asynchronous path can be demonstrated on demand.

**Approving a candidate does not apply it.** Nothing in the platform reads an
`APPROVED` recommendation and changes a prompt or a routing rule; that step is
deliberately out of scope for the Alpha.

---

## GET /api/v1/ops/metrics

Agent role required. Counters for **this instance only** — behind a load
balancer each instance reports its own, which `instanceId` makes explicit.

```json
{
  "instanceId": "vm-e175bb61",
  "collectedAt": "2026-09-14T03:15:19Z",
  "uptimeSeconds": 17,
  "requests": { "total": 23, "byStatusClass": { "2xx": 23 } },
  "conversationTurns": {
    "total": 4,
    "byStatus": { "ANSWERED": 1, "ESCALATED": 3 },
    "escalationsByReason": { "UNSUPPORTED_TOPIC": 2, "CUSTOMER_REQUEST": 1 },
    "escalationRate": 0.75
  },
  "latencyMs": { "p50": 9, "p95": 11, "max": 14, "overFiveSecondTarget": 0 },
  "cache": { "implementation": "in-memory", "hits": 1, "misses": 5, "entries": 5, "evictions": 0, "hitRate": 0.167 }
}
```

**Alpha scope:** counters live in process memory and are read back through this
endpoint. A production deployment exports them to a monitoring system.

---

## GET /api/v1/health

```json
{
  "status": "healthy",
  "timestamp": "2026-08-27T20:30:00Z",
  "version": "0.1.0-alpha",
  "instanceId": "vm-e175bb61",
  "dependencies": {
    "database": "ok",
    "database_engine": "postgresql",
    "ai_provider": "ok",
    "ai_provider_name": "mock",
    "cache": "ok",
    "cache_implementation": "in-memory"
  }
}
```

`instanceId` identifies the application instance behind the load balancer.

`status` is `healthy`, `degraded` (a dependency is impaired but the platform
still answers and escalates) or `unavailable` (returned with **503**). The
endpoint exposes no customer data.

`dependencies` is an open map of diagnostic values, not a fixed contract.
`database_engine` names the live engine (`postgresql`, or `sqlite` when the
launcher fell back to a local file) and `ai_provider_name` names the selected
provider, so a demonstration can state exactly what is running.

---

## Error contract

Every failure uses the same shape:

```json
{
  "error": {
    "code": "INVALID_MESSAGE",
    "message": "Message must contain between 1 and 2000 characters.",
    "requestId": "6f14c243-51d6-4a98-a3fb-7de24973a63f"
  }
}
```

| HTTP | Condition | Example codes |
| --- | --- | --- |
| 400 | Malformed request or invalid syntax | `INVALID_IDENTIFIER`, `BAD_REQUEST` |
| 401 | Authentication missing, expired or invalid | `UNAUTHORIZED` |
| 403 | Authenticated user lacks permission | `FORBIDDEN` |
| 404 | Resource not found | `NOT_FOUND` (unknown route), `CONVERSATION_NOT_FOUND`, `CASE_NOT_FOUND`, `MESSAGE_NOT_FOUND`, `RECOMMENDATION_NOT_FOUND`, `ARTICLE_NOT_FOUND` |
| 405 | Method not allowed on this route | `METHOD_NOT_ALLOWED` |
| 409 | Conflicting conversation, case or review state | `CONFLICT`, `ESCALATION_ALREADY_ACTIVE`, `CONVERSATION_CLOSED`, `CASE_ALREADY_CLOSED`, `CASE_NOT_OPEN`, `CASE_ALREADY_ASSIGNED`, `FEEDBACK_ALREADY_RECORDED`, `RECOMMENDATION_ALREADY_REVIEWED` |
| 413 | Payload exceeds the permitted size | `PAYLOAD_TOO_LARGE` |
| 422 | Valid syntax, failed validation | `INVALID_REQUEST` (schema), `UNPROCESSABLE_REQUEST`, `INVALID_MESSAGE`, `INVALID_REPLY`, `INVALID_COMMENT`, `INVALID_REVIEW_DECISION` |
| 429 | Rate limit exceeded | `RATE_LIMIT_EXCEEDED` |
| 500 | Unexpected server fault; details are logged, never returned | `INTERNAL_ERROR` |
| 502 | Upstream returned an invalid response | `UPSTREAM_INVALID_RESPONSE` |
| 503 | Required dependency unavailable | `DEPENDENCY_UNAVAILABLE` |
| 504 | Upstream exceeded the configured timeout | `UPSTREAM_TIMEOUT` |

Provider error text is never returned to the customer. A failed AI call
produces a safe fallback message and an `AI_SERVICE_FAILURE` escalation, not a
5xx.
