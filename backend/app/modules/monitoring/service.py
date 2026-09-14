"""Monitoring and Logging (Infrastructure Layer).

ALPHA SCOPE -- barebones. The counters are real and updated by the live request
path, but they live in process memory and are reported through one endpoint
rather than exported to a monitoring system.

The diagram shows this component observing the Conversation Management and AI
Integration modules. It does that by being called from them, so it never
reaches into their internals.

What is deliberately NOT built yet: export to a metrics backend, alerting,
distributed tracing across instances, and log shipping. Because counters are
per-process, a horizontally scaled deployment would report per-instance
figures -- `instanceId` in the payload makes that explicit rather than
misleading.
"""

import os
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _instance_id() -> str:
    """Identify this application instance behind the load balancer."""
    host = getattr(os, "uname", None)
    prefix = os.uname().nodename[:12] if host else "instance"
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


INSTANCE_ID = _instance_id()


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.monotonic)
    requests_total: int = 0
    requests_by_status: Counter[str] = field(default_factory=Counter)
    turns_by_status: Counter[str] = field(default_factory=Counter)
    escalations_by_reason: Counter[str] = field(default_factory=Counter)
    turn_latencies_ms: list[int] = field(default_factory=list)
    slow_turns: int = 0

    def record_request(self, status_code: int) -> None:
        self.requests_total += 1
        self.requests_by_status[f"{status_code // 100}xx"] += 1

    def record_turn(self, status: str, latency_ms: int, escalation_reason: str | None) -> None:
        self.turns_by_status[status] += 1
        if escalation_reason:
            self.escalations_by_reason[escalation_reason] += 1
        # Bounded so a long-running process cannot grow without limit.
        self.turn_latencies_ms.append(latency_ms)
        if len(self.turn_latencies_ms) > 500:
            del self.turn_latencies_ms[:-500]

    def record_slow_turn(self) -> None:
        self.slow_turns += 1

    def _percentile(self, fraction: float) -> int:
        if not self.turn_latencies_ms:
            return 0
        ordered = sorted(self.turn_latencies_ms)
        index = min(len(ordered) - 1, int(len(ordered) * fraction))
        return ordered[index]

    def snapshot(self) -> dict[str, Any]:
        turns = sum(self.turns_by_status.values())
        return {
            "instanceId": INSTANCE_ID,
            "collectedAt": datetime.now(timezone.utc).isoformat(),
            "uptimeSeconds": int(time.monotonic() - self.started_at),
            "requests": {
                "total": self.requests_total,
                "byStatusClass": dict(self.requests_by_status),
            },
            "conversationTurns": {
                "total": turns,
                "byStatus": dict(self.turns_by_status),
                "escalationsByReason": dict(self.escalations_by_reason),
                "escalationRate": (
                    round(self.turns_by_status.get("ESCALATED", 0) / turns, 3) if turns else 0.0
                ),
            },
            "latencyMs": {
                "p50": self._percentile(0.50),
                "p95": self._percentile(0.95),
                "max": max(self.turn_latencies_ms) if self.turn_latencies_ms else 0,
                "overFiveSecondTarget": self.slow_turns,
            },
        }


_metrics = Metrics()


def get_metrics() -> Metrics:
    return _metrics


def reset_metrics() -> None:
    global _metrics
    _metrics = Metrics()
