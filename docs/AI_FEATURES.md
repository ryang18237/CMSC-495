# AI Features

**Owner:** Benjamin Madden (Integration Lead)

SkillBridge AI has two AI features, and lets the member choose which model
answers. They solve different problems and fail in
different ways, so they are built differently on purpose.

| | Conversational assistant | Pathway recommender |
| --- | --- | --- |
| What the member sees | Answers to free-text questions in the chat | "Recommended next steps" panel beside the chat |
| Technique | Large language model behind a provider interface | Content-based filtering: TF-IDF vectors and cosine similarity |
| Needs an API key | For Claude or ChatGPT; a record-aware demo assistant answers without one | No |
| Deterministic | No | Yes — same record, same list |
| When it fails | Escalates to a counsellor with `AI_SERVICE_FAILURE` | Falls back to general starting points |
| Code | `app/modules/ai_integration/service.py`, `providers/` | `app/modules/ai_integration/recommender.py`, `data/pathways.json` |
| Endpoint | `POST /api/v1/conversations/{id}/messages` | `GET /api/v1/pathways/recommended` |

Both live inside the AI Integration Module and obey its boundary: neither
imports the database, the models or another component. Member data reaches
them only as plain values handed over by the caller, after the Customer Data
Adapter has applied its per-inquiry permission list.

---

## 1. Conversational assistant

### How a turn reaches the model

1. Conversation Management classifies the question (`CREDENTIAL`, `EDUCATION`,
   `CAREER`, `TRANSITION`, `GENERAL`).
2. The Customer Data Adapter returns only the fields that inquiry type may
   see. A question about internship timing gets the separation date; it does
   not get the training list.
3. `AIIntegrationService.build_prompt()` assembles a provider-neutral prompt:
   system instruction, the permitted facts, up to two knowledge base
   excerpts, and the last six turns.
4. The selected provider returns text, or raises `AIProviderError`.
5. Response Validation checks the text before the member sees it — no claims
   of having enrolled or applied anyone, no guarantees of jobs, places or
   funding.

### What leaves the platform

Exactly four things, and nothing else — the request body is asserted by a test
to contain only `model`, `max_tokens`, `system` and `messages`:

1. The system instruction (how to answer, what not to claim, when to decline).
2. The account facts the inquiry type is permitted to see — for example a
   `CREDENTIAL` question sends specialty, completed training and credentials
   held, and never the branch, pay grade or separation date.
3. Up to two knowledge base excerpts, each cut to 700 characters.
4. The last six turns of this conversation and the new message.

No member name, email, member number or identifier is ever included.

### Providers and the member's choice

Three providers sit behind the same `AIProvider` interface. Everything that
keeps the assistant safe — minimised prompts, the retry budget, response
validation, the handover to a counsellor — lives in `AIIntegrationService`, so
it applies identically whichever one answers.

| Provider id | Member sees | Needs | Endpoint called |
| --- | --- | --- | --- |
| `anthropic` | Claude | `ANTHROPIC_API_KEY` | Anthropic Messages API |
| `openai` | ChatGPT | `OPENAI_API_KEY` | OpenAI Chat Completions |
| `mock` | Demo assistant (no AI key) | nothing | none — runs in process |

`GET /api/v1/ai/providers` lists only the providers this server has a key for,
plus the demo assistant. When more than one is available, the chat shows a
**Model** picker and sends the chosen id with each message; the reply says
which one answered. A provider without a key can never be selected — the API
refuses it with `422 AI_PROVIDER_UNAVAILABLE` — and **no key ever leaves the
server**: the browser only ever sees a name and a model id.

`AI_PROVIDER` sets the default, used when a message names none and when it has
a key; otherwise the default is the demo assistant.

### Getting a key

Each team member uses **their own** key, in **their own** `backend/.env`,
which git ignores. Never share a key in the repository, a chat or a commit.

**Claude (Anthropic)**

1. Sign in at <https://console.anthropic.com>.
2. Add credits under **Billing** — the API is pay-as-you-go and separate from
   a Claude.ai subscription.
3. **API Keys → Create Key**. Copy it once; it is not shown again.
4. Optional but recommended: set a monthly spend limit.

**ChatGPT (OpenAI)**

1. Sign in at <https://platform.openai.com>.
2. Add a payment method under **Billing**. A ChatGPT Plus subscription does
   **not** include API usage; the two are billed separately.
3. **API keys → Create new secret key**. Copy it once.
4. Optional but recommended: set a usage limit for the project.

Then, in `backend/.env`:

```bash
# backend/.env -- git-ignored, never committed
AI_PROVIDER=anthropic                       # the default model
ANTHROPIC_API_KEY=sk-ant-...                # your own key, if you have one
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...                       # your own key, if you have one
OPENAI_MODEL=gpt-6-luna
```

Restart `python run.py`. `/api/v1/health` shows the default provider, and the
chat shows the picker once two or more are available.

**Model versions.** Defaults are dated or specific model ids so a demonstration
is reproducible. Check the current model lists on each provider's site and set
`ANTHROPIC_MODEL` / `OPENAI_MODEL` if a default has been retired.

**If a key leaks,** revoke it in that console at once and create a new one.
Deleting the commit does not help — the key stays in git history. A key is
read at startup, so a new one takes effect after a restart.

### The demo assistant

With no key the demo assistant answers — and it answers from the member's own
record, not from canned text. It reads the same minimised facts a real model
would receive (training completed, credentials held, specialty), asks the
pathway recommender for the closest next steps, and builds the reply from
them. Two members get different answers, and one member gets a different
answer after adding something to **My record**:

> Looking at your record, you already hold CompTIA A+ and CompTIA Security+
> and you have completed Basic Leader Course, Network Administration Course
> and Information Assurance Fundamentals. The closest next steps from that are
> CompTIA Network+, the natural step after CompTIA A+; and CompTIA
> Cybersecurity Analyst (CySA+), the natural step after CompTIA Security+. …

It is still deterministic, so tests and CI can rely on it.

### Failure handling

Every provider fault is raised as `AIProviderError` with a `retryable` flag.
The provider never retries itself — `AIIntegrationService` owns one bounded
retry loop, so a retry cannot multiply.

| Setting | Default | Meaning |
| --- | --- | --- |
| `AI_TIMEOUT_SECONDS` | 8 | Longest a single attempt may take |
| `AI_MAX_RETRIES` | 1 | Retries after the first attempt, for retryable failures only |
| `AI_RETRY_BUDGET_SECONDS` | 5 | No retry is *started* once the turn has used this much time |

The worst case is therefore about 5 + 8 ≈ 13 seconds before a member is handed
to a person. The Alpha defaults — 20-second timeout, two retries — allowed
about 61 seconds, against a five-second response target; the peer review
rated that High and these values resolve it.

| Situation | Retryable | Member sees |
| --- | --- | --- |
| Timeout, transport error, 429, 5xx, non-JSON or empty body | Yes | A fallback message and a handover, if retries run out |
| 401/403 (bad key), 400, 404, 413 | No | Handover immediately |
| Response cut off at the token limit | — | Returned flagged as truncated; Response Validation rejects it as `VALIDATION_FAILURE` and hands over — never half a sentence |
| Model declines (`UNSUPPORTED_TOPIC`, however it is decorated) | — | `UNSUPPORTED_TOPIC` escalation |

Provider error text never reaches the member. Prompt and response bodies are
never logged; errors record only the failure class and HTTP status, and the
stored `error_detail` is capped at 200 characters so a future provider that
quoted content in an error still could not write member data to the log. A test
drives a rejected-key call and asserts the key appears in no log line, error or
member-facing text.

Truncation used to be raised as a provider failure, which escalated as
`AI_SERVICE_FAILURE` and pointed the analytics worker at provider timeouts
that were never the cause. It is now a validation failure, which is what it
is. `MAX_TOKENS` (1,024) and `max_response_length` (4,000 characters) are
coupled, and both sites say so.

One HTTP connection pool is shared across requests. It is created under a lock,
because the sync routes run on a thread pool and two first requests arriving
together would otherwise each build a pool and leak one. It is closed when the
application shuts down.

---

## 2. Pathway recommender

### Why a second, non-LLM feature

The assistant only works properly with a key, and the people grading this
project will not have one. The recommender gives every member a real,
personalised AI result with nothing to configure, and it keeps working when
the model provider is down. It is also the direct expression of what the
platform is for: insight based on what a member has already done.

### Method

1. **Catalog.** `data/pathways.json` holds 23 illustrative civilian pathways —
   certifications, licenses, programs, degrees and an apprenticeship — each
   with a summary, descriptive keywords, aliases, and the pathways it
   `follows` on from.
2. **Text to tokens.** Lower-cased words minus generic course vocabulary
   ("course", "school", "fundamentals", vendor names), a two-rule stemmer
   (`networks`, `networking` → `network`), plus adjacent word pairs so
   "information assurance" counts as a phrase.
3. **Vectors.** Each pathway and the member's record become sublinear TF-IDF
   vectors over one vocabulary, L2-normalised. Keywords count double.
4. **Score.** Cosine similarity, plus **0.10** when the member already holds a
   credential the pathway follows on from. Anything under **0.08** is dropped
   as coincidence.
5. **Filter.** Credentials already held — matched by title or alias — are never
   suggested.
6. **Explain.** Each suggestion names why: the held credential it follows
   (`NEXT_STEP`), or the single item on the record it overlaps most with
   (`BUILDS_ON`), plus up to three shared terms in the member's own wording.
7. **Cold start.** A record with nothing to match gets broadly useful starting
   points, labelled `GENERAL` so the interface can say so.

### Evaluation

Measured by `backend/tests/test_recommender.py` against seven hand-labelled
service records (IT specialist, hospital corpsman, motor transport operator,
electronics technician, cyber operations, combat medic, NCO leader). A
suggestion counts as relevant if a counsellor would expect it near the top.

| k | Hit rate @k | Precision @k |
| --- | --- | --- |
| 1 | 0.86 | 0.86 |
| 3 | **1.00** | **0.76** |
| 5 | 1.00 | 0.51 |

Every labelled record gets at least one relevant pathway in its top three. The
tests fail the build if hit rate @3 drops below 1.00 or precision @3 below
0.60, so a catalog edit that makes suggestions worse cannot merge quietly.

Tuning decisions were made by reading these rankings, not by guessing:

- The minimum score was raised from 0.05 to 0.08 after a motor transport
  operator was offered a radio license on the single shared word "operator".
- Vendor names were added to the stopword list after "CompTIA" appeared as a
  matched term — sharing a vendor says nothing about sharing a subject.

### Limits

- The catalog is small and hand-written. Coverage outside the fields above is
  thin, and a record in an uncovered field falls back to starting points.
- Similarity is lexical. "Corpsman" and "medic" only meet because the catalog
  keywords list both; the recommender does not know they are related.
- No learning from outcomes yet. The feedback outbox records chat ratings but
  not whether a member pursued a suggestion.

---

## Peer review — what changed

Items from `docs/PEER_REVIEW_AI_Integration_Module.md` and the Unit 5
refinement report, and where each stands.

| Finding | Severity | Resolution |
| --- | --- | --- |
| Worst-case turn ≈ 61 s against a 5 s target | High | Timeout 8 s, one retry, 5 s retry budget; worst case ≈ 13 s |
| `error_detail` could carry content into logs | Medium | Capped at 200 characters; invariant documented on the field |
| Truncation reported as `AI_SERVICE_FAILURE` | Medium | Now `VALIDATION_FAILURE`, with no change to the approved enumeration |
| Handoff doc described a stub | Medium | Replaced by this document |
| What reaches the provider not stated in one place | Medium | "What leaves the platform", above |
| Model alias, key rotation, rate limits undocumented | Medium / Low | Documented above |
| No test that the key never reaches a log | Low | Added |
| `MAX_TOKENS` silently coupled to `max_response_length` | Low | Commented at both sites |
| Shared pool never closed | Low | Closed on shutdown |
| Shared pool created without a lock | Refinement report | Lock added; a 20-thread test fails without it |
| Synchronous provider call holds a worker thread | Medium | **Open.** Needs async routes across the API layer; recorded as architectural debt |

---

## Tests

| File | Covers |
| --- | --- |
| `tests/test_ai_provider.py` | Request shape, status mapping, retry flags, retry budget, parsing, truncation as a validation failure, decline-marker normalisation, capped error detail, key never logged, pool closed on shutdown |
| `tests/test_modules.py` | Retry policy, fallback and escalation on provider failure |
| `tests/test_model_choice.py` | ChatGPT provider wire format, status mapping, refusal and truncation; which providers are offered; the member's choice honoured and unconfigured choices refused; keys never exposed; demo answers built from the member's record |
| `tests/test_recommender.py` | Tokenising, ranking, held-credential filtering, explanations, cold start, catalog integrity, offline evaluation, the HTTP route, and the shared-pool lock under 20 concurrent threads |
| `frontend/src/components/PathwayRecommendations.test.jsx` | Reasons and strengths rendered, general fallback, error code shown |
