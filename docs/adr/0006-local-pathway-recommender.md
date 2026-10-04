# 0006 — Pathway recommendations are computed locally, not by the model

**Status:** Accepted
**Date:** Final release
**Deciders:** Benjamin Madden, Ravonne Wade, Ryan Gant

## Context

The platform's purpose is insight based on what a member has already
completed. The chat assistant does that through a language model, which has
three properties that matter here:

1. It needs an API key. The people who evaluate this project, and CI, run the
   mock provider, so they never see a personalised AI result.
2. It is non-deterministic. The same record can produce different suggestions
   on different days, which cannot be tested exactly and cannot be reproduced
   when a counsellor asks "what did the member see?"
3. It sends member data to a third party on every call, however minimised.

A "what should I do next?" list is a ranking problem over a known catalog. It
does not need generated prose.

## Decision

Rank a curated pathway catalog against the member's record inside the
platform using content-based filtering — TF-IDF vectors and cosine similarity,
with a bonus for a held credential a pathway follows on from — and expose it at
`GET /api/v1/pathways/recommended`. The language model stays responsible for
free-text conversation only.

The recommender lives in AI Integration and follows that module's rules: it
imports no database, model or other component. The API route reads the record
through the Customer Data Adapter using the existing `CREDENTIAL` permission
set and hands the recommender plain lists. That adds one edge to the permitted
dependency graph — `api → customer_data` — which is the reason for this record.

## Consequences

**What this buys.** Every member sees a personalised result with no key and no
network. The same record always gives the same list, so ranking quality is
tested against labelled profiles and a regression fails the build. Every
suggestion names the item on the record it builds on. No member data leaves the
process. It answers in tens of milliseconds and keeps working when the model
provider is down.

**What it costs.** Similarity is lexical: "corpsman" and "medic" only meet
because the catalog lists both words. The catalog is small and hand-maintained,
and a record in a field it does not cover falls back to generic starting
points. Nothing yet learns from which suggestions members pursue.

**Alternatives considered.**

- *Ask the model for recommendations.* Rejected for the three reasons in the
  context.
- *Embeddings for semantic similarity.* Would fix the lexical limitation but
  needs either a model download too large for a one-command setup or an
  external embedding API, which brings back the key and the data transfer.
  The recommender's interface does not change if the vectoriser is swapped
  later.
- *Collaborative filtering ("members like you chose...").* There is no
  outcome data to learn from, and for a small population it would expose one
  member's choices through another's suggestions.

## Enforcement

`test_recommender.py` fails if hit rate @3 falls below 1.00 or precision @3
below 0.60 on the labelled profiles, if a held credential is ever suggested,
or if a `follows` reference names a missing pathway. The existing boundary
tests keep the recommender free of the database. The generated module graph in
`ARCHITECTURE.md` shows the new `api → customer_data` edge, and CI fails if the
diagram and the imports disagree.
