"""Simple in-process latency benchmark.

Usage:
    python scripts/benchmark.py --requests 20 --days 4
"""

from __future__ import annotations

import argparse
import statistics
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((pct / 100) * (len(ordered) - 1))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--days", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings(
        environment="test",
        log_level="WARNING",
        dataset_path=PROJECT_ROOT / "data" / "fitness_dataset.csv",
        rate_limit_enabled=False,
        metrics_enabled=False,
    )
    app = create_app(settings)
    payload = {
        "gender": "male",
        "height_cm": 175,
        "weight_kg": 72,
        "injuries": [],
        "available_days": args.days,
        "preferred_body_part": ["chest"],
        "preferred_equipment": ["dumbbell", "barbell"],
        "seed": args.seed,
    }

    latencies: list[float] = []
    with TestClient(app) as client:
        # Warm-up: dataset load + one GA run.
        client.post("/api/v1/recommendation/", json=payload)
        for _ in range(args.requests):
            start = time.perf_counter()
            response = client.post("/api/v1/recommendation/", json=payload)
            elapsed_ms = (time.perf_counter() - start) * 1000
            if response.status_code != 201:
                raise SystemExit(response.text)
            latencies.append(elapsed_ms)

    print(f"requests={len(latencies)} days={args.days}")
    print(f"min={min(latencies):.1f} ms")
    print(f"p50={statistics.median(latencies):.1f} ms")
    print(f"p95={percentile(latencies, 95):.1f} ms")
    print(f"max={max(latencies):.1f} ms")
    print(f"mean={statistics.mean(latencies):.1f} ms")


if __name__ == "__main__":
    main()
