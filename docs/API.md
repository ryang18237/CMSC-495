# API Reference — v1

Base URL (local): `http://127.0.0.1:8000`

Customer identity is always derived from the verified access token. The API
never trusts a client-supplied customer identifier when deciding access to
customer information.

All requests and responses are JSON. Every response carries an `X-Request-ID`
header; the same value appears as `requestId` in any error body.

---

## Authentication

`POST /api/v1/auth/login` → **200**

```json
{ "email": "customer@example.com", "password": "DemoPassw0rd!" }
```

```json
{
  "accessToken": "eyJhbGciOi...",
  "tokenType": "Bearer",
  "expiresIn": 3600,
  "role": "CUSTOMER",
  "displayName": "Alex Customer"
}
```

Send the token on every other call: `Authorization: Bearer <accessToken>`.

---

## Endpoint summary

| Method | Endpoint | Purpose | Success |
| --- | --- | --- | --- |
| POST | `/api/v1/conversations` | Create a conversation | 201 |
| POST | `/api/v1/conversations/{conversationId}/messages` | Submit a customer message | 200 |
| GET | `/api/v1/conversations/{conversationId}` | Retrieve authorized history | 200 |
| POST | `/api/v1/conversations/{conversationId}/escalate` | Request human escalation | 201 |
| POST | `/api/v1/conversations/{conversationId}/feedback` | Submit feedback | 201 |
| GET | `/api/v1/agent/cases` | List open cases (agent only) | 200 |
| GET | `/api/v1/agent/cases/{caseId}` | Retrieve a case (agent only) | 200 |
| PATCH | `/api/v1/agent/cases/{caseId}` | Update case status (agent only) | 200 |
| GET | `/api/v1/health` | Application health | 200 |

`GET /api/v1/agent/cases` and `PATCH /api/v1/agent/cases/{caseId}` are Alpha
additions supporting the agent dashboard; the seven endpoints from the System
Design Specification are unchanged.

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
{ "message": "Why was I charged twice for my order?" }
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
  "response": "I can help you review that charge.",
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
| Customer asks for a person | `CUSTOMER_REQUEST` | Before the model is called |
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
      "content": "I can help you review that charge.",
      "status": "ANSWERED",
      "escalationReason": null,
      "sources": ["Duplicate charges and pending authorisations"],
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
  "queue": "CUSTOMER_SUPPORT"
}
```

`SECURITY_CONCERN` routes to the `TRUST_AND_SAFETY` queue; every other reason
routes to `CUSTOMER_SUPPORT`.

A second escalation while one is still active returns **409**
`ESCALATION_ALREADY_ACTIVE` rather than creating a duplicate case.

---

## POST /api/v1/conversations/{conversationId}/feedback

```json
{
  "messageId": "179abb70-e469-44f8-aaf4-338288805024",
  "rating": "HELPFUL",
  "comment": "The answer resolved my issue."
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

## GET /api/v1/health

```json
{
  "status": "healthy",
  "timestamp": "2026-08-27T20:30:00Z",
  "version": "0.1.0-alpha",
  "dependencies": { "database": "ok", "ai_provider": "ok", "ai_provider_name": "mock" }
}
```

`status` is `healthy`, `degraded` (a dependency is impaired but the platform
still answers and escalates) or `unavailable` (returned with **503**). The
endpoint exposes no customer data.

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
| 400 | Malformed request or invalid syntax | `INVALID_IDENTIFIER` |
| 401 | Authentication missing, expired or invalid | `UNAUTHORIZED` |
| 403 | Authenticated user lacks permission | `FORBIDDEN` |
| 404 | Resource not found | `CONVERSATION_NOT_FOUND`, `CASE_NOT_FOUND`, `MESSAGE_NOT_FOUND` |
| 409 | Conflicting conversation or escalation state | `ESCALATION_ALREADY_ACTIVE`, `CONVERSATION_CLOSED` |
| 413 | Payload exceeds the permitted size | `PAYLOAD_TOO_LARGE` |
| 422 | Valid syntax, failed business validation | `INVALID_MESSAGE`, `INVALID_COMMENT` |
| 429 | Rate limit exceeded | `RATE_LIMIT_EXCEEDED` |
| 502 | Upstream returned an invalid response | `UPSTREAM_INVALID_RESPONSE` |
| 503 | Required dependency unavailable | `DEPENDENCY_UNAVAILABLE` |
| 504 | Upstream exceeded the configured timeout | `UPSTREAM_TIMEOUT` |

Provider error text is never returned to the customer. A failed AI call
produces a safe fallback message and an `AI_SERVICE_FAILURE` escalation, not a
5xx.
