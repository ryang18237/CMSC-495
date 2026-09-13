# AI-Powered Customer Service Platform

CMSC 495 team project — **Alpha release**.

A modular monolith (FastAPI + PostgreSQL) with a React client, an isolated AI
Integration Module, deterministic human-escalation rules, and asynchronous
feedback analysis. Everything in this repository uses synthetic data only.

| Lead Architect | Ravonne Wade | Architecture, component boundaries, data flow |
| Interface Designer | Ryan Gant | API contracts, component interfaces, validation, error handling |
| Integration Lead | Benjamin Madden | AI chatbot integration, escalation path |

## What works in the Alpha

- **Multi-module integration** — one customer message travels through
  Conversation Management → Customer Data Adapter → Knowledge Base → AI
  Integration → Response Validation → (Escalation) → persistence, and the
  result is visible in both the customer client and the agent dashboard.
- **Functional AI component** — the AI Integration Module runs behind a
  provider interface with a working `MockAIProvider`. Switching to a managed
  model provider is a configuration change, not a code change.
- **CI/CD pipeline** — GitHub Actions runs lint, format, type checks, tests
  against a real PostgreSQL service, a frontend build, and an end-to-end
  integration smoke test on every push and pull request.
- **Core MVP features** — all seven specified endpoints, JWT authentication
  with customer and agent roles, the five approved escalation reasons, the
  documented error contract, feedback capture, and the Learning Analytics
  Worker.

Known Alpha limitations are listed at the bottom of this file.

## Local setup (macOS)

Prerequisites: Python 3.10+, Node 18+, PostgreSQL 14+, Git.

```bash
# PostgreSQL, if you do not already have it
brew install postgresql@16
brew services start postgresql@16
createdb csp
```

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# Edit .env: set DATABASE_URL for your machine and generate a JWT secret with
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

python -m app.bootstrap          # creates the schema and seeds synthetic data
uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

Interactive API docs are served at <http://127.0.0.1:8000/docs>.

### Frontend

```bash
cd frontend
npm install
npm run dev                      # http://localhost:5173
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so both processes
must be running.

### Seeded accounts

| Email | Password | Role |
| --- | --- | --- |
| `customer@example.com` | `DemoPassw0rd!` | CUSTOMER |
| `customer2@example.com` | `DemoPassw0rd!` | CUSTOMER |
| `agent@example.com` | `DemoPassw0rd!` | AGENT |

Sign in as the customer to use the chat; sign in as the agent to see the
escalation queue. Override the password with `SEED_PASSWORD` before running
`python -m app.bootstrap`.

## Running the checks locally

Run these before pushing; they are exactly what CI runs.

```bash
# Backend
cd backend
ruff check .
ruff format --check .
mypy app
pytest -q

# Frontend
cd ../frontend
npm run lint
npm test
npm run build

# End-to-end (backend must be running)
bash scripts/smoke_test.sh
```

The asynchronous worker is run on demand:

```bash
cd backend && python -m app.modules.analytics.worker
```

## Repository layout

```
backend/
  app/
    main.py              Application entry point and middleware
    config.py            Environment-driven configuration
    schemas.py           Request/response contracts (the public interface)
    errors.py            The shared error contract and status-code mapping
    security.py          JWT issuance, identity and role checks
    models.py            SQLAlchemy models, incl. the simulated legacy database
    bootstrap.py         Schema creation and synthetic seed data
    api/v1/              Routers: auth, conversations, agent, health
    modules/
      conversation/      Conversation Management Module (orchestrator)
      customer_data/     Customer Data Adapter (legacy schema translation)
      knowledge/         Knowledge Base Service
      ai_integration/    AI Integration Module + provider implementations
      validation/        Response Validation Module
      escalation/        Escalation rules and case management
      feedback/          Feedback Module and event outbox
      analytics/         Learning Analytics Worker (asynchronous)
  tests/                 72 tests covering the modules and every endpoint
frontend/
  src/api/client.js      Single API client; translates the error contract
  src/pages/             Customer chat, agent dashboard
  src/components/        Login panel
docs/
  API.md                       Endpoint reference
  ARCHITECTURE.md              Component boundaries and data flow
  AI_INTEGRATION_HANDOFF.md    Benjamin's implementation brief
  SECURITY.md                  Secret handling and access rules
scripts/smoke_test.sh    End-to-end integration check used by CI
```

## Alpha limitations (deliberate)

- `AnthropicProvider` is an interface stub; `AI_PROVIDER=mock` is the default.
  See `docs/AI_INTEGRATION_HANDOFF.md`.
- Rate-limit counters are in process memory. Production moves them to the
  shared cache so instances stay stateless.
- The event queue is a database outbox table rather than a managed queue, and
  the analytics worker is run on demand rather than on a schedule.
- Self-service registration is out of scope; accounts are seeded.
- The 10,000 concurrent-user target has not been load tested. The architecture
  permits horizontal scaling; the measurement is still outstanding.
