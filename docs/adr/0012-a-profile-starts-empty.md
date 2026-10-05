# 0012 — Nothing on a profile is beyond the member's reach

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

**Amended after use.** Starting from nothing was the right fix for the
unremovable record and the wrong default for everything else: there was
nothing to recommend from on the first screen, and a demonstration needed a
minute of typing before it showed anything. The demo accounts are now seeded
with a starting profile again — but through `_seed_profile_for`, as the
member's *own* entries, each with a Remove button. The rule this ADR is
actually about is unchanged, and is now its title: a populated profile is
fine, an uneditable one is not.

That seeding runs only on the branch that creates the account, never on a
later startup. Re-seeding whenever the profile looked empty would quietly
restore anything the member deleted, which is the original complaint wearing
a different hat.

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

**What this buys.** Everything on a profile can be taken off by the member,
with no exception to explain. The empty state is a prompt rather than a dead
end, and the populated state is one the member can take apart.

**What it costs.** The seeded entries are indistinguishable from ones the
member typed, because that is the point — so a member cannot tell which lines
the platform supplied. For a demonstration profile of invented data that is
the right trade; for a real personnel feed it would not be, which is why that
feed stays separate and read-only. Tests that assumed a seeded legacy history
set one up explicitly, through the `member_with_history` fixture.

## Enforcement

`test_a_seeded_member_carries_no_history` fails if the personnel feed grows
training or credentials again.
`test_nothing_on_a_profile_is_beyond_the_members_reach` deletes every line the
API returns and fails if one survives, and
`test_a_new_account_is_given_a_profile_it_owns` pins that a deleted seed entry
does not come back.
`test_an_empty_profile_is_asked_for_rather_than_guessed_about` pins the
assistant's empty-profile reply, and
`test_an_empty_profile_does_not_make_everything_answerable` keeps that reply
from swallowing questions that belong with a counsellor.
