"""Small custom Prometheus metrics for operational visibility."""

from __future__ import annotations

from prometheus_client import Counter

RATE_LIMIT_DEGRADED_TOTAL = Counter(
    "jymz_rate_limit_degraded_total",
    "Requests served while the rate-limit backend was unavailable.",
)
