"""Monitoring and Logging endpoints (Infrastructure Layer).

ALPHA SCOPE -- barebones. Counters are collected in process and read back
through this endpoint. A production deployment exports them to a monitoring
system instead; this endpoint is what proves the component exists and is wired
to the live request path.

Agent role required: operational figures are not customer-facing.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.models import User
from app.modules.cache.service import get_cache
from app.modules.monitoring.service import get_metrics
from app.security import require_agent

router = APIRouter(prefix="/api/v1/ops", tags=["ops"])


@router.get("/metrics")
def metrics(agent: User = Depends(require_agent)) -> dict[str, Any]:
    """Request, conversation and latency counters for this instance.

    Figures are per-instance by design. Behind a load balancer each instance
    reports its own, which `instanceId` makes explicit rather than implying a
    cluster-wide total.
    """
    snapshot = get_metrics().snapshot()
    cache = get_cache()
    snapshot["cache"] = {"implementation": cache.name, **cache.stats().as_dict()}
    return snapshot
