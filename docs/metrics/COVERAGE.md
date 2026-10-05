# Test Coverage

**Owner:** Ravonne Wade (Lead Architect)

Coverage is measured on every push. CI prints a summary on the run page and
uploads the full HTML reports as the `backend-coverage` and
`frontend-coverage` artifacts. A drop below the floor fails the build.

| Suite | Tests | Lines | Branches | Floor enforced in CI |
| --- | ---: | ---: | ---: | --- |
| Backend — pytest against PostgreSQL 16 | 278 | **94.5%** | **83.5%** | 90% combined (`.coveragerc`) |
| Frontend — Vitest + Testing Library | 43 | **89.7%** | **85.4%** | 80% lines, 75% branches (`vite.config.js`) |
| End-to-end — `scripts/smoke_test.sh` | 11 steps | — | — | Must pass |

Backend combined line-and-branch coverage is 92.8%.

## Backend, by component

| Component | Lines | Branches |
| --- | ---: | ---: |
| Conversation Management | 99.0% | 94.4% |
| Customer Data Adapter | 93.9% | 87.8% |
| Knowledge Base | 91.5% | 80.0% |
| AI Integration | 95.6% | 85.5% |
| Response Validation | 96.2% | 90.9% |
| Escalation | 95.5% | 81.6% |
| Feedback | 97.2% | 100.0% |
| Learning Analytics Worker | 80.9% | 45.5% |
| Cache | 95.2% | 100.0% |
| Monitoring | 93.6% | 66.7% |
| API layer | 97.0% | 83.3% |
| Shared (config, schemas, errors, security, data) | 93.6% | 78.0% |

**Where coverage is thin, and why it matters or does not.** The Learning
Analytics Worker is lowest: its tests drive the patterns the demo produces, but
not every category of recommendation it can emit. It never touches a member's
request path — its output waits for human review — so a gap there cannot reach
a member, but it is the first place new tests should go. Monitoring's untested
lines are the 500-sample cap on the latency window, the slow-turn counter and
the empty-window percentile — none reachable in a short test run without
contrived data. The uncovered lines in `config.py` and `main.py` are the
local-development conveniences — generating a signing secret and seeding the
database on startup — which the test run skips because CI supplies
`JWT_SECRET` and sets `AUTO_BOOTSTRAP=false`, exactly as a deployment would.

## Frontend, by file

| File | Lines | Branches |
| --- | ---: | ---: |
| `App.jsx` | 91.8% | 88.2% |
| `api/client.js` | 77.3% | 76.0% |
| `api/agentHandoff.js`, `api/pathways.js` | 100% | 100% |
| `components/LoginPanel.jsx` | 100% | 92.9% |
| `components/MyRecordPanel.jsx` | 94.2% | 87.5% |
| `components/PathwayRecommendations.jsx` | 100% | 89.5% |
| `components/CounsellorReplyBox.jsx` | 97.0% | 92.3% |
| `components/EscalationQueue.jsx` | 91.9% | 86.4% |
| `components/InsightsPanel.jsx` | 89.4% | 80.0% |
| `components/OperationsPanel.jsx` | 94.5% | 83.3% |
| `hooks/useCounsellorReplies.js` | 81.3% | 87.5% |
| `pages/AgentDashboard.jsx` | 100% | 100% |
| `pages/CustomerChat.jsx` | 80.0% | 80.4% |

**The counsellor dashboard had no tests at all at the Alpha.** Measuring
coverage for the first time showed the frontend at **44.9%** of lines, with
every counsellor-facing screen — queue, case view, reply box, insights,
operations — at zero. `AgentDashboard.test.jsx` (11 tests), `App.test.jsx`
(5) and `agentHandoff.test.js` (3) were written in response, taking it to
89.4%. This is the clearest case in the project of a metric changing what was
built: nothing was failing, so without the measurement the gap would not have
been noticed.

## What the tests assert, beyond lines

Coverage says code ran, not that it was checked. The suites also pin
behaviour that line counts cannot show:

- **The API contract** — every route and every error code the code can raise
  must appear in `docs/API.md`, and every documented route must exist
  (`test_api_contract.py`).
- **The architecture** — sixteen rules on which component may import which,
  parsed from source (`test_architecture_boundaries.py`).
- **Recommendation quality** — hit rate and precision against hand-labelled
  service records, with floors that fail the build (`test_recommender.py`).
- **Security properties** — members cannot read each other's conversations,
  the API key never reaches a log line, provider error text never reaches a
  member.
- **My profile** — items a member saves reach every new conversation; a whole
  resume imports into four kinds; one member cannot remove another's; uploads
  are previewed, never saved unasked.
- **Usable with no key** — a full conversation with every key unset still
  returns a personalised answer.
- **Model choice** — a provider without a key can never be selected, and no
  key ever appears in an API response.
- **Concurrency** — the shared connection pool is created once under twenty
  simultaneous first requests; the test fails without the lock.

## Reproducing

```bash
cd backend
pytest --cov --cov-report=term --cov-report=html     # opens as backend/htmlcov/index.html

cd ../frontend
npm run test:coverage                                # frontend/coverage/index.html
```
