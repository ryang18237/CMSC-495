# SkillBridge AI

CMSC 495 team project — **Alpha release**.

A free education and professional development service for military members and
veterans. It answers questions about certifications, degrees, apprenticeships
and civilian careers, and grounds its suggestions in the training the member
has already completed. Nothing is sold and nothing is charged for.

Built as a modular monolith (FastAPI + PostgreSQL) with a React client, an
isolated AI Integration Module, deterministic human-escalation rules, and
asynchronous feedback analysis. Every record in this repository is synthetic;
no real service member's information appears anywhere, and the knowledge base
is illustrative sample content rather than guidance from any agency.

| Lead Architect | Ravonne Wade | Architecture, component boundaries, data flow |
| Interface Designer | Ryan Gant | API contracts, component interfaces, validation, error handling |
| Integration Lead | Benjamin Madden | AI chatbot integration, escalation path |

## Quick start

**Requirements: Python 3.10+ and Node 18+.** Nothing else — no database to
install, no configuration file to edit.

```bash
git clone https://github.com/ryang18237/CMSC-495.git
cd CMSC-495
python3 run.py          # Windows: python run.py
```

Or **double-click `start.command`** (macOS) or **`start.bat`** (Windows).

Your browser opens at **<http://localhost:5173>**. Click **Continue as a
member** — nothing to type — then ask a question or click one of the example
prompts.

The first run takes a couple of minutes while dependencies install. After that
it starts in seconds. `run.py` creates the virtual environment, installs
backend and frontend dependencies, selects a database, creates the schema,
loads the synthetic seed data, starts both processes, and opens the browser.
`Ctrl+C` stops everything.

### What to try

| Sign in as | What you see |
| --- | --- |
| **Member** (`member@example.com`) | The chat |
| **Counsellor** (`counselor@example.com`) | Three tabs: escalation queue, AI insights, operations |

A development build fills the seeded credentials in for you, so one click is
all it takes. The sign-in itself is real: it calls `/api/v1/auth/login`,
receives a signed token, and every later request is authorised with it — so the
401 and 403 paths still behave exactly as documented. A production build
(`npm run build`) drops the shortcuts and shows an ordinary empty form.

Both seeded passwords are `DemoPassw0rd!` if you want to type them. To see the
whole loop, escalate something as the member, then sign out and continue as the
counsellor.

The seeded member is an Army E-5 information technology specialist with a
network administration course and an A+ certification already completed, so the
assistant's answers refer back to that.

In the chat, each example prompt demonstrates a different path:

| Message | Result |
| --- | --- |
| `Which certification should I work toward next?` | `ANSWERED`, grounded in completed training |
| `Should I do a degree or a certification first?` | `ANSWERED` from the knowledge base |
| `I want to speak to a human` | `ESCALATED` / `CUSTOMER_REQUEST` — never reaches the model |
| `I think my account was hacked` | `ESCALATED` / `SECURITY_CONCERN` |
| `What is the capital of France?` | `ESCALATED` / `UNSUPPORTED_TOPIC` |
| `question __force_ai_failure__` | `ESCALATED` / `AI_SERVICE_FAILURE` with a safe fallback |

On the agent side, **AI insights** shows the improvement candidates the
Learning Analytics Worker produced — press *Run analysis* after escalating a
couple of conversations, then approve or reject one. **Operations** shows live
counters for the instance, including the escalation rate and p95 turn latency
against the five-second target.

Interactive API documentation is at <http://127.0.0.1:8000/docs>.

### `run.py` options

| Command | What it does |
| --- | --- |
| `python run.py` | Set up if needed, then start everything |
| `python run.py --check` | Run every check CI runs, then exit |
| `python run.py --reset-db` | Start from an empty database |
| `python run.py --postgres` | Require PostgreSQL; fail rather than fall back |
| `python run.py --api-only` | API and `/docs` only, no web client |
| `python run.py --db-url URL` | Use a specific database |
| `python run.py --no-browser` | Do not open a browser window |

### A note on the database

PostgreSQL is the platform's data layer: it is what the design specifies, what
the CI pipeline tests every commit against, and what a deployment would use.

`run.py` uses PostgreSQL whenever a server is reachable. When none is — a fresh
laptop, a teammate who has not installed it yet — it falls back to a local
SQLite file and says so on screen, so the platform still starts and can be
demonstrated. The application code is identical either way; only the connection
URL differs. `/api/v1/health` reports which engine is live under
`dependencies.database_engine`.

To use PostgreSQL, install it (see below) and `run.py` will pick it up. Use
`--postgres` to make a missing server an error instead of a fallback.

## Local setup (macOS)

<details>
<summary><b>macOS</b></summary>

```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
createdb csp
```

Then create `backend/.env` with your macOS username as the database user:

```bash
cp backend/.env.example backend/.env
```

```ini
DATABASE_URL=postgresql+psycopg://<your-mac-username>@localhost:5432/csp
```

(`whoami` prints the username.) Run `python3 run.py` again — it will report
`PostgreSQL is reachable`.

</details>

<details>
<summary><b>Windows 10 / 11</b></summary>

```powershell
winget install PostgreSQL.PostgreSQL.16
```

Or use the EDB installer from postgresql.org. Either way you set a **password
for the `postgres` user** during installation — write it down.

Close and reopen PowerShell, then:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\16\bin"
createdb -U postgres csp
```

To make that PATH change permanent: search Windows for *"Edit the system
environment variables"* → **Environment Variables** → select **Path** under
*User variables* → **New** → add `C:\Program Files\PostgreSQL\16\bin`.

Then create `backend\.env`:

```powershell
copy backend\.env.example backend\.env
notepad backend\.env
```

```ini
DATABASE_URL=postgresql+psycopg://postgres:<your-password>@localhost:5432/csp
```

If your password contains `@`, `:`, `/` or `#`, percent-encode it (`@` → `%40`,
`:` → `%3A`, `/` → `%2F`, `#` → `%23`) or choose an alphanumeric password —
those characters have special meaning inside a connection URL.

Run `python run.py` again — it will report `PostgreSQL is reachable`.

</details>

---

## Prerequisites in detail

<details>
<summary><b>macOS</b></summary>

```bash
# Homebrew, if you do not have it: https://brew.sh
brew install python@3.11 node git
```

Verify:

```bash
python3 --version   # 3.10 or newer
node --version      # 18 or newer
```

</details>

<details>
<summary><b>Windows 10 / 11</b></summary>

## Running the checks locally

`run.py` only automates the steps below; both still work exactly as before.

**Terminal 1 — the API**

```bash
cd backend
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

**Terminal 2 — the web client**

```bash
cd frontend
npm run dev
```

Then open <http://localhost:5173>. The dev server proxies `/api` to the
backend, so the browser sees a single origin and no CORS exception is needed.

Run by hand, the API creates the schema and loads seed data on startup
(`AUTO_BOOTSTRAP`, on by default for development). To do it explicitly instead:

```bash
cd backend && python -m app.bootstrap
```

You do not need a `backend/.env` file. Without one the application uses its
built-in development defaults and generates a local signing secret in
`backend/.jwt_secret` (git-ignored). Create `.env` when you want to point at a
specific database or enable a real AI provider — `backend/.env.example` lists
every setting.

---

## Running the checks

```bash
python run.py --check
```

That runs exactly what CI runs. Individually:

```bash
cd backend                         # Windows: .venv\Scripts\Activate.ps1
ruff check . && ruff format --check . && mypy app && pytest -q

cd ../frontend
npm run lint && npm test && npm run build
```

End-to-end check against a running instance (macOS, Linux or Git Bash):

```bash
bash scripts/smoke_test.sh
```

The asynchronous worker is run on demand:

```bash
cd backend && python -m app.modules.analytics.worker
```

## Repository layout

```
run.py                   One-command setup and launcher
start.command            macOS: double-click to run
start.bat                Windows: double-click to run
backend/
  app/
    main.py              Application entry point, middleware, startup bootstrap
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
      cache/             Cache interface + in-memory implementation
      monitoring/        Request, turn and latency counters
  tests/                 Tests covering the modules and every endpoint
frontend/
  src/api/client.js      Single API client; translates the error contract
  src/pages/             Customer chat, agent dashboard
  src/components/        Login panel, escalation queue, AI insights, operations
docs/
  API.md                       Endpoint reference
  ARCHITECTURE.md              Component boundaries and data flow (as built)
  AI_INTEGRATION_HANDOFF.md    Integration Lead's implementation brief
  SECURITY.md                  Secret handling and access rules
scripts/smoke_test.sh    End-to-end integration check used by CI
```

## Alpha limitations (deliberate)

- `AnthropicProvider` is an interface stub; `AI_PROVIDER=mock` is the default.
  See `docs/AI_INTEGRATION_HANDOFF.md`.
- The cache and the rate-limit counters are process-local. Production moves
  both to the shared cache so instances stay stateless.
- Monitoring counters are per-instance and are read through an endpoint rather
  than exported to a monitoring system. No alerting or tracing.
- Approving an AI improvement recommendation records the decision but does not
  apply it; no prompt or routing rule changes as a result.
- The event queue is a database outbox table rather than a managed queue, and
  the analytics worker runs on demand rather than on a schedule.
- Self-service registration is out of scope; accounts are seeded.
- A counsellor can read an escalated case but cannot yet reply to the member.
  That path is on the Integration Lead's branch.
- There is no special handling for a member in distress. A service for veterans
  would need one before any real use; the Alpha routes such a message through
  the ordinary rules, which most likely means an unsupported-topic escalation.
- The 10,000 concurrent-user target has not been load tested. The architecture
  permits horizontal scaling; the measurement is still outstanding.
