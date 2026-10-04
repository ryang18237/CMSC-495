# 0008 — Members choose the model; keys never leave the server

**Status:** Accepted
**Date:** Final release
**Deciders:** Benjamin Madden, Ryan Gant, Ravonne Wade

## Context

Some members and team members prefer ChatGPT to Claude. ADR 0002 already put
the model behind a provider interface, so a second managed provider is one
class. The open question was who chooses, and how to offer a choice without
putting API keys anywhere a browser can reach.

## Decision

Add an OpenAI provider behind the same interface. The server offers exactly
the providers it has keys for, plus the keyless demo assistant, through
`GET /api/v1/ai/providers`. The member picks one in the chat and each message
carries only the provider **id**. The API refuses an id without a configured
key (`422 AI_PROVIDER_UNAVAILABLE`). `AI_PROVIDER` sets the default.

## Consequences

**What this buys.** Choice without new risk: the browser never holds a key,
and every safeguard — prompt minimisation, retry budget, response validation,
handover — lives in the service, so it applies identically to every provider.

**What it costs.** Two providers' behaviour to watch instead of one, and two
bills. Answers to the same question differ by model; the reply records which
one answered so that difference is visible.

## Enforcement

`test_model_choice.py` checks that unconfigured providers are never offered or
accepted, that the providers endpoint never contains a key, and that the chosen
provider is the one that answers.
