# Architecture decision records

OWNER: Ravonne Wade (Lead Architect)

One short document per decision that would be expensive to reverse, written
when the decision is made rather than reconstructed afterwards. The value is
the *context* section: six months from now the decision will look either
obvious or stupid, and only the context explains which it was at the time.

Each record follows the same shape:

- **Status** — proposed, accepted, or superseded by a later record
- **Context** — what was true when the decision was made
- **Decision** — what was chosen, in one sentence
- **Consequences** — what this buys and what it costs, honestly
- **Enforcement** — the test that stops the decision quietly eroding, if there
  is one

Numbering is sequential and never reused. A decision that turns out to be wrong
gets a new record that supersedes the old one; the old record stays, because
deleting it hides the reasoning.

| # | Decision | Status |
| --- | --- | --- |
| [0001](0001-modular-monolith.md) | Modular monolith rather than microservices | Accepted |
| [0002](0002-ai-provider-interface.md) | The AI model sits behind a provider interface | Accepted |
| [0003](0003-database-outbox-queue.md) | A database outbox stands in for the message queue | Accepted |
| [0004](0004-deterministic-escalation.md) | Escalation is rule-based, not confidence-based | Accepted |
| [0005](0005-local-database-fallback.md) | SQLite is a local fallback; PostgreSQL is the data layer | Accepted |
