# 0003 — A database outbox stands in for the message queue

**Status:** Accepted
**Date:** Unit 5, Alpha release
**Deciders:** Ravonne Wade

## Context

The design places feedback analysis behind a message queue so it never delays a
live conversation. A managed broker is the eventual answer, but adding one in
the Alpha means a second piece of infrastructure that every team member has to
install and that CI has to stand up, in exchange for behaviour the Alpha cannot
yet demonstrate.

The property that actually matters at this stage is narrower than "we have a
broker": recording feedback must return immediately, and analysis must happen
somewhere else, later.

## Decision

The Feedback Module writes an event row to `feedback_events` inside the same
transaction as the feedback itself. The Learning Analytics Worker drains
unprocessed rows. The worker runs on demand rather than on a schedule.

## Consequences

**What this buys.** The asynchronous boundary is real and visible in the code,
not a comment promising one later. Writing the event in the same transaction as
the feedback means the two cannot disagree -- a genuine advantage over
publishing to a broker, where a crash between the commit and the publish loses
the event. No extra infrastructure for the team or for CI.

**What it costs.** No fan-out to multiple consumers, no delivery guarantees
beyond "the row is there", no back-pressure, and polling instead of push. With
more than one instance, two workers could claim the same row; the Alpha runs
one worker on demand, so that has not been solved.

**What changes when a broker arrives.** The Feedback Module publishes instead
of inserting, and the worker subscribes instead of polling. Callers of
`FeedbackService.record_feedback` are unaffected, which is the point of keeping
the publish behind that method.

## Enforcement

None automated. The boundary is a convention, held in place by
`FeedbackService.publish_feedback_event` being the only writer of
`feedback_events`.
