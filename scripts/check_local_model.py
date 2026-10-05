#!/usr/bin/env python3
"""Ask the local model one question and report exactly what came back.

    python scripts/check_local_model.py

When the assistant says "Assistant service unavailable", the cause is one of
four things and the platform cannot tell you which without this: the daemon is
not running, the model is not pulled, the request is refused, or generation
takes longer than the turn allows. This runs the same request the platform
runs, with the same settings, and prints the status, the timing and the body
instead of turning them into a fallback message.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.modules.ai_integration.providers.ollama_provider import (  # noqa: E402
    PLACEHOLDER_KEY,
    OllamaProvider,
    installed_models,
)
from app.modules.ai_integration.providers.openai_provider import MAX_TOKENS  # noqa: E402

QUESTION = "Which certification should I work toward next?"
SYSTEM = (
    "You are a career adviser for military members and veterans. "
    "The member holds CompTIA A+ and has completed a Network Administration Course. "
    "Answer in one short paragraph."
)


def main() -> int:
    settings = get_settings()
    base = settings.ollama_base_url.rstrip("/")
    model = settings.ollama_model
    timeout = settings.ollama_timeout_seconds

    print("Settings the platform will use")
    print(f"  base url   {base}")
    print(f"  model      {model}")
    print(f"  timeout    {timeout:.0f}s")
    print(f"  reply cap  {MAX_TOKENS} tokens, sent as {OllamaProvider.token_limit_field!r}")
    print()

    print(f"1. Is the daemon answering?  GET {base}/v1/models")
    try:
        listing = httpx.get(f"{base}/v1/models", timeout=5.0)
    except httpx.HTTPError as error:
        print(f"   NO -- {type(error).__name__}: {error}")
        print("   Ollama is not running. Start it, or run `python run.py` and let it start it.")
        return 1
    print(f"   yes, HTTP {listing.status_code}")

    names = installed_models(listing.json())
    print(f"2. Is {model} pulled?  installed: {', '.join(sorted(names)) or '(none)'}")
    if model not in names:
        print(f"   NO -- run:  ollama pull {model}")
        return 1
    print("   yes")

    print(f"3. Asking it a real question (up to {timeout:.0f}s)...")
    body = {
        "model": model,
        OllamaProvider.token_limit_field: MAX_TOKENS,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": QUESTION},
        ],
    }
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {PLACEHOLDER_KEY}"},
            json=body,
            timeout=timeout,
        )
    except httpx.TimeoutException:
        waited = time.monotonic() - started
        print(f"   TIMED OUT after {waited:.0f}s.")
        print("   The daemon is up and the model is pulled, so this is speed, not setup.")
        print("   Try a smaller model:  ollama pull llama3.2:1b")
        print("   then set OLLAMA_MODEL=llama3.2:1b before starting run.py")
        return 1
    except httpx.HTTPError as error:
        print(f"   FAILED -- {type(error).__name__}: {error}")
        return 1

    waited = time.monotonic() - started
    print(f"   HTTP {response.status_code} in {waited:.1f}s")
    if response.status_code >= 400:
        print(f"   body: {response.text[:500]}")
        return 1

    payload = response.json()
    choice = (payload.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = (message.get("content") or "").strip()
    usage = payload.get("usage") or {}
    print(f"   finish_reason: {choice.get('finish_reason')}")
    print(f"   tokens out:    {usage.get('completion_tokens', '?')}")
    if not text:
        print("   content was EMPTY. Other keys on the message:")
        print(f"   {json.dumps({k: str(v)[:200] for k, v in message.items() if k != 'content'})}")
        return 1
    print()
    print("   The model answered:")
    print(f"   {text[:600]}")
    print()
    print("All four checks passed. The assistant should work in the app.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
