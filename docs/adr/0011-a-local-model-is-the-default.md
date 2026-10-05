# 0011. A local model is the default, not a hosted one

Status: accepted

## Context

The built-in advisor made the platform usable with no key (ADR 0009), but it
routes on topic keywords rather than understanding what a member wrote, and
its answers read as such. The obvious fix — call Claude or ChatGPT — collides
with a requirement we had already committed to: anyone can clone this
repository and run it, and no member is ever asked for an API key.

Those two cannot both hold for a hosted model. Inference is paid for by
somebody. The three ways out are a key committed to the repository, which is
a credential leak and not an option; a single hosted deployment, which works
but means the project only demonstrates well when one particular server is
up and one particular person's card is on file; or running the model on the
machine the platform is already running on.

## Decision

`AI_PROVIDER` defaults to `auto`, which resolves at runtime: a local model
through [Ollama](https://ollama.com) when the daemon is reachable and the
configured model is pulled, and the built-in advisor otherwise. Naming a
provider explicitly always overrides the guess.

The provider subclasses `OpenAIProvider`, because Ollama speaks the same
`/v1/chat/completions` shape. It changes three things: no credential (the
header is required and ignored, so a constant stands in), readiness probed
against `GET /v1/models` rather than read from configuration, and a short
cache on that probe because it runs on every conversation turn.

Readiness requires the model to be *installed*, not merely the daemon to be
*up*. A provider offered without its model would 404 every turn, which is a
worse failure than not being offered.

`run.py` performs the setup rather than printing it. Before the API starts it
finds Ollama, starts the daemon if it is installed but stopped, and pulls the
model if it has never been pulled. A default that requires reading two lines
of output and running a command is not a default; most people would have read
the fallback paragraph instead and concluded the assistant was a canned
response generator. Installing software is the one step it asks about first,
because that is a decision about someone's computer rather than about this
project — a declined install, a missing network or an unattended run all fall
back to the built-in advisor and start the platform anyway.

## Consequences

Someone who clones the repository gets a real language model by answering one
question, with no account, no key and no cost, and the facts from their
service record never leave the machine. Someone who installs
nothing still gets a working platform. Neither path has a credential in it.

CI keeps using `builtin`, which is deterministic and needs no daemon, so the
conversation path is still exercised on every push at no cost.

The costs are real. A 3B model on a laptop answers less well than Claude and
more slowly, and the model download is a few gigabytes. Answers are no longer
reproducible between machines, so the benchmark figures in
`docs/metrics/BENCHMARKS.md` continue to be measured on `builtin`.

## Enforcement

- `test_auto_prefers_a_local_model_when_one_is_running` and
  `test_auto_falls_back_to_the_builtin_advisor` pin the resolution order.
- `test_a_local_model_is_only_offered_when_it_can_answer` fails if a provider
  whose model is missing is offered to a member.
- `test_no_api_key_is_required` fails if the provider ever grows a credential.
- `test_a_real_request_reaches_a_real_server` drives the provider against an
  OpenAI-compatible server over a loopback socket, which is what catches a
  wrong path, method or header that a mocked transport would accept.
