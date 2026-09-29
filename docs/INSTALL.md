# Installation Guide

SkillBridge AI runs on **macOS, Windows 10/11 and Linux**. The fastest path
needs only Python and Node; PostgreSQL is optional for local use and is picked
up automatically when present.

- [1. Quick install](#1-quick-install)
- [2. Prerequisites](#2-prerequisites)
- [3. PostgreSQL (recommended)](#3-postgresql-recommended)
- [4. Configuration](#4-configuration)
- [5. Running without `run.py`](#5-running-without-runpy)
- [6. Verifying the install](#6-verifying-the-install)
- [7. Troubleshooting](#7-troubleshooting)

---

## 1. Quick install

```bash
git clone https://github.com/ryang18237/CMSC-495.git
cd CMSC-495
python3 run.py          # Windows: python run.py
```

Or double-click **`start.command`** (macOS) or **`start.bat`** (Windows).

The browser opens at <http://localhost:5173>. The first run takes two or three
minutes while dependencies install; later runs start in seconds. `Ctrl+C`
stops everything.

`run.py` does, in order: checks the Python version, creates
`backend/.venv`, installs backend dependencies, installs frontend dependencies,
picks a database (PostgreSQL if reachable, otherwise a local SQLite file),
creates the schema, loads the synthetic seed data, starts the API on port 8000
and the web client on port 5173, and opens the browser.

| Command | What it does |
| --- | --- |
| `python run.py` | Set up if needed, then start everything |
| `python run.py --check` | Run every check CI runs, then exit |
| `python run.py --reset-db` | Start from an empty database |
| `python run.py --reinstall` | Reinstall all dependencies from scratch |
| `python run.py --postgres` | Require PostgreSQL; fail rather than fall back |
| `python run.py --db-url URL` | Use a specific database |
| `python run.py --api-only` | API and `/docs` only, no web client |
| `python run.py --no-browser` | Do not open a browser window |

---

## 2. Prerequisites

| Tool | Version | Check |
| --- | --- | --- |
| Python | 3.10 or newer | `python3 --version` (Windows: `python --version`) |
| Node.js | 18 or newer (LTS) | `node --version` |
| Git | any recent | `git --version` |

### macOS

```bash
# Homebrew, if you do not have it: https://brew.sh
brew install python@3.11 node git
```

### Windows 10 / 11

Use **PowerShell**, not Command Prompt.

```powershell
winget install Python.Python.3.11
winget install OpenJS.NodeJS.LTS
winget install Git.Git
```

If you prefer installers, use python.org (tick **"Add python.exe to PATH"**),
nodejs.org (LTS) and git-scm.com. **Close and reopen PowerShell** after
installing so the new commands are found.

### Linux (Debian / Ubuntu)

```bash
sudo apt install python3 python3-venv python3-pip git
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install nodejs
```

---

## 3. PostgreSQL (recommended)

PostgreSQL is the platform's data layer: it is what the design specifies and
what CI tests every commit against. Without it, `run.py` falls back to a local
SQLite file and says so on screen, so the platform still starts. The
application code is identical either way; `/api/v1/health` reports which
engine is live under `dependencies.database_engine`.

### macOS

```bash
brew install postgresql@16
brew services start postgresql@16
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
createdb csp
```

Then point the app at it — `whoami` prints your username:

```bash
cp backend/.env.example backend/.env
```

```ini
DATABASE_URL=postgresql+psycopg://<your-mac-username>@localhost:5432/csp
```

### Windows 10 / 11

```powershell
winget install PostgreSQL.PostgreSQL.16
```

The installer asks for a **password for the `postgres` user** — write it
down. Close and reopen PowerShell, then:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\16\bin"
createdb -U postgres csp
copy backend\.env.example backend\.env
notepad backend\.env
```

```ini
DATABASE_URL=postgresql+psycopg://postgres:<your-password>@localhost:5432/csp
```

If the password contains `@`, `:`, `/` or `#`, percent-encode it (`@` → `%40`,
`:` → `%3A`, `/` → `%2F`, `#` → `%23`) or choose an alphanumeric one.

To keep the PATH change: search Windows for *Edit the system environment
variables* → **Environment Variables** → **Path** under *User variables* →
**New** → `C:\Program Files\PostgreSQL\16\bin`.

### Linux

```bash
sudo apt install postgresql
sudo -u postgres createuser --createdb "$USER"
createdb csp
```

```ini
DATABASE_URL=postgresql+psycopg://<your-username>@localhost:5432/csp
```

Run `python run.py` again; it reports **PostgreSQL is reachable**.

---

## 4. Configuration

You do not need a `backend/.env` to run the platform. Without one it uses safe
development defaults and generates a local signing secret in
`backend/.jwt_secret`. Create `.env` only to change something;
`backend/.env.example` lists every setting.

| Setting | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | chosen by `run.py` | Database connection |
| `JWT_SECRET` | generated locally | Token signing key — never commit a real one |
| `JWT_EXPIRE_MINUTES` | 60 | Session length |
| `CORS_ORIGINS` | `http://localhost:5173` | Allowed browser origins |
| `AI_PROVIDER` | `mock` | `mock` or `anthropic` |
| `ANTHROPIC_API_KEY` | empty | Only with `AI_PROVIDER=anthropic` — your own key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Pin a dated model for a reproducible demo |
| `AI_TIMEOUT_SECONDS` | 8 | Longest single provider call |
| `AI_MAX_RETRIES` | 1 | Retries for retryable provider failures |
| `AI_RETRY_BUDGET_SECONDS` | 5 | No retry starts after this much of a turn has passed |
| `RATE_LIMIT_MESSAGES_PER_MINUTE` | 30 | Per member |

`backend/.env` is git-ignored. **Never commit a key.** The repository is shared
with the whole team, so a committed key is readable by everyone with access and
stays in history after deletion. See [`SECURITY.md`](SECURITY.md).

---

## 5. Running without `run.py`

`run.py` only automates these steps.

**Terminal 1 — API**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

**Terminal 2 — web client**

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server proxies `/api` to port 8000, so
the browser sees one origin and no CORS exception is needed. The API creates
the schema and seeds data on startup; to do it explicitly, run
`python -m app.bootstrap` from `backend/`.

---

## 6. Verifying the install

| Check | Expected |
| --- | --- |
| <http://127.0.0.1:8000/api/v1/health> | `"status": "healthy"` and the database engine in use |
| <http://127.0.0.1:8000/docs> | Interactive API documentation |
| <http://localhost:5173> | Sign-in page with **Continue as a member** |
| `python run.py --check` | `All checks passed.` |

---

## 7. Troubleshooting

**`[Errno 48] Address already in use`** (macOS), `Errno 98` (Linux) or
`10048` (Windows) — a previous run still holds port 8000 or 5173, usually
because its terminal was closed without `Ctrl+C`. `run.py` now detects a
leftover run of this project and stops it before starting, and closing the
terminal shuts the servers down properly. If a *different* program holds the
port, `run.py` names it and stops; free the port by hand:

```bash
# macOS / Linux
lsof -ti :8000 | xargs kill -9
lsof -ti :5173 | xargs kill -9
```

```powershell
# Windows
netstat -ano | findstr :8000
taskkill /PID <number-from-the-last-column> /F
```

**`Cannot find module @rollup/rollup-darwin-arm64`** (or `-win32-x64`) — the
frontend dependencies were installed on a different operating system, for
example copied between machines. `run.py` detects this and reinstalls; to
force it: `python run.py --reinstall`.

**"Email address or password is incorrect"** with the demo accounts — an old
local database from an earlier version. `python run.py --reset-db`.

**PowerShell refuses to run `Activate.ps1`** — once, for your user only:
`Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

**`python` opens the Microsoft Store** — *Settings → Apps → Advanced app
settings → App execution aliases* → switch off both `python.exe` entries.

**`PostgreSQL is not reachable, using SQLite`** — expected without PostgreSQL.
If you installed it, check the server is running (`brew services list` /
*Services* on Windows) and that `DATABASE_URL` in `backend/.env` matches your
user and password.

**`git push` fails with `Permission denied (publickey)`** — your machine has no
SSH key registered with GitHub. Either run `gh auth login` and choose HTTPS, or
switch the remote: `git remote set-url origin https://github.com/ryang18237/CMSC-495.git`.

**Scripts in `scripts/*.sh` do not run on Windows** — they are bash scripts;
use Git Bash (*right-click → Git Bash Here*) or WSL. Nothing in the application
needs them; `run.py` covers the same ground on every platform.
