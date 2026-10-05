# 0012 — A profile starts empty

**Status:** Accepted
**Date:** Final release
**Deciders:** Ryan Gant, Ravonne Wade, Benjamin Madden

## Context

The seed data gave each demo member a service record already carrying
completed training and credentials. It made the first screen look populated,
and it was wrong in three ways at once.

It was unremovable. The personnel feed is read-only by design (ADR 0007), so
seeded items appeared under **From your service record** with no **Remove**
beside them, in a panel whose whole promise is that the member controls what
is on it. The first thing anyone tried was deleting one, and the first thing
they learned was that they could not.

It was unearned. Every recommendation, every completeness figure and every
answer about "your background" was computed from a history the person had
never had. A demonstration of advice grounded in a member's record is not a
demonstration if the record is invented for them.

And it hid the thing being built. The point of the profile is that it is
assembled: the recommendations change as it fills, which is only visible if
it starts out not filled.

## Decision

`_MEMBER_RECORDS` seeds branch, pay grade, specialty, years served and
separation date — facts about a posting — and seeds no training and no
credentials. The **From your service record** card is hidden entirely when
the feed returns nothing, rather than shown empty.

Each kind's card carries its own **+ Add** button, which sets the shared form
to that kind and focuses it, so adding the first item is one click from the
card that says the member has none.

The assistant handles the empty case explicitly rather than falling through
to a general answer: asked for advice with nothing on file, it says it has
nothing, names the four kinds it needs, and says three or four entries is
enough. An off-topic question still goes to a counsellor — an empty profile
is a reason to ask for data, not a reason to answer questions this service
does not answer.

## Consequences

**What this buys.** Everything on a profile was put there by the member and
can be taken off by them, with no exception to explain. The recommender's
behaviour as a record fills is visible from the first screen. The empty state
is a prompt rather than a dead end.

**What it costs.** A new member sees an empty panel and generic
recommendations until they enter something, and a demonstration needs a
minute of typing before it shows anything interesting. Tests that assumed a
seeded history now set one up explicitly, through the `member_with_history`
fixture — more setup per test, in exchange for each test stating the record
it depends on.

## Enforcement

`test_a_seeded_member_carries_no_history` fails if the seed grows training or
credentials again, and `test_a_new_member_starts_with_an_empty_profile` pins
the same thing through the API.
`test_an_empty_profile_is_asked_for_rather_than_guessed_about` pins the
assistant's empty-profile reply, and
`test_an_empty_profile_does_not_make_everything_answerable` keeps that reply
from swallowing questions that belong with a counsellor.
