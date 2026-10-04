# 0009 — The platform is fully usable with no API key

**Status:** Accepted
**Date:** Final release
**Deciders:** Ryan Gant, Benjamin Madden, Ravonne Wade

## Context

ADR 0008 let a member choose between Claude and ChatGPT. Both need an API
key, and a key needs a billing account, so anyone cloning the repository — a
teammate, a grader, a veteran trying the tool — met a sign-up before they met
the product. The keyless path existed but was called a "mock", which told
every reader it was a stand-in rather than something to rely on.

Asking end users for their own key was never on the table: it puts a
credential in a browser form, makes every user responsible for a bill, and
turns a five-second sign-in into a twenty-minute errand.

## Decision

The keyless provider becomes a real, named feature — the **built-in advisor**
(`builtin`) — and the default. It composes answers from the member's profile
and the pathway recommender rather than returning canned text, so it is
personal and useful on its own.

Managed models stay optional and stay a **server** setting. Whoever runs the
instance puts a key in `backend/.env` once; every member of that instance
then sees the extra option in the model picker. There is no field anywhere in
the interface for a member to enter a key, and no endpoint accepts one.

`mock` remains an accepted alias so existing configuration keeps working.

## Consequences

**What this buys.** `git clone` then `python run.py` produces a working,
personalised product with no account, no key, no cost and no network. CI runs
the full conversation path with no secret to leak. A member's data never
leaves the process on the default path.

**What it costs.** The advisor understands topics, not free text, so it
declines more often than a language model — those turns become
`UNSUPPORTED_TOPIC` handovers to a counsellor. Calling it the default also
means the answers most people see are the narrower ones. That is the right
trade for a service whose fallback is a human being, and it is stated plainly
in `AI_FEATURES.md` rather than hidden.

**Alternatives considered.**

- *A shared team key committed to the repository.* Rejected: a private repo is
  private from the public, not between collaborators, and a committed key
  survives in history.
- *Asking each member for their own key.* Rejected on usability and on
  security — a credential typed into a form is a credential that can leak.
- *A free hosted proxy holding one key for everyone.* Rejected for a course
  project: it needs a server, a budget, abuse controls and rate limiting, and
  it makes the team liable for every member's usage.

## Enforcement

`test_model_choice.py` runs a full conversation with every key unset and
asserts a personalised `ANSWERED` reply; it also asserts that a provider
without a key can never be selected and that no key appears in any response.
CI sets `AI_PROVIDER=builtin` and holds no secret.
