# SkillBridge AI

CMSC 495 team project — **final release, version 1.0.0**.

A free education and professional development service for military members and
veterans. Members ask about certifications, degrees, apprenticeships and
civilian careers; the platform answers from approved reference material and
from the training each member has already completed, recommends concrete next
steps, and hands the conversation to a human counsellor whenever it should not
answer on its own. Nothing is sold and nothing is charged for.

Every record in this repository is synthetic. No real service member's
information appears anywhere, and the knowledge base and pathway catalog are
illustrative content rather than guidance from any agency.

| Role | Member | Owns |
| --- | --- | --- |
| Lead Architect | Ravonne Wade | Architecture, component boundaries, data flow, documentation, quality metrics |
| Interface Designer | Ryan Gant | API endpoints and contracts, validation, error handling, client, CI/CD |
| Integration Lead | Benjamin Madden | AI features, provider integration, human escalation path |

---

## Quick start

Requires **Python 3.10+** and **Node 18+**. No database to install and no file
to edit.

```bash
git clone https://github.com/ryang18237/CMSC-495.git
cd CMSC-495
python3 run.py          # Windows: python run.py
```

Or double-click **`start.command`** (macOS) or **`start.bat`** (Windows).

The browser opens at <http://localhost:5173>. Click **Continue as a member**,
ask a question, and look at **Recommended next steps** beside the chat. Then
sign out and **Continue as a counsellor** to answer the member from the other
side. Full setup, PostgreSQL and troubleshooting: [`docs/INSTALL.md`](docs/INSTALL.md).

| Account | Password |
| --- | --- |
| `member@example.com` — Army IT specialist | `DemoPassw0rd!` |
| `member2@example.com` — Navy hospital corpsman | `DemoPassw0rd!` |
| `counselor@example.com` — career counsellor | `DemoPassw0rd!` |

Interactive API documentation runs at <http://127.0.0.1:8000/docs>.

**No API key is needed.** The built-in advisor answers from the member's
profile, so the platform is complete as cloned. To have Claude or ChatGPT
answer instead, whoever runs the server adds one key to `backend/.env` — see
[Adding Claude or ChatGPT](docs/AI_FEATURES.md#adding-claude-or-chatgpt).

---

## What it does

| Feature | Detail |
| --- | --- |
| **My profile** | Members enter credentials, education, experience and training once — typed in, or imported from a resume or transcript — and every conversation and recommendation uses them from then on. |
| **Conversational assistant** | Answers grounded in the member's profile and approved articles, with sources shown. Works with **no API key**: a built-in advisor composes answers from the profile and the recommender. Claude and ChatGPT are optional upgrades the operator adds; members are never asked for a key. |
| **Pathway recommender** | Ranks 23 civilian credentials and programs against the member's record using TF-IDF and cosine similarity, explains each suggestion, never suggests something already held. Needs no key. |
| **Response validation** | Every generated answer is checked before a member sees it — no claims of enrolling or applying, no guaranteed outcomes, no sensitive identifiers, no truncated text. |
| **Deterministic escalation** | Five rule-based reasons hand a conversation to a person: member request, security concern, unsupported topic, validation failure, AI service failure. |
| **Counsellor dashboard** | Escalation queue with full context, replies that appear in the member's own chat, case workflow. |
| **Learning loop** | Feedback is recorded to an outbox; an analytics worker turns recurring patterns into candidates a counsellor approves or rejects. Nothing changes the assistant automatically. |
| **Operations** | Per-instance counters: requests, escalation rate, p95 latency against the five-second target, cache hit rate. |

How to use each of these: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md).

---

## Documentation

| Document | For |
| --- | --- |
| [Installation guide](docs/INSTALL.md) | Setting up on macOS, Windows or Linux; PostgreSQL; troubleshooting |
| [User guide](docs/USER_GUIDE.md) | Members and counsellors, with screenshots |
| [API reference](docs/API.md) · [OpenAPI](docs/openapi.json) | Every endpoint, request, response and error code |
| [AI features](docs/AI_FEATURES.md) | The assistant, the recommender, evaluation results, failure handling |
| [Architecture design](docs/ARCHITECTURE_DESIGN.md) | Components, boundaries, data flows, quality attributes, debt |
| [Architecture as built](docs/ARCHITECTURE.md) | Generated module graph and implementation notes |
| [Decision records](docs/adr/README.md) | Why the eight hardest-to-reverse decisions went the way they did |
| [CI/CD pipeline](docs/CI_CD.md) | The four jobs, what each gates, run evidence |
| [Code quality metrics](docs/metrics/README.md) | Coverage, complexity, benchmarks, code reviews |
| [Security](docs/SECURITY.md) | Secrets, access rules, what the shared repository means for keys |

---

## Architecture at a glance

A **modular monolith**: one deployable FastAPI application whose ten
components communicate only through named entry points, with a React client
and PostgreSQL. The boundaries are not a convention — sixteen tests parse the
source and fail the build if a component reaches where it should not, and the
dependency diagram is generated from the real imports.

```
React client ──HTTP──▶ API layer ──▶ Conversation Management ──▶ Customer Data Adapter ──▶ Cache
                          │                    ├──▶ Knowledge Base ──▶ Cache
                          │                    ├──▶ AI Integration ──▶ provider (mock / Anthropic)
                          │                    ├──▶ Response Validation
                          │                    └──▶ Escalation
                          ├──▶ Pathway recommender (AI Integration) via Customer Data Adapter
                          ├──▶ Feedback ──▶ outbox ──▶ Learning Analytics Worker
                          └──▶ Monitoring
```

## Quality at a glance

| | |
| --- | --- |
| Tests | 236 backend (PostgreSQL 16) · 42 frontend · 11-step end-to-end |
| Coverage | 94.4% backend lines · 90.3% frontend lines, with floors in CI |
| Complexity | Mean cyclomatic complexity 2.6; no function above 15; CI limit 15 |
| Static analysis | 0 findings — ruff, mypy, ESLint, actionlint |
| Latency | Conversation turn p95 128 ms at 10 concurrent clients (built-in advisor); target 5 s |
| Recommender | Relevant pathway in the top three for 7 of 7 labelled records |

Details and how each is measured: [`docs/metrics/`](docs/metrics/README.md).

---

## Development

```bash
python run.py --check        # everything CI runs: lint, types, tests, contract, architecture, complexity
python run.py --reset-db     # start from an empty database
python run.py --reinstall    # reinstall dependencies from scratch
```

Workflow: branch from `main`, keep `python run.py --check` green, open a pull
request using the template, and merge once CI passes. Python follows ruff
formatting at 100 columns; JavaScript uses Allman braces, enforced by ESLint.
Keep commit messages short. Never commit `backend/.env` or a key.

## Repository layout

```
run.py                     One-command setup and launcher (start.command / start.bat)
backend/
  app/
    main.py                Entry point, middleware, startup and shutdown
    schemas.py             Request/response contracts — the public interface
    errors.py              The shared error contract
    security.py            Token issuance, identity and role checks
    models.py, bootstrap.py  Data model and synthetic seed data
    api/v1/                Routers: auth, conversations, agent, pathways, health, ops
    modules/
      conversation/        Conversation Management — the one orchestrator
      customer_data/       Customer Data Adapter — legacy record translation and minimisation
      knowledge/           Knowledge Base
      ai_integration/      Providers, prompt building, retry policy, pathway recommender
      validation/          Response Validation
      escalation/          Escalation rules, cases, counsellor replies
      feedback/            Feedback and event outbox
      analytics/           Learning Analytics Worker
      cache/, monitoring/  Supporting components
  tests/                   236 tests, including contract and architecture tests
frontend/src/              React client: chat, recommendations, counsellor dashboard
docs/                      Everything in the documentation table above
scripts/
  smoke_test.sh            End-to-end check used by CI
  benchmark.py             HTTP performance benchmark
  quality_report.py        Maintainability metrics
  export_openapi.py        Regenerates docs/openapi.json
  generate_module_graph.py Regenerates the architecture diagram
.github/workflows/ci.yml   Backend, frontend, integration and delivery jobs
```

## Known limitations

Recorded in full, with consequences, in section 10 of the
[architecture design](docs/ARCHITECTURE_DESIGN.md#10-known-architectural-debt).
The ones to know before relying on this:

- The built-in advisor routes on topic rather than understanding free text,
  so unusual phrasings reach a counsellor instead of being answered. Configure
  Claude or ChatGPT on the server for wider coverage.
- The cache and rate-limit counters are per process, so instances are not yet
  fully stateless; monitoring counters are per instance and not exported.
- The provider call is synchronous and holds a worker thread for its duration.
- One instance has been benchmarked. The 10,000 concurrent-user requirement
  has not been demonstrated.
- There is no special handling for a member in distress. A service for
  veterans needs one before any real use.
