#!/usr/bin/env python3
"""Start the AI-Powered Customer Service Platform locally.

    python run.py

That is the whole setup. The script creates the backend virtual environment,
installs dependencies, picks a database, creates the schema, loads the
synthetic seed data, starts the API and the web client, and opens the browser.

Options
-------
    python run.py --check        run every check CI runs, then exit
    python run.py --reset-db     start from an empty database
    python run.py --api-only     skip the web client (API and /docs only)
    python run.py --postgres     require PostgreSQL; do not fall back
    python run.py --db-url URL   use a specific database
    python run.py --no-browser   do not open a browser window

Nothing here changes how the application is built. It only automates the setup
steps documented in the README, so `uvicorn app.main:app` and `npm run dev`
still work exactly as before for anyone who prefers to run them by hand.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
VENV = BACKEND / ".venv"

API_HOST = "127.0.0.1"
API_PORT = 8000
WEB_PORT = 5173
API_URL = f"http://{API_HOST}:{API_PORT}"
WEB_URL = f"http://localhost:{WEB_PORT}"

IS_WINDOWS = platform.system() == "Windows"
MIN_PYTHON = (3, 10)

# Windows has no SIGKILL. `taskkill /F` is already forceful, so SIGTERM is only
# a placeholder there -- but the name still has to resolve, because Python
# evaluates the argument before the platform branch inside _signal_group.
FORCE_SIGNAL = signal.SIGTERM if IS_WINDOWS else signal.SIGKILL

SQLITE_FILE = BACKEND / "local.sqlite3"
SQLITE_URL = f"sqlite+pysqlite:///{SQLITE_FILE.as_posix()}"

DEMO_PASSWORD = "DemoPassw0rd!"


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------
_COLOR = sys.stdout.isatty() and not IS_WINDOWS


def _paint(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def step(message: str) -> None:
    print(_paint(f"==> {message}", "1;36"), flush=True)


def info(message: str) -> None:
    print(f"    {message}", flush=True)


def warn(message: str) -> None:
    print(_paint(f"  ! {message}", "1;33"), flush=True)


def fail(message: str) -> None:
    print(_paint(f"  x {message}", "1;31"), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Environment preparation
# ---------------------------------------------------------------------------
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required; "
            f"this is {platform.python_version()}."
        )
        info("Install a newer Python and run this script with it.")
        sys.exit(1)


def ensure_backend_environment(force: bool = False) -> Path:
    """Create the virtual environment and install dependencies if needed."""
    if force and VENV.is_dir():
        step("Removing the existing virtual environment")
        shutil.rmtree(VENV, ignore_errors=True)

    python = venv_python()

    if not python.exists():
        step("Creating the backend virtual environment (first run only)")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        python = venv_python()

    probe = subprocess.run(
        [str(python), "-c", "import fastapi, sqlalchemy, jwt, bcrypt"],
        capture_output=True,
    )
    if probe.returncode != 0:
        step("Installing backend dependencies (first run only, this takes a minute)")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
            check=True,
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(BACKEND / "requirements-dev.txt")],
            check=True,
        )

    return python


def npm_command() -> str | None:
    return shutil.which("npm.cmd") if IS_WINDOWS else shutil.which("npm")


# node_modules holds compiled binaries for one operating system and CPU. A copy
# made on a different machine (or committed, or synced through a shared folder)
# leaves the platform packages Vite needs as empty directories, and the build
# fails with "Cannot find module '@rollup/rollup-<platform>'". The marker file
# records what the tree was built for so the mismatch is repaired automatically.
PLATFORM_MARKER = "node_modules/.install-platform"


def _platform_tag() -> str:
    return f"{platform.system()}-{platform.machine()}"


def _frontend_toolchain_loads() -> bool:
    """Load the two native toolchain packages the same way Vite does.

    `require('rollup')` resolves the binding for the current platform, which is
    precisely what fails with "Cannot find module '@rollup/rollup-<platform>'"
    when node_modules was installed on a different machine. Probing here turns
    that crash into an automatic reinstall.
    """
    node = shutil.which("node")
    if node is None or not (FRONTEND / "node_modules" / "vite").is_dir():
        return False

    probe = subprocess.run(
        [node, "-e", "require('rollup'); require('esbuild')"],
        cwd=FRONTEND,
        capture_output=True,
    )
    return probe.returncode == 0


def _npm_install(npm: str) -> None:
    result = subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    if result.returncode != 0:
        warn("The install failed. Clearing node_modules and trying once more.")
        shutil.rmtree(FRONTEND / "node_modules", ignore_errors=True)
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=FRONTEND, check=True)
    (FRONTEND / PLATFORM_MARKER).write_text(_platform_tag(), encoding="utf-8")


def ensure_frontend_environment(npm: str, force: bool = False) -> None:
    modules = FRONTEND / "node_modules"
    marker = FRONTEND / PLATFORM_MARKER
    tag = _platform_tag()

    if force and modules.is_dir():
        step("Reinstalling web client dependencies")
        shutil.rmtree(modules, ignore_errors=True)
    elif modules.is_dir():
        recorded = ""
        try:
            recorded = marker.read_text(encoding="utf-8").strip()
        except OSError:
            pass

        if recorded == tag:
            return
        if not recorded and _frontend_toolchain_loads():
            # Installed by hand rather than by this script, and healthy.
            try:
                marker.write_text(tag, encoding="utf-8")
            except OSError:
                pass
            return

        step("Repairing web client dependencies")
        info(
            f"node_modules was installed for {recorded or 'a different platform'}; "
            f"this machine is {tag}."
        )
        shutil.rmtree(modules, ignore_errors=True)
    else:
        step("Installing web client dependencies (first run only)")

    _npm_install(npm)


# ---------------------------------------------------------------------------
# Database selection
# ---------------------------------------------------------------------------
def configured_database_url() -> str | None:
    """DATABASE_URL from the environment, or from backend/.env if present."""
    from_env = os.environ.get("DATABASE_URL")
    if from_env:
        return from_env

    env_file = BACKEND / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    return None


def can_connect(python: Path, url: str) -> bool:
    probe = (
        "import sys\n"
        "from sqlalchemy import create_engine, text\n"
        "url = sys.argv[1]\n"
        "kwargs = {'connect_args': {'connect_timeout': 3}} if url.startswith('postgresql') else {}\n"
        "engine = create_engine(url, **kwargs)\n"
        "with engine.connect() as connection:\n"
        "    connection.execute(text('SELECT 1'))\n"
    )
    return subprocess.run([str(python), "-c", probe, url], capture_output=True).returncode == 0


def try_create_postgres_database(python: Path, url: str) -> bool:
    """Create the target database if the server is up but the database is not."""
    if "/" not in url.rsplit("/", 1)[0]:
        return False
    server_url, _, database = url.rpartition("/")
    database = database.split("?", 1)[0]
    if not database:
        return False

    script = (
        "import sys\n"
        "from sqlalchemy import create_engine, text\n"
        "server, name = sys.argv[1], sys.argv[2]\n"
        "engine = create_engine(f'{server}/postgres', isolation_level='AUTOCOMMIT',\n"
        "                      connect_args={'connect_timeout': 3})\n"
        "with engine.connect() as connection:\n"
        "    connection.execute(text(f'CREATE DATABASE \"{name}\"'))\n"
    )
    created = subprocess.run(
        [str(python), "-c", script, server_url, database], capture_output=True
    )
    return created.returncode == 0


def resolve_database(python: Path, args: argparse.Namespace) -> tuple[str, str]:
    """Return (database_url, human readable label)."""
    if args.db_url:
        if not can_connect(python, args.db_url):
            fail(f"Could not connect to {args.db_url}")
            sys.exit(1)
        return args.db_url, "the database you specified"

    candidate = configured_database_url() or "postgresql+psycopg://csp:csp@localhost:5432/csp"

    step("Selecting a database")
    if can_connect(python, candidate):
        info(f"PostgreSQL is reachable: {_redact(candidate)}")
        return candidate, "PostgreSQL"

    if candidate.startswith("postgresql") and try_create_postgres_database(python, candidate):
        if can_connect(python, candidate):
            info(f"Created the PostgreSQL database: {_redact(candidate)}")
            return candidate, "PostgreSQL"

    if args.postgres:
        fail(f"PostgreSQL is not reachable at {_redact(candidate)}")
        info("Start PostgreSQL, or drop --postgres to use the local SQLite file.")
        sys.exit(1)

    warn("No PostgreSQL server reachable, so this run uses a local SQLite file.")
    info("PostgreSQL is the supported data layer and is what CI tests against;")
    info("SQLite is a convenience so the platform starts on a clean machine.")
    info("To use PostgreSQL, follow the setup section of the README.")
    return SQLITE_URL, "SQLite (local file)"


def _redact(url: str) -> str:
    """Hide a password before printing a connection URL."""
    if "://" not in url or "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    credentials, _, host = rest.partition("@")
    if ":" in credentials:
        user = credentials.split(":", 1)[0]
        credentials = f"{user}:***"
    return f"{scheme}://{credentials}@{host}"


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------
class Service:
    def __init__(self, name: str, command: list[str], cwd: Path, env: dict[str, str]) -> None:
        self.name = name
        kwargs: dict[str, object] = {"cwd": str(cwd), "env": env}
        if IS_WINDOWS:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]

    def stop(self) -> None:
        """Stop the service and everything it spawned.

        Each service runs in its own process group (its own session on POSIX),
        so signalling the group reaches the children too -- uvicorn's reload
        worker, and the node process behind `npm run dev`.
        """
        if self.process.poll() is not None:
            return

        self._signal_group(signal.SIGTERM)
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._signal_group(FORCE_SIGNAL)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass

    def _signal_group(self, sig: int) -> None:
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                )
            else:
                os.killpg(os.getpgid(self.process.pid), sig)
        except (OSError, subprocess.SubprocessError):
            try:
                if sig == FORCE_SIGNAL:
                    self.process.kill()
                else:
                    self.process.terminate()
            except OSError:
                pass


def wait_for(url: str, timeout: int = 60) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def run_checks(python: Path, env: dict[str, str], args_holder: argparse.Namespace) -> int:
    """Run exactly what the CI pipeline runs."""
    failures: list[str] = []

    backend_checks = [
        ("ruff check", [str(python), "-m", "ruff", "check", "."]),
        ("ruff format --check", [str(python), "-m", "ruff", "format", "--check", "."]),
        ("mypy", [str(python), "-m", "mypy", "app"]),
        ("pytest", [str(python), "-m", "pytest", "-q"]),
    ]
    for label, command in backend_checks:
        step(f"backend: {label}")
        if subprocess.run(command, cwd=BACKEND, env=env).returncode != 0:
            failures.append(f"backend {label}")

    npm = npm_command()
    if npm is None:
        warn("npm not found, skipping the web client checks.")
    else:
        ensure_frontend_environment(npm, force=getattr(args_holder, "reinstall", False))
        for label, command in [
            ("lint", [npm, "run", "lint"]),
            ("test", [npm, "test"]),
            ("build", [npm, "run", "build"]),
        ]:
            step(f"frontend: {label}")
            if subprocess.run(command, cwd=FRONTEND).returncode != 0:
                failures.append(f"frontend {label}")

    print()
    if failures:
        fail("Failed: " + ", ".join(failures))
        return 1
    print(_paint("All checks passed.", "1;32"))
    return 0


def serve(python: Path, env: dict[str, str], label: str, args: argparse.Namespace) -> int:
    services: list[Service] = []
    npm = npm_command()

    try:
        step("Starting the API")
        services.append(
            Service(
                "api",
                [
                    str(python),
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    API_HOST,
                    "--port",
                    str(API_PORT),
                    "--reload",
                ],
                BACKEND,
                env,
            )
        )

        if not wait_for(f"{API_URL}/api/v1/health"):
            fail("The API did not start. The error should be printed above.")
            return 1
        info(f"API ready at {API_URL} (interactive docs at {API_URL}/docs)")

        serve_web = not args.api_only and npm is not None
        if args.api_only:
            info("Web client skipped (--api-only).")
        elif npm is None:
            warn("npm was not found, so only the API is running.")
            info("Install Node.js from https://nodejs.org to get the web interface.")

        if serve_web:
            ensure_frontend_environment(npm, force=args.reinstall)  # type: ignore[arg-type]
            step("Starting the web client")
            services.append(Service("web", [npm, "run", "dev"], FRONTEND, env))  # type: ignore[list-item]
            if not wait_for(WEB_URL):
                fail("The web client did not start. The error should be printed above.")
                return 1

        target = WEB_URL if serve_web else f"{API_URL}/docs"
        _print_banner(target, label, serve_web)

        if not args.no_browser:
            webbrowser.open(target)

        while all(service.process.poll() is None for service in services):
            time.sleep(0.5)

        for service in services:
            if service.process.poll() not in (None, 0):
                fail(f"The {service.name} process exited unexpectedly.")
                return 1
        return 0

    except (KeyboardInterrupt, SystemExit):
        print()
        step("Stopping")
        return 0
    finally:
        for service in reversed(services):
            service.stop()


def _print_banner(target: str, label: str, serve_web: bool) -> None:
    line = "-" * 62
    print()
    print(_paint(line, "1;32"))
    print(_paint(f"  Open  {target}", "1;32"))
    print(_paint(line, "1;32"))
    print(f"  Data layer     {label}")
    print(f"  API            {API_URL}   (docs at {API_URL}/docs)")
    if serve_web:
        print(f"  Web client     {WEB_URL}")
    print()
    print("  Sign in with one of the seeded demo accounts:")
    print(f"    customer@example.com   {DEMO_PASSWORD}   (support chat)")
    print(f"    agent@example.com      {DEMO_PASSWORD}   (escalation queue)")
    print()
    print("  In the chat, try:")
    print('    "Why was I charged twice for my order?"   -> answered')
    print('    "I want to speak to a human"              -> escalated to an agent')
    print('    "What is the capital of France?"          -> unsupported topic')
    print()
    print("  Press Ctrl+C to stop.")
    print(_paint(line, "1;32"))
    print(flush=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _install_signal_handlers() -> None:
    """Make Ctrl+C and a terminate signal both shut the services down.

    A process started in the background by a shell inherits SIGINT as ignored,
    so the default handler is restored explicitly. SIGTERM is translated into
    SystemExit so the cleanup in `serve()` runs when a terminal is closed.
    """
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        pass

    def _terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    try:
        signal.signal(signal.SIGTERM, _terminate)
    except (ValueError, OSError):
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start the AI-Powered Customer Service Platform locally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="run every check CI runs, then exit")
    parser.add_argument("--reset-db", action="store_true", help="start from an empty database")
    parser.add_argument("--api-only", action="store_true", help="skip the web client")
    parser.add_argument("--postgres", action="store_true", help="require PostgreSQL")
    parser.add_argument("--db-url", metavar="URL", help="use a specific database")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--reinstall", action="store_true", help="reinstall dependencies from scratch"
    )
    args = parser.parse_args()

    check_python_version()
    _install_signal_handlers()
    python = ensure_backend_environment(force=args.reinstall)

    env = os.environ.copy()
    env.setdefault("ENVIRONMENT", "development")
    env.setdefault("PYTHONUNBUFFERED", "1")

    if args.check:
        # Checks run against the configured database, exactly as CI does.
        database_url, _ = resolve_database(python, args)
        env["DATABASE_URL"] = database_url
        env["AI_PROVIDER"] = env.get("AI_PROVIDER", "mock")
        return run_checks(python, env, args)

    database_url, label = resolve_database(python, args)
    env["DATABASE_URL"] = database_url

    if args.reset_db:
        step("Resetting the database")
        if database_url == SQLITE_URL:
            SQLITE_FILE.unlink(missing_ok=True)
            info("Removed the local SQLite file.")
        else:
            reset = subprocess.run(
                [
                    str(python),
                    "-c",
                    "import sys\n"
                    "from app.db import Base, engine\n"
                    "import app.models  # noqa: F401\n"
                    "Base.metadata.drop_all(bind=engine)\n",
                ],
                cwd=BACKEND,
                env=env,
            )
            if reset.returncode != 0:
                fail("Could not drop the existing tables.")
                return 1
            info("Dropped the existing tables.")

    # The application recreates the schema and reloads the synthetic seed data
    # on startup (AUTO_BOOTSTRAP), so nothing else is needed here.
    return serve(python, env, label, args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        fail(f"A setup command failed: {error}")
        sys.exit(1)
