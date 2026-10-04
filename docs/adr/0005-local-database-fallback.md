# 0005 — SQLite is a local fallback; PostgreSQL is the data layer

**Status:** Accepted
**Date:** Unit 5, Alpha release
**Deciders:** Ravonne Wade, Ryan Gant

## Context

PostgreSQL is the data layer in the design and what a deployment uses. But a
teammate or an instructor cloning the repository should not have to install and
configure a database server before they can see the application run at all.
Setup friction is the most common reason a working prototype is judged as
broken.

## Decision

`run.py` connects to PostgreSQL whenever a server is reachable and falls back
to a local SQLite file when none is, announcing which it chose. CI always runs
against a real PostgreSQL service container. A portable `GUID` column type lets
the same models run on both.

## Consequences

**What this buys.** The application starts on a clean machine with one command.
Anyone can see it work in minutes, and the PostgreSQL path is still the one
every commit is tested against.

**What it costs.** Two databases in play, and they are not identical: SQLite
has weaker type enforcement, different concurrency behaviour, and no native
UUID. A bug that only appears on PostgreSQL would not be caught by a local run
-- which is precisely why CI uses PostgreSQL and not the fallback.

**The rule this creates.** Nothing in the application may depend on a feature
of either engine. If a PostgreSQL-specific feature becomes necessary, that is a
reason to supersede this record, not to quietly break the fallback.

**Honesty requirement.** `/api/v1/health` reports `database_engine`, so a
demonstration can never be vague about which one is live.

## Enforcement

CI runs the full suite against PostgreSQL 16. The `GUID` type in `app/db.py` is
the single place the difference is handled.
