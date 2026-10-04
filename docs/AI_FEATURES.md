# AI Features

**Owner:** Benjamin Madden (Integration Lead)

SkillBridge AI has two AI features. Both work with no API key, no account and
nothing to configure — Claude and ChatGPT are optional upgrades whoever runs
the server can add. The two features solve different problems and fail in
different ways, so they are built differently on purpose.

| | Conversational assistant | Pathway recommender |
| --- | --- | --- |
| What the member sees | Answers to free-text questions in the chat | "Recommended next steps" panel beside the chat |
| Technique | A provider interface: a rule-based advisor in process, or a managed language model | Content-based filtering: TF-IDF vectors and cosine similarity |
| Needs an API key | No — the built-in advisor answers. Claude and ChatGPT are optional | No |
| Deterministic | Yes on the built-in advisor, no on a managed model | Yes — same profile, same list |
| When it fails | Escalates to a counsellor with `AI_SERVICE_FAILURE` | Falls back to general starting points |
| Code | `providers/builtin.py`, `providers/anthropic_provider.py`, `providers/openai_provider.py` | `recommender.py` |
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

### Three providers, no key required

The platform works the moment it is installed. Nobody signs up for anything,
and **no member is ever asked for an API key** — there is nowhere in the
interface to enter one, by design.

| Provider id | Member sees | Needs | Runs |
| --- | --- | --- | --- |
| `builtin` | Built-in advisor | nothing | in process, offline |
| `anthropic` | Claude | `ANTHROPIC_API_KEY` | Anthropic Messages API |
| `openai` | ChatGPT | `OPENAI_API_KEY` | OpenAI Chat Completions |

`builtin` is the default and is always available. Claude and ChatGPT are
upgrades that **whoever runs the server** configures once, in
`backend/.env`; every member of that server then benefits without touching a
key. `GET /api/v1/ai/providers` lists only what the server can actually
reach, the chat shows a **Model** picker when there is more than one, and each
message carries a provider **id** — never a credential. A provider without a
key can never be selected: the API refuses it with
`422 AI_PROVIDER_UNAVAILABLE`.

### The built-in advisor

Not a placeholder. It reads the member's profile — credentials, training,
education, experience, all minimised by the Customer Data Adapter exactly as
they would be for a managed model — and composes an answer, asking the pathway
recommender which next steps actually follow. Two members get different
answers, and the same member gets a different answer after adding a degree or
a job:

> Looking at your profile, you already hold CompTIA A+ and you have studied
> Associate of Applied Science in Network Systems (Central Texas College). The
> closest next steps from that are CompTIA Network+, the natural step after
> CompTIA A+; and Cisco Certified Network Associate (CCNA), which builds on
> Network Administration Course. …

**What it does well.** Personal, instant, free, deterministic, and nothing
about the member leaves the process. It answers the questions the platform
exists for: what to do next, degree or credential, how to describe this on a
resume, what is on my profile.

**What it does not do.** It does not understand free text the way a language
model does. It routes on topic and declines anything it does not recognise,
which becomes an `UNSUPPORTED_TOPIC` handover to a counsellor — the same safe
ending a managed model gets when it is out of its depth. A member asking
something unusual reaches a person instead of getting a guess.

Being deterministic is also what lets CI exercise the whole conversation path
on every push with no key and no spend.

### Adding Claude or ChatGPT

Optional. Do this when you want free-text understanding beyond the advisor's
topics. It is a **server** setting; members see the new option appear.

**Claude (Anthropic)**

1. Sign in at <https://console.anthropic.com>.
2. Add credits under **Billing**. API usage is pay-as-you-go and separate
   from a Claude.ai subscription.
3. **API Keys → Create Key**. Copy it once; it is not shown again.
4. Set a monthly spend limit while you are developing.

**ChatGPT (OpenAI)**

1. Sign in at <https://platform.openai.com>.
2. Add a payment method under **Billing**. A ChatGPT Plus subscription does
   **not** include API usage; the two are billed separately.
3. **API keys → Create new secret key**. Copy it once.
4. Set a usage limit for the project.

Then, in `backend/.env` on the machine running the server:

```bash
# backend/.env -- git-ignored, never committed
AI_PROVIDER=anthropic                       # or openai, or builtin
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-6-luna
```

Restart `python run.py`. `/api/v1/health` reports the default provider, and
the picker appears once two or more are available.

### Which to run, and when

| Situation | Recommendation |
| --- | --- |
| Demonstration, grading, a teammate cloning the repo | **Built-in advisor.** Nothing to configure, nothing to spend, identical for everyone. |
| One person showing real Claude or ChatGPT answers | That person puts **their own** key in their own `.env` and runs the demo on their machine. Nobody else needs a copy. |
| A deployed instance for real members | One key held by the deployment, in the host's secret store — never in the repository. Members still never see it. |
| CI | **Built-in advisor**, always. No secret to leak, repeatable results, no bill. |

Never share one key between people by committing it: a private repository is
private from the public, not between collaborators, and a committed key stays
in git history after it is deleted. Each person uses their own.

**Model versions.** Defaults are dated or specific ids so a demonstration is
reproducible. Check each provider's current model list and update
`ANTHROPIC_MODEL` / `OPENAI_MODEL` if a default is retired.

**If a key leaks,** revoke it in that console immediately and create a new
one. A key is read at startup, so a replacement takes effect after a restart.

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

Ranking is not a language problem. "What should I do next?" is a question
about how close each pathway is to what a member has already finished, and
that is answered better — and provably, and in milliseconds — by comparing
the two directly than by asking a model to guess. It also keeps working when
a model provider is down, and it is the engine the built-in advisor uses to
answer without a key at all. It is the direct expression of what the platform
is for: insight based on what a member has already done.

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
