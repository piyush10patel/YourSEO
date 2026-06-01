"""Prometheus metrics (spec §28: observability).

Exposes request throughput/latency plus domain counters (crawls, audits, agent
runs). Scrape at GET /metrics; visualize in Prometheus/Grafana. Langfuse/Sentry
/OpenTelemetry are complementary and can be layered via config later.
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "seoos_requests_total",
    "HTTP requests",
    ["method", "path", "status"],
)
LATENCY = Histogram(
    "seoos_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)

# Domain counters.
CRAWLS = Counter("seoos_crawls_total", "Site crawls run")
AUDITS = Counter("seoos_audits_total", "Audits run")
AGENT_RUNS = Counter("seoos_agent_runs_total", "Agent runs", ["agent"])


def _route(request: Request) -> str:
    """Use the route template (e.g. /projects/{id}) to avoid high cardinality."""
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    path = _route(request)
    LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    REQUESTS.labels(request.method, path, response.status_code).inc()
    return response


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
