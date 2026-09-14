# Peer Review — AI Integration Module

**Reviewer:** Ryan Gant (Interface Designer)
**Author under review:** Benjamin Madden (Integration Lead)
**Module:** `backend/app/modules/ai_integration/` — `service.py`, `contracts.py`,
`providers/base.py`, `providers/mock.py`, `providers/anthropic_provider.py`,
`tests/test_ai_provider.py`
**Branch reviewed:** `feature/ai-provider-anthropic`
**Date:** _[fill in when you submit]_

---

## Scope and method

I read the module against the interface contracts I own, ran the full suite
(104 passed), `ruff check`, `ruff format --check` and `mypy app` locally, and
traced one customer turn end to end through `ConversationService.process_message`
with the provider swapped in. I focused on the five required areas: code
quality, security, performance, integration compatibility, and documentation of
the AI model implementation.

## Summary

The module is well isolated and ready to merge after the items marked **High**
are addressed. The boundary is the strongest part of the work: no module
outside `ai_integration/` imports a provider SDK or constructs a prompt, and
selecting a provider is configuration rather than code. Two defects the author
found and fixed while implementing — truncated responses reaching the customer,
and the decline marker being matched by exact equality — were real and would
have surfaced during the demonstration.

My concerns are concentrated in one place: the retry and timeout policy
conflicts with our stated performance requirement, and the failure taxonomy
loses information that the Learning Analytics Worker depends on.

---

## 1. Code quality and readability

**Strengths.** `generate()` reads as four named steps — build, post, check
status, parse — each small enough to hold in your head. The `retryable` flag on
`AIProviderError` is a good abstraction: it lets the provider classify a failure
without knowing anything about the retry policy that consumes the
classification. Comments explain *why* rather than restating the code; the
note on why the HTTP client lives at module level rather than on the instance
is exactly the kind of thing that stops a future maintainer from "simplifying"
it into a socket leak.

**Minor — optional.** `_raise_for_status()` is a chain of six `if` statements.
A module-level mapping of status code to `(message, retryable)` with a default
would be shorter to read and would put the whole policy in one visible table.
This is a preference, not a defect; take it or leave it.

**Minor.** `_MARKER_TRIM` handles the common dressings of the decline marker.
Worth one line in the docstring stating what it deliberately does *not* catch —
a marker embedded in a longer reply is treated as a real answer, which is the
safe default but is not obvious from the code.

## 2. Security vulnerabilities and risks

**Strengths.** No prompt or response body is logged anywhere in the module.
Provider error bodies are never read, so a provider that echoes request content
in an error cannot leak it into our logs — and there is a test asserting a
provider's own error text never appears in the raised message. The request body
is asserted to contain exactly four keys, which locks down what leaves the
platform. `health()` performs no network call and reveals only whether a key is
configured.

**Medium — recommend fixing.** `AIIntegrationService.handle_provider_failure()`
stores the provider's error text in `AIResult.error_detail`, and
`ConversationService` logs it. Nothing this provider raises contains customer
data, but that is a property of this one implementation rather than something
the type enforces. A future provider that includes a response excerpt in its
error message would silently write customer content to the application log.
Recommend truncating `error_detail` to a fixed length and documenting the
invariant on the field: *provider error class and status only, never content*.

**Low — recommend adding.** No test asserts that the API key never appears in a
log record or exception message. A `caplog` test that drives a failed call and
asserts the key string is absent would make that guarantee enforced rather than
assumed. This matters more than usual for us because the repository is shared.

**Low — documentation, not code.** `get_settings()` is `lru_cache`d and the key
is read in `__init__`, so rotating `ANTHROPIC_API_KEY` requires a process
restart. That is a reasonable choice; it just needs to be written down so
nobody assumes a rotated key takes effect immediately.

## 3. Performance

**High — please address before merge.** `AI_TIMEOUT_SECONDS` defaults to 20 and
`AI_MAX_RETRIES` to 2, so a worst-case turn is roughly 20 + 0.2 + 20 + 0.4 + 20
≈ **61 seconds** against our stated requirement that chatbot responses complete
within approximately five seconds. The customer waits the whole time before
receiving the fallback. I suggest a timeout of about 8 seconds with 1 retry,
plus a total-budget check in `generate_response()` that stops retrying once the
elapsed time would exceed the target — but the numbers are yours to set, since
you own the module and know the provider's latency profile better than I do.
The `_log_latency` warning already fires above 5 seconds, so we will see this
in the logs the moment a real provider is enabled.

**Medium.** `time.sleep()` in the retry loop runs inside FastAPI's threadpool
because the endpoints are synchronous. It does not block the event loop, but it
does hold a threadpool worker for the duration. The default pool is 40 workers;
under the concurrency we claim to target, retrying calls would exhaust it and
queue unrelated requests. Converting the provider and the service to `async`
with `httpx.AsyncClient` is the real fix. That is larger than this pull request
and touches my routers, so let us schedule it rather than rush it — but it
should be recorded as a known limitation now.

**Strength.** Sharing one connection pool across turns instead of constructing
a client per provider instance is the right call and is well justified in the
comment. Reusing keep-alive connections also removes a TLS handshake from every
customer message, which is real latency, not theoretical.

## 4. Integration compatibility

**Medium — this one has a downstream effect.** A response truncated at the
token limit is raised as a non-retryable `AIProviderError`, which
`ResponseValidationService` maps to `AI_SERVICE_FAILURE`. Rejecting the
truncated answer is correct, but the reason is wrong: the AI service worked
fine. The consequence is not cosmetic. `LearningAnalyticsWorker.produce_review_recommendations()`
branches on `ESCALATION_AI_SERVICE_FAILURE` and emits *"Review provider timeout
and retry configuration"* — so a recurring truncation problem would send whoever
reviews those recommendations to inspect timeouts that are not the cause. Since
the five escalation reasons are fixed in the interface contract I own, this is a
joint change. My preference is a sixth reason; if the team would rather not
alter the approved enumeration for the Alpha, mapping truncation to
`VALIDATION_FAILURE` is closer to the truth than the current behaviour.

**Low.** `MAX_TOKENS = 1024` caps a response at roughly 4,000 characters, which
happens to match `max_response_length` in `config.py`. The two values are
coupled but nothing documents or enforces it, so raising one without the other
would produce responses that the validator silently rejects. Either derive
`MAX_TOKENS` from the configured limit or add a comment at both sites naming the
relationship.

**Low.** `_shared_client` is never closed. A FastAPI shutdown handler calling
`reset_shared_client()` would release the pool cleanly. That handler lives in
`main.py`, which is mine — tell me and I will add it, or include it in your
branch, whichever you prefer.

**Strength.** `MockAIProvider` implements the identical interface, which is what
lets CI exercise the whole conversation path with no key and no network. Every
new test in `test_ai_provider.py` uses `httpx.MockTransport` rather than
patching internals, so the tests verify the real request we send rather than a
mock of our own assumptions. That is the right level to test at, and it means
the tests will survive a refactor of the module's internals.

## 5. Documentation of the AI model implementation

**Medium.** `docs/AI_INTEGRATION_HANDOFF.md` still describes the provider as a
stub with three outstanding TODO blocks. Once this branch merges that document
is actively misleading — it is the first thing a new reader opens. It should be
rewritten as a configuration and operations reference, or deleted with its
useful content folded into the module docstring.

**Medium.** The module docstring covers the wire format and the failure
taxonomy well, but three things a reader will need are missing:

- **Model version policy.** `claude-sonnet-4-5` is an alias that moves. For a
  reproducible demonstration we should pin a dated model string and record
  which one the Alpha was demonstrated against.
- **What data actually reaches the provider.** The Design Specification claims
  data sent to the provider is minimised. That claim is implemented across the
  Customer Data Adapter's `_INQUIRY_FIELDS` table and
  `AIIntegrationService.build_prompt()`, but it is not stated anywhere as a
  single explicit list. A short "Data sent to the provider" section — the
  system instruction, the permitted account facts for the inquiry type, up to
  two knowledge-base excerpts, and the last six turns — would let a reader
  verify the claim without reading three files.
- **Cost and rate limits.** Nothing records what a provider 429 means for us in
  practice, or what the account's limits are.

**Strength.** The inline comments explaining the two defects found during
implementation, including why a truncated response passes validation, are the
most useful documentation in the module. Keep that style.

---

## Requested response

Please reply on the pull request addressing, at minimum: the retry and timeout
budget (item 3, High), the truncation reason mapping (item 4, Medium), and the
stale handoff document (item 5, Medium). The threadpool item can be recorded as
a known limitation rather than fixed now. Everything marked Low is your call —
tell me which you are declining and why, and I will not raise them again.

I will also take the two items that fall on my side of the boundary: the
shutdown handler in `main.py`, and the escalation-reason decision, which I want
your recommendation on before I change the contract.
