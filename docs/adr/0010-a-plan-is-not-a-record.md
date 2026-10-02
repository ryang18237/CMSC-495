# 0010. A development plan is a separate kind, not a flag on a record item

Status: accepted

## Context

Members asked to be able to act on a suggestion, not just read it. Clicking
**Bachelor of Science in Information Technology** under Recommended next steps
should put it on their plan and move the list on.

The cheap implementation is to save it as an `EDUCATION` item, or as any item
with a `planned: true` flag. Both make the same mistake in different ways: the
profile is the single source of truth the Customer Data Adapter minimises into
every prompt, and the recommender ranks against it. An item that is on the
profile but not true corrupts both. A member who plans a bachelor's degree
would be told about the roles that degree unlocks, and the recommender would
start suggesting what follows a degree nobody has earned. A boolean flag is
worse than a separate kind here, because every one of those readers has to
remember to check it, and the failure mode when one forgets is silent.

## Decision

`GOAL` is a kind of record item alongside `CREDENTIAL`, `TRAINING`,
`EDUCATION` and `EXPERIENCE`. Nothing that reads the profile as fact reads it:

- The Customer Data Adapter maps inquiry types to named fields
  (`credentials`, `completed_training`, `education`, `experience`). `GOAL` is
  in none of them, so it never reaches a prompt.
- `ProfileCompleteness` counts only the four held kinds. Having no plan is
  not a gap in the record of what you have done.
- The recommender takes plan titles in a `planned` field that is used only to
  drop those pathways from the results. They are never vectorised, so a plan
  can never make a member look more qualified than they are.

## Consequences

Choosing a suggestion moves the member on: the chosen pathway leaves the list
and the rest move up. The plan is editable like anything else on the profile
-- every item has a **Remove** -- so a member can change their mind without
asking anyone.

The cost is a fifth kind to carry through the schema, the API and the client,
and the discipline that each new reader of the profile has to decide
explicitly whether it wants held kinds or all kinds. That is the point: the
decision is visible at each call site rather than hidden behind a flag.

## Enforcement

- `test_a_plan_does_not_count_toward_completeness` fails if `GOAL` is counted.
- `test_a_plan_is_never_sent_to_the_provider` fails if a goal reaches an
  answer.
- `test_a_plan_is_never_scored_as_experience` fails if a plan alone makes a
  profile look non-empty to the recommender.
- `test_a_planned_pathway_drops_out_of_the_list` fails if choosing something
  leaves it in the list.
