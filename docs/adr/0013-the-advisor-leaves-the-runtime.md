# 0013 — The built-in advisor is a test double, not a fallback

**Status:** Accepted
**Date:** Final release
**Deciders:** Ryan Gant, Ravonne Wade, Benjamin Madden

## Context

ADR 0009 made the platform usable with no API key by shipping a built-in
advisor that routes on topic keywords and composes an answer from templates.
ADR 0011 then made a local model the default. Both were kept available: the
advisor was listed in the member's model picker, and `auto` fell back to it
whenever Ollama was not reachable.

Keeping both turned out to cost more than it bought, in two ways that are
invisible from the outside.

A member choosing between "Built-in advisor" and "Local model" has no way to
know the first is a stand-in. It sits first in the list and answers instantly,
so it gets chosen — and its template text is then read as the product's
considered advice rather than as a placeholder.

Worse, the silent fallback. When Ollama was stopped or its model unpulled,
`auto` resolved to the advisor and the member got a fluent, confident
paragraph. Nothing in the reply said a language model had never been called.
The operator saw a working platform, the member saw canned advice about their
career, and the actual condition — a stopped daemon, fixable in under a minute
— was reported nowhere.

Deleting the advisor outright was considered and rejected. It is genuinely
good at one job: standing in for a language model in a test. It is
deterministic, instant, free, and needs no daemon, which is exactly what CI
needs and exactly what a hosted model is not.

## Decision

The advisor keeps its code and loses its runtime.

- It is absent from `_MEMBER_FACING`, so `available_providers()` never lists
  it and `is_available("builtin")` is false. A member cannot select it, and a
  request naming it is refused like any other unavailable provider.
- It is absent from `_AUTO_ORDER`, so `auto` never resolves to it. With
  nothing reachable, `auto` stays on the local model, the call fails honestly,
  and the member is told the model is not running and what to start.
- It remains reachable by naming it outright — `AI_PROVIDER=builtin`, or the
  older `mock` — which is what CI does and the only thing that still should.

A provider failure is no longer one message. A daemon that is not answering
gets `LOCAL_MODEL_DOWN_MESSAGE`, which names the condition and the two
commands that fix it; everything else keeps the generic outage message. Both
still escalate to a counsellor, and neither reveals the provider's error text.

## Consequences

**What this buys.** Every answer a member reads came from a language model, or
is an explanation of why one could not be reached. The most common failure in
this platform's life — Ollama not running — now diagnoses itself at the point
the member hits it, instead of being absorbed. The provider interface is
untouched: adding or removing a provider is still a registry entry.

**What it costs.** A machine with no Ollama no longer answers at all, where
before it answered badly. That is the intended trade and it is a real loss for
someone demonstrating the platform on a machine that cannot run a model —
`AI_PROVIDER=builtin` is the documented escape hatch, and `run.py` now sets up
Ollama rather than leaving it to them (ADR 0011). ADR 0009's claim narrows:
the platform still needs no API key, but it does need a model.

## Enforcement

- `test_the_builtin_advisor_is_never_offered_to_a_member` fails if it returns
  to the picker.
- `test_auto_never_falls_back_to_the_builtin_advisor` fails if the silent
  fallback returns.
- `test_the_advisor_is_reachable_only_by_naming_it_outright` keeps CI's path
  working, so the two cannot be conflated.
- `test_a_stopped_daemon_is_explained_rather_than_called_an_outage` and
  `test_a_running_model_that_fails_is_not_blamed_on_the_daemon` pin the two
  failure messages apart.
