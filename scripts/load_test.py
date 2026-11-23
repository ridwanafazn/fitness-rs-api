"""Small dependency-free HTTP load test.

Examples:

    python scripts/load_test.py --path /health --requests 500 --concurrency 50
    python scripts/load_test.py --path /ready --requests 200 --concurrency 20
    python scripts/load_test.py --method POST --path /api/v1/recommendation/ \
        --body-file payload.json --requests 50 --concurrency 5 --max-p95-ms 2000

This is a smoke load test, not a capacity benchmark. Do not run it against a
shared production host without permission.
"""

from __future__ import annotations

import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple


def percentile(values: List[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small HTTP load test.")
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--path", default="/health")
    parser.add_argument("--method", default="GET")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--body-file", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=0.0)
    args = parser.parse_args()

    total = max(1, args.requests)
    concurrency = max(1, min(args.concurrency, total))
    body: Optional[bytes] = None
    if args.body_file:
        with open(args.body_file, "rb") as handle:
            body = handle.read()
    headers = {"Content-Type": "application/json", "Connection": "close"}
    if args.api_key:
        headers["X-API-Key"] = args.api_key

    target = urllib.parse.urlsplit(
        args.url.rstrip("/") + "/" + args.path.lstrip("/")
    )
    if target.scheme not in {"http", "https"} or not target.hostname:
        print("URL must be http(s) with a host.", file=sys.stderr)
        return 2
    request_path = target.path or "/"
    if target.query:
        request_path = f"{request_path}?{target.query}"
    port = target.port or (443 if target.scheme == "https" else 80)

    latencies: List[float] = []
    statuses: Dict[str, int] = {}
    errors: Dict[str, int] = {}

    def one_request() -> Tuple[int, float, Optional[str]]:
        started = time.perf_counter()
        connection: Optional[http.client.HTTPConnection] = None
        try:
            if target.scheme == "https":
                connection = http.client.HTTPSConnection(
                    target.hostname, port, timeout=args.timeout
                )
            else:
                connection = http.client.HTTPConnection(
                    target.hostname, port, timeout=args.timeout
                )
            connection.request(
                args.method.upper(),
                request_path,
                body=body,
                headers=headers,
            )
            response = connection.getresponse()
            response.read()
            return response.status, (time.perf_counter() - started) * 1000, None
        except Exception as exc:
            return 0, (time.perf_counter() - started) * 1000, type(exc).__name__
        finally:
            if connection is not None:
                connection.close()

    wall_start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(one_request) for _ in range(total)]
        for future in as_completed(futures):
            code, elapsed, error = future.result()
            latencies.append(elapsed)
            key = str(code)
            statuses[key] = statuses.get(key, 0) + 1
            if error:
                errors[error] = errors.get(error, 0) + 1
    wall_seconds = max(0.001, time.perf_counter() - wall_start)
    error_count = sum(count for code, count in statuses.items() if not code.startswith("2"))
    error_rate = error_count / total

    summary = {
        "target": urllib.parse.urlunsplit(target),
        "requests": total,
        "concurrency": concurrency,
        "wall_seconds": round(wall_seconds, 3),
        "requests_per_second": round(total / wall_seconds, 2),
        "status_counts": statuses,
        "error_count": error_count,
        "error_rate": round(error_rate, 4),
        "errors": errors,
        "latency_ms": {
            "min": round(min(latencies), 2) if latencies else None,
            "p50": round(percentile(latencies, 0.50), 2) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 2) if latencies else None,
            "p99": round(percentile(latencies, 0.99), 2) if latencies else None,
            "max": round(max(latencies), 2) if latencies else None,
            "mean": round(statistics.fmean(latencies), 2) if latencies else None,
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))

    if error_rate > args.max_error_rate:
        print(
            f"error rate {error_rate:.2%} exceeds {args.max_error_rate:.2%}",
            file=sys.stderr,
        )
        return 1
    p95 = summary["latency_ms"]["p95"]
    if args.max_p95_ms > 0 and p95 is not None and p95 > args.max_p95_ms:
        print(f"p95 {p95}ms exceeds {args.max_p95_ms}ms", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
