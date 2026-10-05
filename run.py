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
    python run.py --no-local-model      skip the Ollama setup entirely
    python run.py --install-local-model install Ollama without asking

Nothing here changes how the application is built. It only automates the setup
steps documented in the README, so `uvicorn app.main:app` and `npm run dev`
still work exactly as before for anyone who prefers to run them by hand.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import socket
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
    # A teammate's existing environment has the core packages but not a tool
    # added later (a new test plugin, say), so the probe alone would pass and
    # `run.py --check` would then fail on the missing import. Recording what the
    # environment was installed from catches that and installs the difference.
    current = _requirements_hash()
    try:
        recorded = REQUIREMENTS_MARKER.read_text(encoding="utf-8").strip()
    except OSError:
        recorded = ""

    if probe.returncode != 0:
        step("Installing backend dependencies (first run only, this takes a minute)")
        subprocess.run(
            [str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip"],
            check=True,
        )
    elif recorded != current:
        step("Updating backend dependencies (the requirements files changed)")

    if probe.returncode != 0 or recorded != current:
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--quiet",
                "-r",
                str(BACKEND / "requirements-dev.txt"),
            ],
            check=True,
        )
        try:
            REQUIREMENTS_MARKER.write_text(current, encoding="utf-8")
        except OSError:
            pass

    return python


REQUIREMENTS_MARKER = VENV / ".requirements-hash"


def _requirements_hash() -> str:
    digest = hashlib.sha256()
    for name in ("requirements.txt", "requirements-dev.txt"):
        try:
            digest.update((BACKEND / name).read_bytes())
        except OSError:
            pass
    return digest.hexdigest()[:16]


# Windows installs npm as a batch file, so `npm` alone finds nothing unless the
# shell expands it; nvm-windows and fnm shims vary again. Try each spelling
# rather than reporting Node as missing on a machine that has it.
_NPM_NAMES = ("npm.cmd", "npm.exe", "npm") if IS_WINDOWS else ("npm",)


def _default_node_dirs() -> list[Path]:
    """Where the official installers put Node, in case PATH has not caught up.

    The Windows installer writes the system PATH, but a terminal -- or the
    editor that spawned it -- started before the install keeps the old
    environment until it is restarted, and people reasonably read "I installed
    Node" as "Node is installed". Looking in the standard places turns a
    confusing dead end into a working start.
    """
    if IS_WINDOWS:
        roots = [
            (os.environ.get("ProgramFiles") or r"C:\Program Files", "nodejs"),
            (os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)", "nodejs"),
            (os.environ.get("LOCALAPPDATA"), r"Programs\nodejs"),
            (os.environ.get("APPDATA"), "npm"),
        ]
        return [Path(root) / leaf for root, leaf in roots if root]
    return [Path(p) for p in ("/usr/local/bin", "/opt/homebrew/bin", "/usr/bin")]


def npm_command() -> str | None:
    for name in _NPM_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for directory in _default_node_dirs():
        for name in _NPM_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return None


def put_node_on_path() -> None:
    """Make sure the npm we found can reach its own node.

    npm is a wrapper that shells out to `node`, so an npm located outside PATH
    is useless on its own. This runs once at startup and prepends its
    directory to this process's PATH, which every child then inherits. It
    changes nothing when npm was on PATH already.
    """
    if any(shutil.which(name) for name in _NPM_NAMES):
        # Already reachable. Touching PATH here would only risk confusing npm
        # about where it is installed.
        return
    npm = npm_command()
    if npm is None:
        return
    directory = str(Path(npm).parent)
    os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")
    info(f"Found Node in {directory} (it was not on PATH).")


# node_modules holds compiled binaries for one operating system and CPU. A copy
# made on a different machine (or committed, or synced through a shared folder)
# leaves the platform packages Vite needs as empty directories, and the build
# fails with "Cannot find module '@rollup/rollup-<platform>'". The marker file
# records what the tree was built for so the mismatch is repaired automatically.
PLATFORM_MARKER = "node_modules/.install-platform"


def _platform_tag() -> str:
    return f"{platform.system()}-{platform.machine()}"


def _lock_hash() -> str:
    try:
        return hashlib.sha256((FRONTEND / "package-lock.json").read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _marker_value() -> str:
    """Platform the tree was built for, and the lockfile it was built from.

    The platform half catches node_modules copied between machines; the lockfile
    half catches a pull that added a package, which would otherwise surface as
    "Cannot find module" the first time a teammate runs the new script.
    """
    return f"{_platform_tag()}:{_lock_hash()}"


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
    (FRONTEND / PLATFORM_MARKER).write_text(_marker_value(), encoding="utf-8")


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

        if recorded == _marker_value():
            return
        recorded_platform = recorded.partition(":")[0]
        if recorded_platform == tag or (not recorded and _frontend_toolchain_loads()):
            # Right platform -- only the dependency list changed, or the tree
            # was installed by hand. An in-place install adds what is missing
            # without throwing away what is already there.
            step("Updating web client dependencies (package-lock.json changed)")
            _npm_install(npm)
            return

        step("Repairing web client dependencies")
        info(
            f"node_modules was installed for {recorded_platform or 'a different platform'}; "
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
    created = subprocess.run([str(python), "-c", script, server_url, database], capture_output=True)
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


# ---------------------------------------------------------------------------
# Ports
#
# A previous run that was not shut down cleanly -- a terminal window closed, a
# laptop put to sleep, a crash -- leaves its servers running in the background
# because each one runs in its own process group. The next run then fails with
# "Address already in use", and worse, the health check can succeed against the
# *old* server, so the launcher reports the API as ready when it is not. Every
# run therefore checks both ports first. A leftover from this project is
# stopped; anything else is reported and left alone.
# ---------------------------------------------------------------------------
def _port_in_use(port: int) -> bool:
    # Vite listens on "localhost", which is ::1 on recent macOS and Node, so
    # both address families are tried.
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                if probe.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def _listening_pids(port: int) -> list[int]:
    pids: set[int] = set()
    try:
        if IS_WINDOWS:
            output = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=10
            ).stdout
            for line in output.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0].upper() == "TCP"
                    and parts[1].endswith(f":{port}")
                    and parts[3].upper() == "LISTENING"
                    and parts[4].isdigit()
                ):
                    pids.add(int(parts[4]))
        else:
            lsof = shutil.which("lsof")
            if lsof is None:
                return []
            output = subprocess.run(
                [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            pids.update(int(pid) for pid in output.split() if pid.isdigit())
    except (OSError, subprocess.SubprocessError):
        return []
    pids.discard(os.getpid())
    return sorted(pids)


def _command_line(pid: int) -> str:
    try:
        if IS_WINDOWS:
            query = f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", query],
                capture_output=True,
                text=True,
                timeout=15,
            )
        else:
            result = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10
            )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _working_directory(pid: int) -> str:
    """Where the process was started. POSIX only; Windows relies on the command line."""
    lsof = shutil.which("lsof")
    if IS_WINDOWS or lsof is None:
        return ""
    try:
        output = subprocess.run(
            [lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    return next((line[1:] for line in output.splitlines() if line.startswith("n")), "")


def _is_ours(pid: int, command: str) -> bool:
    """A server this project started: our paths, our API module, or run from our folder."""
    lowered = command.lower()
    if str(ROOT).lower() in lowered or "app.main:app" in lowered:
        return True
    cwd = _working_directory(pid)
    return bool(cwd) and Path(cwd).resolve().is_relative_to(ROOT)


def _stop_pid(pid: int) -> None:
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        else:
            os.kill(pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        pass


def free_port(port: int, what: str) -> bool:
    """Make sure `port` is free, stopping a leftover run of this project if needed."""
    if not _port_in_use(port):
        return True

    kill_hint = (
        f"netstat -ano | findstr :{port}   then   taskkill /PID <pid> /F"
        if IS_WINDOWS
        else f"lsof -ti :{port} | xargs kill -9"
    )
    pids = _listening_pids(port)
    if not pids:
        fail(f"Port {port}, needed for the {what}, is already in use.")
        info(f"Free it with:  {kill_hint}")
        return False

    commands = {pid: _command_line(pid) for pid in pids}
    if not any(_is_ours(pid, command) for pid, command in commands.items()):
        pid, command = next(iter(commands.items()))
        fail(f"Port {port}, needed for the {what}, is in use by another program (pid {pid}).")
        if command:
            info(f"It is: {command[:100]}")
        info(f"Close that program, or free the port with:  {kill_hint}")
        return False

    step(f"Stopping a previous run that is still holding port {port}")
    info("(usually a terminal that was closed without Ctrl+C)")
    for pid in pids:
        _stop_pid(pid)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not _port_in_use(port):
            return True
        time.sleep(0.3)

    if not IS_WINDOWS:
        for pid in _listening_pids(port):
            try:
                os.kill(pid, FORCE_SIGNAL)
            except OSError:
                pass
        time.sleep(1)
    if _port_in_use(port):
        fail(f"Could not free port {port}.")
        info(f"Free it with:  {kill_hint}")
        return False
    return True


def _fetch_json(url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            loaded = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# ---------------------------------------------------------------------------
# The local language model
# ---------------------------------------------------------------------------
# The assistant answers through whatever provider resolves at runtime. Ollama
# is the one that needs software on the machine, so the launcher sets it up
# rather than printing instructions and leaving the reader to follow them: it
# finds Ollama, starts the daemon if it is installed but not running, and
# pulls the model if it has never been pulled. Downloading and running an
# installer is the one step it will not do on its own -- that is a decision
# about someone's computer, so it is asked for, and declining it simply falls
# back to the built-in advisor.
OLLAMA_PORT = 11434
OLLAMA_URL = f"http://127.0.0.1:{OLLAMA_PORT}"
OLLAMA_MODEL = "llama3.2"
OLLAMA_PAGE = "https://ollama.com/download"
OLLAMA_WINDOWS_INSTALLER = "https://ollama.com/download/OllamaSetup.exe"
OLLAMA_UNIX_SCRIPT = "https://ollama.com/install.sh"

# The model is about two gigabytes. A pull on a slow connection is slow, not
# broken, so the wait is generous and the download prints its own progress.
_PULL_TIMEOUT = 45 * 60
_DAEMON_TIMEOUT = 30


def _ollama_dirs() -> list[Path]:
    """Where the official installers put Ollama, in case PATH has not caught up."""
    if IS_WINDOWS:
        roots = [
            (os.environ.get("LOCALAPPDATA"), r"Programs\Ollama"),
            (os.environ.get("ProgramFiles") or r"C:\Program Files", "Ollama"),
        ]
        return [Path(root) / leaf for root, leaf in roots if root]
    return [
        Path(p)
        for p in (
            "/usr/local/bin",
            "/opt/homebrew/bin",
            "/usr/bin",
            "/Applications/Ollama.app/Contents/Resources",
        )
    ]


def ollama_command() -> str | None:
    name = "ollama.exe" if IS_WINDOWS else "ollama"
    found = shutil.which("ollama")
    if found:
        return found
    for directory in _ollama_dirs():
        candidate = directory / name
        if candidate.is_file():
            return str(candidate)
    return None


def _ollama_models() -> set[str] | None:
    """Model names the daemon reports, or None when it is not answering."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/v1/models", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    data = payload.get("data") if isinstance(payload, dict) else None
    names: set[str] = set()
    for entry in data or []:
        model_id = entry.get("id") if isinstance(entry, dict) else None
        if isinstance(model_id, str):
            names.add(model_id)
            # Ollama reports 'llama3.2:latest'; people write 'llama3.2'.
            names.add(model_id.split(":", 1)[0])
    return names


def _start_ollama(executable: str) -> bool:
    """Start the daemon in the background and wait for it to answer."""
    step("Starting the local model service")
    creation = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0  # type: ignore[attr-defined]
    try:
        subprocess.Popen(
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation,
        )
    except OSError as error:
        warn(f"Could not start Ollama: {error}")
        return False
    deadline = time.monotonic() + _DAEMON_TIMEOUT
    while time.monotonic() < deadline:
        if _ollama_models() is not None:
            return True
        time.sleep(0.5)
    warn("Ollama did not start in time.")
    return False


def _pull_model(executable: str, model: str) -> bool:
    step(f"Downloading the {model} model (about 2 GB, once)")
    info("This happens only the first time. Progress is printed below.")
    try:
        completed = subprocess.run([executable, "pull", model], timeout=_PULL_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as error:
        warn(f"The download did not finish: {error}")
        return False
    if completed.returncode != 0:
        warn(f"`ollama pull {model}` failed.")
        return False
    return True


def _agreed(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        # Nobody is there to answer, and installing software unattended is not
        # a decision this script gets to make for someone.
        return False
    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def _install_ollama(assume_yes: bool) -> str | None:
    """Offer to install Ollama, and return its path if it ends up installed."""
    info("Ollama is not installed. It runs the language model on this machine,")
    info("so nothing is sent anywhere and there is no account or key to set up.")
    if not _agreed(f"Download and install Ollama from {OLLAMA_PAGE}?", assume_yes):
        info(f"Skipping. You can install it yourself later from {OLLAMA_PAGE}.")
        return None

    if IS_WINDOWS:
        installer = Path(os.environ.get("TEMP") or ".") / "OllamaSetup.exe"
        step("Downloading the Ollama installer")
        try:
            urllib.request.urlretrieve(OLLAMA_WINDOWS_INSTALLER, installer)
        except (urllib.error.URLError, OSError) as error:
            warn(f"Download failed: {error}")
            return None
        step("Running the installer")
        try:
            subprocess.run([str(installer), "/VERYSILENT", "/NORESTART"], check=False)
        except OSError as error:
            warn(f"The installer did not run: {error}")
            return None
    elif platform.system() == "Darwin" and shutil.which("brew"):
        step("Installing Ollama with Homebrew")
        subprocess.run(["brew", "install", "ollama"], check=False)
    elif platform.system() == "Linux":
        step("Installing Ollama")
        subprocess.run(f"curl -fsSL {OLLAMA_UNIX_SCRIPT} | sh", shell=True, check=False)
    else:
        info(f"Automatic installation is not available here. Install it from {OLLAMA_PAGE}.")
        return None

    executable = ollama_command()
    if executable is None:
        warn("Ollama still was not found after installing.")
        info("Open a new terminal and run this script again -- PATH may be stale.")
    return executable


def ensure_local_model(args: argparse.Namespace) -> None:
    """Make the local model usable, quietly, before the API decides what to use.

    Everything here is best effort. A machine with no Ollama, no network or a
    declined install still starts the platform -- the assistant falls back to
    the built-in advisor, and `report_ai_provider` says so afterwards.
    """
    if getattr(args, "no_local_model", False):
        return
    configured = os.environ.get("AI_PROVIDER", "auto").strip().lower()
    if configured not in ("", "auto", "ollama"):
        # Someone has chosen a provider on purpose. Respect it.
        return

    model = os.environ.get("OLLAMA_MODEL", OLLAMA_MODEL)
    executable = ollama_command()
    if executable is None:
        executable = _install_ollama(getattr(args, "install_local_model", False))
        if executable is None:
            return

    models = _ollama_models()
    if models is None and not _start_ollama(executable):
        return
    if models is None:
        models = _ollama_models() or set()

    if model not in models and not _pull_model(executable, model):
        return
    info(f"Local model ready: {model}")


# How the assistant answers is the thing people most often get wrong about
# this platform ("why is it giving me the same paragraph?"), so the launcher
# says which provider the server actually resolved -- read back from
# /health rather than worked out a second time here, so the two can never
# disagree -- and, when it is the fallback, how to get a real model.
_OLLAMA_HINT = (
    "For answers from a real language model, install Ollama ({page}) and "
    "start this script again -- it will pull {model} for you."
)


def report_ai_provider(default_model: str = "llama3.2") -> None:
    dependencies = _fetch_json(f"{API_URL}/api/v1/health").get("dependencies")
    if not isinstance(dependencies, dict):
        return

    name = str(dependencies.get("ai_provider_name") or "")
    labels = {
        "builtin": "Built-in advisor (no key, keyword-routed)",
        "ollama": "Local model through Ollama",
        "anthropic": "Claude",
        "openai": "ChatGPT",
    }
    if not name:
        return

    info(f"Assistant: {labels.get(name, name)}")
    if name == "builtin":
        info(_OLLAMA_HINT.format(model=default_model, page=OLLAMA_PAGE))
        info("Nothing else to configure -- it is picked up automatically.")


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

    # The committed OpenAPI file has to match the code, or a reviewer reading
    # the pull request diff is reading a contract the server no longer serves.
    step("contract: docs/openapi.json is current")
    export = [str(python), str(ROOT / "scripts" / "export_openapi.py"), "--check"]
    if subprocess.run(export, cwd=ROOT, env=env).returncode != 0:
        failures.append("openapi contract")

    # The dependency diagram is generated from the imports, and no function
    # may grow past the complexity limit. Both run in CI as well.
    for label, script, extra in [
        ("architecture: module graph is current", "generate_module_graph.py", ["--check"]),
        ("quality: no function above complexity 15", "quality_report.py", ["--max-cc", "15"]),
    ]:
        step(label)
        command = [str(python), str(ROOT / "scripts" / script), *extra]
        if subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL).returncode != 0:
            failures.append(label.split(":")[0])

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
        ensure_local_model(args)

        if not free_port(API_PORT, "API"):
            return 1
        if not args.api_only and npm is not None and not free_port(WEB_PORT, "web client"):
            return 1

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

        api_started = wait_for(f"{API_URL}/api/v1/health")
        # A health response only counts if it came from the process just started.
        if not api_started or services[-1].process.poll() is not None:
            fail("The API did not start. The error should be printed above.")
            return 1
        info(f"API ready at {API_URL} (interactive docs at {API_URL}/docs)")
        report_ai_provider()

        serve_web = not args.api_only and npm is not None
        if args.api_only:
            info("Web client skipped (--api-only).")
        elif npm is None:
            warn("Node.js was not found, so the web interface cannot start.")
            info("The API below works, but the pages people actually use will not.")
            info("Install the LTS build from https://nodejs.org, open a new terminal")
            info("and run this script again.")

        if serve_web:
            ensure_frontend_environment(npm, force=args.reinstall)  # type: ignore[arg-type]
            step("Starting the web client")
            # --strictPort: fail loudly rather than drift to 5174 while the
            # browser is sent to 5173.
            web_command = [npm, "run", "dev", "--", "--strictPort"]
            services.append(Service("web", web_command, FRONTEND, env))  # type: ignore[list-item]
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
    else:
        print("  Web client     not running -- this is the API only")
    print()

    if not serve_web:
        # Saying "click Continue as a member" when there is no page to click on
        # is how someone ends up thinking the program is broken.
        print("  There is no sign-in page in this mode. What you can open is the")
        print("  API reference, where each endpoint has a 'Try it out' button.")
        print("  Start with POST /api/v1/auth/login and these accounts:")
    else:
        print("  Click 'Continue as a member' or 'Continue as a counsellor'.")
        print("  Or sign in by hand:")
    print(f"    member@example.com      {DEMO_PASSWORD}   (member chat)")
    print(f"    counselor@example.com   {DEMO_PASSWORD}   (counsellor dashboard)")
    print()
    if serve_web:
        print("  In the chat, try:")
        print('    "Which certification should I work toward next?"   -> answered')
        print('    "I want to speak to a human please"                -> handed to a counsellor')
        print('    "What is the capital of France?"                   -> unsupported topic')
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
    SystemExit so the cleanup in `serve()` runs on a kill, and SIGHUP -- what a
    terminal window sends when it is closed -- is handled the same way, so
    closing the window no longer leaves the servers running in the background.
    """
    try:
        signal.signal(signal.SIGINT, signal.default_int_handler)
    except (ValueError, OSError):
        pass

    def _terminate(_signum: int, _frame: object) -> None:
        raise SystemExit(0)

    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)  # SIGHUP does not exist on Windows
        if sig is None:
            continue
        try:
            signal.signal(sig, _terminate)
        except (ValueError, OSError):
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start SkillBridge AI locally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="run every check CI runs, then exit")
    parser.add_argument("--reset-db", action="store_true", help="start from an empty database")
    parser.add_argument("--api-only", action="store_true", help="skip the web client")
    parser.add_argument("--postgres", action="store_true", help="require PostgreSQL")
    parser.add_argument("--db-url", metavar="URL", help="use a specific database")
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument(
        "--no-local-model",
        action="store_true",
        help="do not set up Ollama; use the built-in advisor",
    )
    parser.add_argument(
        "--install-local-model",
        action="store_true",
        help="install Ollama without asking first",
    )
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

    put_node_on_path()
    env["PATH"] = os.environ["PATH"]

    if args.check:
        # Checks run against the configured database, exactly as CI does.
        database_url, _ = resolve_database(python, args)
        env["DATABASE_URL"] = database_url
        env["AI_PROVIDER"] = env.get("AI_PROVIDER", "builtin")
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
