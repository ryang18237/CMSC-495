# Performance Benchmarks

**Owner:** Ravonne Wade (Lead Architect)

Measured with [`scripts/benchmark.py`](../../scripts/benchmark.py) over real
HTTP against a running instance, so every figure includes routing,
authentication, validation, database round trips and JSON serialisation. The
target is the System Design Specification's **five-second response time**.

CI runs the same benchmark on every push in the integration job — 200 requests
per scenario, 10 concurrent — writes the table to the run summary, uploads it
as the `benchmark` artifact, and fails if any p95 exceeds five seconds.

## Environment

One API process (uvicorn, one worker) on 2 CPUs, PostgreSQL 16 on the same
machine, mock AI provider. The client ran on the same machine, competing for
the same two CPUs, so these are conservative.

## Run 1 — 10 concurrent clients

| Scenario | Requests | p50 ms | p95 ms | p99 ms | Max ms | Req/s | Failures | Within 5 s target |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Health check | 200 | 25.5 | 61.5 | 73.0 | 76.8 | 335.6 | 0 | yes |
| Sign in | 20 | 1582.1 | 1681.6 | 1715.3 | 1715.3 | 6.2 | 0 | yes |
| Conversation turn | 200 | 77.1 | 113.8 | 129.8 | 132.2 | 122.7 | 0 | yes |
| Conversation history | 200 | 67.2 | 103.8 | 147.0 | 169.3 | 140.4 | 0 | yes |
| Pathway recommendations | 200 | 41.7 | 69.5 | 80.0 | 83.4 | 220.6 | 0 | yes |
| Counsellor queue | 200 | 44.4 | 87.4 | 101.6 | 105.7 | 202.8 | 0 | yes |

## Run 2 — 25 concurrent clients

| Scenario | Requests | p50 ms | p95 ms | p99 ms | Max ms | Req/s | Failures | Within 5 s target |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Health check | 300 | 67.3 | 130.2 | 144.2 | 157.1 | 339.0 | 0 | yes |
| Sign in | 30 | 2486.2 | 4670.8 | 4711.3 | 4711.3 | 6.3 | 0 | yes |
| Conversation turn | 300 | 212.1 | 282.7 | 316.4 | 349.3 | 114.2 | 0 | yes |
| Conversation history | 300 | 152.0 | 218.1 | 236.9 | 263.9 | 157.0 | 0 | yes |
| Pathway recommendations | 300 | 119.4 | 217.3 | 244.9 | 253.8 | 188.3 | 0 | yes |
| Counsellor queue | 300 | 121.7 | 186.1 | 201.5 | 226.4 | 198.2 | 0 | yes |

Every scenario met the target in both runs, with no failed requests.

## What the numbers say

**The platform's own overhead is small.** A full conversation turn — rate
limit, conversation lookup, inquiry classification, member-data minimisation,
knowledge retrieval, prompt construction, provider call, response validation,
escalation rules, persistence and metrics — takes a median of **77 ms** at 10
concurrent clients. With a real model the provider call dominates: a typical
large-language-model response takes one to several seconds, so the platform
itself uses under 100 ms of the 5,000 ms budget.

**The pathway recommender is cheap.** TF-IDF ranking of 23 pathways against a
member's record answers in a median of 42 ms — faster than reading the
conversation history — because the catalog vectors are built once per process
and only the member's record is vectorised per request.

**Sign-in is the slowest operation, on purpose.** Passwords are checked with
bcrypt, which is designed to be expensive so that a stolen password database
is slow to attack. At bcrypt's default work factor of 12, each check costs about 310 ms
of CPU on this machine, and with two CPUs, concurrent sign-ins queue: p95 is 1.7 s at 10 concurrent and **4.7 s at
25** — the only figure near the target. Sign-in happens once per session, not
once per message, so members feel it once. Under real load the fix is more
instances or more CPUs, not a cheaper hash; the finding is recorded in the
architecture design's debt register so the capacity plan accounts for it.

**Throughput is bounded by the single process.** Turns held steady at about
115–120 per second whether 10 or 25 clients were sending, while latency rose —
the signature of a saturated process rather than a slow database. That is the
expected shape for a stateless design meant to scale by adding instances.

## What was not measured

- **The real model's latency.** CI and these runs use the mock provider;
  measuring the Anthropic provider needs a key and costs money per call.
- **Multiple instances.** The 10,000-concurrent-user requirement is a claim
  about horizontal scaling. The design permits it; it has not been
  demonstrated, and this document should not be read as demonstrating it.
- **Sustained load.** Each scenario runs for seconds, not hours, so memory
  growth, connection-pool exhaustion and database bloat are untested.

## Reproducing

```bash
cd backend
RATE_LIMIT_MESSAGES_PER_MINUTE=100000 python -m uvicorn app.main:app --port 8001
# in a second terminal, from the repository root:
python scripts/benchmark.py --base-url http://127.0.0.1:8001 --requests 200 --concurrency 10
```

The message rate limit is raised only for the benchmark instance, so the
conversation scenario measures the platform rather than the limiter.
