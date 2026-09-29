# 0001 — Modular monolith rather than microservices

**Status:** Accepted
**Date:** Unit 5, Alpha release
**Deciders:** Ravonne Wade (Lead Architect), with Ryan Gant and Benjamin Madden

## Context

The platform has to support up to 10,000 concurrent users, integrate with an
existing personnel system, keep the AI feature isolated from core functions,
and stay maintainable by junior developers.

The first three of those are often read as an argument for microservices. The
fourth is the one that decides it. This is a three-person team on an eight-week
schedule, and Microsoft (2025) is explicit that microservices add service
discovery, data consistency across services, interservice communication,
independent deployment and operational overhead. Every one of those is work
that produces no customer-visible feature, and all of it lands on the same
three people who are also building the product.

Separation of concerns is a real requirement. Separate *processes* are not.

## Decision

Build the core application as a single deployable with strongly separated
internal modules, each owning one responsibility and communicating through
documented interfaces. Run asynchronous feedback analysis through a queue and a
worker so it never sits on a customer's request path.

## Consequences

**What this buys.** One thing to run, one thing to debug, one database, one
deployment. A junior developer can follow a customer turn end to end in a
single codebase. Refactoring across a boundary is an ordinary change rather
than a coordinated release of two services.

**What it costs.** The whole application scales as a unit: the AI module cannot
be given more instances than the knowledge base. A slow dependency can consume
threads that unrelated requests needed. Nothing except discipline stops a
developer importing across a boundary.

**Why the cost is acceptable now.** Instances are stateless, so scaling
horizontally behind a load balancer is available immediately, and that is the
axis that matters for 10,000 concurrent users. If one module later needs its
own scaling profile, AI Integration is the obvious first candidate to extract,
and it is already reachable only through `AIIntegrationService`.

**What this does not claim.** The architecture permits horizontal scaling. It
does not demonstrate 10,000 concurrent users; that is a load-testing task and
remains outstanding.

## Enforcement

`backend/tests/test_architecture_boundaries.py` turns "discipline" into CI.
It fails if a module imports the API layer, if a component depends on
Conversation Management, or if the components develop a dependency cycle --
the three ways a modular monolith usually decays into a plain one.

## References

Microsoft. (2025, October 14). *Architecture styles*. Microsoft Learn.
