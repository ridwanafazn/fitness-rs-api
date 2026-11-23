# P2.3 — Scale and reliability

**Status:** implemented behind `OPS_ENABLED=false` for the admin status endpoint.
Worker, pool, rate-limit, load-test, and restore-verification pieces are
available without the flag.

This is still a free hobby/research deployment. P2.3 is about honest
single-service reliability, not a claim of production-grade HA or a paid SLO.

## What changed

- Postgres pool/connect settings are configurable.
- Redis is a supported rate-limit backend with fail-open/fail-closed behavior.
- `/ready` reports database and Redis state without making Redis fatal.
- The notification outbox has a worker lease, so parallel workers do not
  normally process the same row.
- A long-running worker script runs reminders + outbox cycles with graceful
  shutdown.
- A platform-admin `/admin/ops/status` endpoint and `scripts/ops_status.py`
  expose DB/migration/outbox/Redis state.
- `scripts/load_test.py` provides a dependency-free smoke load test.
- `scripts/verify_restore.py` validates a restored database before cutover.
- SLO/alert/runbook/backup procedures are documented below.

## Database resilience

```text
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
DB_POOL_TIMEOUT_SECONDS=10
DB_POOL_RECYCLE_SECONDS=1800
DB_CONNECT_TIMEOUT_SECONDS=5
```

- `pool_pre_ping` is always on for Postgres.
- `pool_timeout` prevents requests from waiting forever for a connection.
- `pool_recycle` avoids stale connections through a pooler.
- Keep pool size modest on Neon free/starter; many app instances multiply the
  pool.
- SQLite ignores these settings and remains single-writer/local/test-only.

## Redis and rate limiting

Default is in-process memory:

```text
RATE_LIMIT_STORAGE_URI=memory://
```

For multiple instances/workers, use a shared Redis:

```text
RATE_LIMIT_STORAGE_URI=redis://default:password@host:6379/0
RATE_LIMIT_FAIL_OPEN=true
```

- `redis==8.1.0` is a runtime dependency.
- `RATE_LIMIT_FAIL_OPEN=true` (default): if Redis is down, serve traffic with
  `X-RateLimit-Degraded: 1` and increment
  `jymz_rate_limit_degraded_total`.
- `RATE_LIMIT_FAIL_OPEN=false`: return `503 rate_limit_unavailable` instead.
- `/ready` reports `redis: ok|unavailable|not_configured`; Redis being down is
  reported as `degraded` but does not make the whole API unready.
- A malformed storage URI or missing Redis client does not prevent startup; the
  limiter degrades according to `RATE_LIMIT_FAIL_OPEN`.

## Outbox worker lease

Migration `0010_outbox_lease` adds:

```text
notification_outbox.locked_until
notification_outbox.locked_by
```

Processing:

1. Select due `pending`/`failed` rows whose lease is free.
2. On Postgres use `SELECT ... FOR UPDATE SKIP LOCKED`.
3. Set `locked_until = now + lease` and `locked_by`, then commit.
4. Deliver each row.
5. Clear the lease and commit final statuses.

Properties:

- Postgres workers skip rows locked by another worker.
- A crashed worker's lease expires after
  `NOTIFICATION_OUTBOX_LEASE_SECONDS` (default 300) and the row becomes
  claimable again.
- Delivery is **at-least-once**; a crash after external delivery but before the
  final commit can duplicate a notification. Keep delivery idempotent.
- SQLite remains effectively single-worker; do not run multiple SQLite workers.

Run the worker:

```bash
DATABASE_URL=... NOTIFICATIONS_ENABLED=true \
  python scripts/worker.py --interval 30 --limit 100
```

One-shot cron:

```bash
DATABASE_URL=... NOTIFICATIONS_ENABLED=true \
  python scripts/worker.py --once --limit 100
```

### SLO targets

These are targets for a single small instance, not guarantees:

| SLO | Target |
|---|---|
| Availability (`/ready` 200) | 99.0% monthly |
| `/health` p95 | < 50 ms |
| `/ready` p95 | < 500 ms |
| Recommendation p95 | < 5 s (GA/CPU-dependent) |
| 5xx error rate | < 1% over 5 minutes |
| Outbox due backlog | < 100 rows and oldest due < 5 minutes |
| Redis outage response | fail-open, no 5xx increase |

### Alerts

| Signal | Warning | Critical |
|---|---|---|
| `/ready` failure | 3 consecutive | 10 consecutive |
| 5xx rate | > 2% for 5 min | > 5% for 5 min |
| p95 latency | > 2× baseline for 10 min | > 5× baseline for 10 min |
| Outbox `due_pending` | > 100 | > 500 or oldest > 30 min |
| Redis | `unavailable` > 5 min | sustained + fail-closed |
| DB pool timeout errors | any | repeated for 5 min |
| Host memory/disk | > 80% | > 90% |

Alerts can scrape `/ready`, `/metrics`, or run `scripts/ops_status.py` in a
scheduled job. The ops script exits non-zero when degraded.

## Operational status

```text
OPS_ENABLED=true
```

`GET /api/v1/admin/ops/status` (platform admin) returns:

- environment, app version, generated time;
- dataset version/size;
- database status and Alembic head;
- Redis status/detail, rate-limit backend, fail-open flag;
- outbox counts (`pending`, `failed`, `sent`, `cancelled`), due backlog,
  oldest due, last sent.

CLI:

```bash
DATABASE_URL=... python scripts/ops_status.py
```

The CLI prints JSON and exits `1` when status is degraded.

## Load test

Dependency-free smoke test:

```bash
python scripts/load_test.py --path /health --requests 500 --concurrency 50
python scripts/load_test.py --path /ready --requests 200 --concurrency 20
python scripts/load_test.py --method POST --path /api/v1/recommendation/ \
  --body-file payload.json --requests 50 --concurrency 5 --max-p95-ms 5000
```

- Use `--max-error-rate` / `--max-p95-ms` for pass/fail thresholds.
- Do not run it against shared production without permission.
- It measures HTTP latency; it is not a capacity-planning benchmark.
- A local 50-concurrent `/health` run proves concurrency handling, not Neon or
  GA capacity.

## Backup and restore

The repository does not implement backups. Use the database provider:

1. Confirm Neon retention/PITR for the plan.
2. Create a branch/snapshot before risky migrations or bulk changes.
3. Restore into a **new branch**, never over the live branch.
4. Verify the restored branch:

```bash
TARGET_DATABASE_URL=postgresql://... \
  python scripts/verify_restore.py --expect-head 0010_outbox_lease
```

`verify_restore.py` checks the Alembic head, required tables, and counts for
`users`, `plans`, `workout_sessions`, and `audit_log`. It does not prove
application correctness; also run a `/ready` + login/plan smoke test against a
temporary deployment pointed at the restored branch.

Cutover:

1. Stop writers/workers.
2. Restore/point at the verified branch.
3. Run `alembic upgrade head` if the restore is behind.
4. Start the API and worker.
5. Verify `/ready`, `ops/status`, login, plan create, and outbox processing.

## Runbook

### API not ready

1. Check `/ready` body and platform health event.
2. If `database_unavailable`, check Neon status/connection limits and
   `DATABASE_URL`.
3. If dataset not loaded, check container logs and `DATASET_PATH`.
4. If Redis is `unavailable`, the API should still serve with degraded rate
   limiting; fix Redis in parallel.

### Redis down

1. Confirm `/ready` says `redis: unavailable` and `degraded: true`.
2. Expect `X-RateLimit-Degraded: 1` on API responses while fail-open is enabled.
3. Restore Redis or switch `RATE_LIMIT_STORAGE_URI=memory://` temporarily for a
   single instance.
4. Do not set `RATE_LIMIT_FAIL_OPEN=false` during an outage unless rejecting
   traffic is intended.

### Outbox backlog

1. Run `python scripts/ops_status.py`.
2. Check worker logs for `worker_cycle_failed`.
3. Run one cycle manually:
   `python scripts/worker.py --once --limit 100`.
4. If rows remain locked, wait for the lease to expire or inspect
   `locked_until`/`locked_by`; do not mass-update blindly.
5. If delivery provider is down, rows retry with exponential backoff up to
   `max_attempts`.

### High latency

1. Compare `/health` (infra) vs `/ready` (DB) vs recommendation latency.
2. Check DB pool timeouts, Neon CPU/connections, and GA request size.
3. Reduce concurrency or scale the instance; never increase workers for a
   CPU-bound GA without measuring.
4. Check `X-Process-Time` and structured access logs.

### Deploy and rollback

1. Build the image, run tests, apply migrations.
2. Deploy one instance; check `/ready` and `/admin/ops/status`.
3. Roll back the image if error rate/latency regresses; migrations should be
   backward-compatible for one release.
4. For a bad migration, restore a Neon branch and point `DATABASE_URL` at it
   after verification.

## Known limitations

- No repository-managed backups; backup/PITR is provider-dependent.
- No read-replica routing; Neon replicas are not wired into the app.
- No OpenTelemetry exporter. Observability is request IDs, structured logs,
  Prometheus HTTP metrics, `/ready`, and the ops status endpoint.
- No distributed tracing across worker and API.
- No multi-region or Kubernetes; one modular monolith is intentional.
- Outbox delivery is at-least-once, not exactly-once.
- The load test is a smoke test, not a benchmark suite.
- Redis is optional; without it, rate limiting is per-process.
- The SLO targets are informal for a hobby deployment.
