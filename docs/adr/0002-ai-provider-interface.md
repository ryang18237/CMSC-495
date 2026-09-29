# 0002 — The AI model sits behind a provider interface

**Status:** Accepted
**Date:** Unit 5, Alpha release
**Deciders:** Ravonne Wade, Benjamin Madden

## Context

The requirement is that the AI feature is isolated from core application
functions. There are two ways to read that. The weak reading is that AI code
lives in its own folder. The strong reading is that no other part of the
application knows which model provider is in use, or that a provider exists at
all.

Two practical pressures pushed us to the strong reading:

1. CI must run on every push without an API key, without network egress to a
   paid service, and without cost. That is impossible if the conversation path
   can only be exercised by calling a real model.
2. The provider will change. Model names move, pricing changes, and a managed
   provider can be unavailable at exactly the wrong moment.

## Decision

Define `AIProvider` with a single `generate(prompt) -> ProviderResponse`
method. `AIIntegrationService` owns prompt construction, the retry policy and
the fallback; a provider only translates a provider-neutral prompt onto a wire
format. Selection happens in configuration (`AI_PROVIDER`), never in code.

## Consequences

**What this buys.** `MockAIProvider` implements the same interface, so CI
exercises the real conversation path including escalation and validation, with
no key and no cost. The Integration Lead can implement a managed provider
without touching any caller. AI Integration has no dependency on the data
layer, which makes it the cleanest component to extract into its own service
if that day comes.

**What it costs.** An indirection to read through, and a provider-neutral
prompt shape that cannot use a provider's proprietary features without changing
the interface for everyone. That is a real limitation and an acceptable one:
depending on a proprietary feature is exactly the coupling this avoids.

**A trap to avoid.** A provider must not retry internally. The service owns the
retry policy, so a provider that also retried would multiply the request count
silently.

## Enforcement

`test_no_provider_is_imported_outside_the_ai_module` fails if any other
component imports a provider. `test_the_ai_module_never_touches_the_database`
fails if the AI module reaches into `app.db` or `app.models`.
