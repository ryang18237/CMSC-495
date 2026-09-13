# AI Integration — implementation brief

**Owner:** Benjamin Madden (Integration Lead)
**Status:** interface complete, provider implementation outstanding
**File to edit:** `backend/app/modules/ai_integration/providers/anthropic_provider.py`

Everything around the model call is already built and tested. Your work is one
class with three small steps. Nothing else in the repository needs to change.

---

## Why the Alpha ships with a mock

`MockAIProvider` implements the same interface and needs no API key and no
network access, so CI exercises the entire conversation path on every push
without a paid call. Selecting the real provider is configuration only:

```bash
AI_PROVIDER=anthropic        # in backend/.env, never committed
ANTHROPIC_API_KEY=sk-ant-... # your key, never committed
```

If the key is missing, `AnthropicProvider.health()` reports `unavailable`,
`/api/v1/health` reports `degraded`, and any call raises a non-retryable
`AIProviderError` that becomes an `AI_SERVICE_FAILURE` escalation. The platform
degrades; it does not break.

---

## What already exists

| Piece | Location | What it does for you |
| --- | --- | --- |
| `AIProvider` | `providers/base.py` | The interface: `generate(prompt) -> ProviderResponse` |
| `Prompt` | `contracts.py` | `system: str` and `messages: [{"role","content"}]` — already in Messages API shape |
| `ProviderResponse` | `contracts.py` | What you return: `text`, `model`, `stop_reason` |
| `AIProviderError` | `contracts.py` | What you raise, with `retryable=True/False` |
| `AIIntegrationService` | `service.py` | Builds the prompt, owns retries and backoff, converts failures to a safe fallback |
| `build_provider()` | `service.py` | Already registers your class for `AI_PROVIDER=anthropic` |
| `ResponseValidationService` | `../validation/service.py` | Checks your output before a customer sees it |

The system prompt (`SYSTEM_INSTRUCTION` in `service.py`) already tells the
model to stay inside the supplied material, never to claim it performed an
account action, never to repeat a password or card number, and to reply with
exactly `UNSUPPORTED_TOPIC` when it cannot help.

---

## Your three steps

Inside `AnthropicProvider.generate()`, replace the `NotImplementedError` with:

**1. Build the body**

```python
body = {
    "model": self._model,
    "max_tokens": MAX_TOKENS,
    "system": prompt.system,
    "messages": prompt.messages,
}
```

`prompt.messages` is already alternating user/assistant with the newest
customer turn last. No transformation needed.

**2. Send it, and map every transport failure to `AIProviderError`**

```
POST {base_url}/v1/messages
  x-api-key:         <key>
  anthropic-version: 2023-06-01
  content-type:      application/json
```

| Situation | Raise |
| --- | --- |
| `httpx.TimeoutException` | `AIProviderError(..., retryable=True)` |
| Other `httpx.HTTPError` | `AIProviderError(..., retryable=True)` |
| 401 / 403 | `AIProviderError(..., retryable=False)` |
| 400 | `AIProviderError(..., retryable=False)` |
| 429 or 5xx | `AIProviderError(..., retryable=True)` |

Do **not** retry inside this class. `AIIntegrationService` already retries
retryable failures with exponential backoff (`AI_MAX_RETRIES`, default 2) and
falls back safely when they are exhausted. Retrying here would multiply.

**3. Parse the body**

```python
payload = response.json()
blocks = [b for b in payload.get("content", []) if b.get("type") == "text"]
text = "".join(b.get("text", "") for b in blocks).strip()
if not text:
    raise AIProviderError("Provider returned an empty response.", retryable=True)
return ProviderResponse(
    text=text,
    model=payload.get("model", self._model),
    stop_reason=payload.get("stop_reason"),
)
```

Full commented scaffolding is already in the file — uncomment and adapt.

---

## Rules the implementation must respect

1. **Never leak provider internals to the customer.** Raise `AIProviderError`;
   the service puts the message in `error_detail` for server logs and returns a
   generic fallback to the customer. `test_provider_failure_falls_back_and_escalates`
   asserts this.
2. **Never log prompt or response bodies.** They may contain customer data, and
   the design requires data sent to the provider to be minimised.
3. **Never widen the prompt.** The Customer Data Adapter already decides which
   account fields an inquiry type is allowed to include. Do not add fields.
4. **Return `"UNSUPPORTED_TOPIC"`** as the entire text when the model declines,
   so the escalation path fires instead of a vague answer reaching a customer.
5. **Do not commit a key.** `backend/.env` is git-ignored. CI keeps
   `AI_PROVIDER=mock` regardless of secrets.

---

## Verifying

```bash
cd backend
source .venv/bin/activate

# 1. The suite must still pass with the mock (CI runs exactly this)
pytest -q

# 2. Provider-specific tests
pytest -q -k provider

# 3. Manual check against the real provider
cp .env.example .env     # set AI_PROVIDER=anthropic and ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

Then in the client, send:

| Message | Expected |
| --- | --- |
| `Why was I charged twice for my order?` | `ANSWERED`, grounded in the knowledge base |
| `What is the capital of France?` | `ESCALATED` / `UNSUPPORTED_TOPIC` |
| Any message with a deliberately wrong API key | `ESCALATED` / `AI_SERVICE_FAILURE`, safe fallback text |

Also confirm `ruff check .`, `ruff format --check .` and `mypy app` pass — CI
runs all three.

---

## Tests worth adding with your implementation

Put them in `backend/tests/test_ai_provider.py` and stub the HTTP layer so they
need no key and no network:

- a 200 with a normal `content` array parses into `ProviderResponse`
- a 200 with an empty `content` array raises a retryable `AIProviderError`
- 429 and 503 raise retryable errors; 401 and 400 raise non-retryable ones
- a timeout raises a retryable error
- `prompt.messages` is passed through unchanged in the request body

---

## Suggested commits

```
feat(ai): implement Anthropic Messages API request construction
feat(ai): map provider transport and status failures to AIProviderError
feat(ai): parse Messages API response into ProviderResponse
test(ai): cover provider success, empty body, and failure mapping
docs(ai): record provider configuration in the integration brief
```

Work on a branch (`feature/ai-provider-anthropic`), open a pull request, and
let CI run before merging.
