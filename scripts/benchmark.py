"""HTTP performance benchmark for a running SkillBridge AI instance.

OWNER: Ravonne Wade (Lead Architect)

Measures latency percentiles and throughput for the operations a member and a
counsellor actually perform, against the five-second response target in the
System Design Specification. It talks to the server over HTTP exactly as the
web client does, so the numbers include routing, authentication, validation,
database round trips and serialisation -- not just the function under test.

Standard library only, so it runs anywhere the backend runs.

Usage
-----
Start a server with the per-member message limit raised, or the conversation
benchmark measures the rate limiter instead of the platform:

    cd backend
    RATE_LIMIT_MESSAGES_PER_MINUTE=100000 python -m uvicorn app.main:app --port 8001

Then, from the repository root:

    python scripts/benchmark.py --base-url http://127.0.0.1:8001
    python scripts/benchmark.py --requests 400 --concurrency 20 --markdown results.md

The script exits non-zero if any scenario's p95 exceeds the target or any
request fails, so it can gate a pipeline when that is wanted.
"""

import argparse
import json
import os
import platform
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

TARGET_MS = 5000.0
PASSWORD = os.environ.get("SEED_PASSWORD", "DemoPassw0rd!")
QUESTION = "Which certification should I work toward next?"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def call(
        self, method: str, path: str, token: str | None = None, body: object | None = None
    ) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")

    def login(self, email: str) -> str:
        status, body = self.call(
            "POST", "/api/v1/auth/login", body={"email": email, "password": PASSWORD}
        )
        if status != 200 or not isinstance(body, dict):
            raise SystemExit(f"Could not sign in as {email} (HTTP {status}). Is the data seeded?")
        return str(body["accessToken"])


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------
@dataclass
class Result:
    name: str
    description: str
    latencies_ms: list[float] = field(default_factory=list)
    failures: dict[int, int] = field(default_factory=dict)
    wall_seconds: float = 0.0

    @property
    def count(self) -> int:
        return len(self.latencies_ms) + sum(self.failures.values())

    def percentile(self, p: float) -> float:
        ordered = sorted(self.latencies_ms)
        if not ordered:
            return 0.0
        # Nearest-rank: the value at or below which p% of requests fall.
        rank = max(1, round(p / 100 * len(ordered)))
        return ordered[rank - 1]

    @property
    def throughput(self) -> float:
        return len(self.latencies_ms) / self.wall_seconds if self.wall_seconds else 0.0

    @property
    def within_target(self) -> bool:
        return not self.failures and self.percentile(95) <= TARGET_MS


def run(
    name: str,
    description: str,
    operation: Callable[[int], int],
    requests: int,
    concurrency: int,
    expect: int,
) -> Result:
    """Run `operation(i)` `requests` times across `concurrency` threads."""
    result = Result(name, description)
    lock = threading.Lock()

    def one(i: int) -> None:
        started = time.perf_counter()
        status = operation(i)
        elapsed = (time.perf_counter() - started) * 1000
        with lock:
            if status == expect:
                result.latencies_ms.append(elapsed)
            else:
                result.failures[status] = result.failures.get(status, 0) + 1

    wall = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, range(requests)))
    result.wall_seconds = time.perf_counter() - wall
    return result


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def scenarios(client: Client, requests: int, concurrency: int) -> list[Result]:
    member = client.login("member@example.com")
    counsellor = client.login("counselor@example.com")

    # One conversation per worker thread, so concurrent turns do not queue
    # behind each other on a single conversation row.
    conversations: list[str] = []
    for _ in range(concurrency):
        status, body = client.call("POST", "/api/v1/conversations", member)
        assert status == 201 and isinstance(body, dict), f"could not open a conversation ({status})"
        conversations.append(str(body["conversationId"]))

    def turn(i: int) -> int:
        conversation = conversations[i % len(conversations)]
        status, _ = client.call(
            "POST",
            f"/api/v1/conversations/{conversation}/messages",
            member,
            {"message": QUESTION},
        )
        return status

    def history(i: int) -> int:
        return client.call(
            "GET", f"/api/v1/conversations/{conversations[i % len(conversations)]}", member
        )[0]

    # Signing in is deliberately slow (bcrypt), so it gets fewer requests.
    login_requests = max(10, requests // 10)

    plan: list[tuple[str, str, Callable[[int], int], int, int]] = [
        (
            "Health check",
            "GET /api/v1/health -- database ping included",
            lambda i: client.call("GET", "/api/v1/health")[0],
            requests,
            200,
        ),
        (
            "Sign in",
            "POST /api/v1/auth/login -- bcrypt password check",
            lambda i: client.call(
                "POST",
                "/api/v1/auth/login",
                body={"email": "member@example.com", "password": PASSWORD},
            )[0],
            login_requests,
            200,
        ),
        (
            "Conversation turn",
            "POST .../messages -- the full pipeline with the mock provider",
            turn,
            requests,
            200,
        ),
        ("Conversation history", "GET /api/v1/conversations/{id}", history, requests, 200),
        (
            "Pathway recommendations",
            "GET /api/v1/pathways/recommended -- TF-IDF ranking",
            lambda i: client.call("GET", "/api/v1/pathways/recommended", member)[0],
            requests,
            200,
        ),
        (
            "Counsellor queue",
            "GET /api/v1/agent/cases",
            lambda i: client.call("GET", "/api/v1/agent/cases", counsellor)[0],
            requests,
            200,
        ),
    ]

    results = []
    for name, description, operation, count, expect in plan:
        # A short warm-up so first-call costs (imports, pool creation, caches)
        # are not reported as the platform's steady state.
        for i in range(min(5, count)):
            operation(i)
        results.append(run(name, description, operation, count, concurrency, expect))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def table(results: list[Result]) -> str:
    lines = [
        "| Scenario | Requests | p50 ms | p95 ms | p99 ms | Max ms | Req/s | Failures "
        "| Within 5 s target |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |",
    ]
    for r in results:
        failures = ", ".join(f"{count}× HTTP {code}" for code, count in r.failures.items()) or "0"
        maximum = max(r.latencies_ms) if r.latencies_ms else 0.0
        lines.append(
            f"| {r.name} | {r.count} | {r.percentile(50):.1f} | {r.percentile(95):.1f} | "
            f"{r.percentile(99):.1f} | {maximum:.1f} | {r.throughput:.1f} | {failures} | "
            f"{'yes' if r.within_target else '**no**'} |"
        )
    return "\n".join(lines)


def environment(base_url: str, concurrency: int, health: object) -> str:
    engine = provider = "unknown"
    if isinstance(health, dict):
        dependencies = health.get("dependencies", {})
        engine = dependencies.get("database_engine", engine)
        provider = dependencies.get("ai_provider_name", provider)
    return (
        f"- Target: `{base_url}` · database `{engine}` · AI provider `{provider}`\n"
        f"- Client: Python {platform.python_version()} on {platform.system()} "
        f"{platform.machine()}, {os.cpu_count()} CPUs, {concurrency} concurrent workers\n"
        f"- Run at: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark a running SkillBridge AI instance.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--requests", type=int, default=200, help="requests per scenario")
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--markdown", help="also write the results table to this file")
    args = parser.parse_args()

    client = Client(args.base_url)
    status, health = client.call("GET", "/api/v1/health")
    if status != 200:
        print(f"No healthy server at {args.base_url} (HTTP {status}).", file=sys.stderr)
        return 2

    results = scenarios(client, args.requests, args.concurrency)
    report = f"{environment(args.base_url, args.concurrency, health)}\n\n{table(results)}\n"
    print(report)

    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as handle:
            handle.write(report)

    slowest = max(results, key=lambda r: r.percentile(95))
    print(
        f"Slowest p95: {slowest.name} at {slowest.percentile(95):.1f} ms "
        f"({statistics.mean(slowest.latencies_ms or [0]):.1f} ms mean)."
    )
    return 0 if all(r.within_target for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
