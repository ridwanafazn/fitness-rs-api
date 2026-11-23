# Deployment guide

## Canonical target: always-on container

The current blueprint uses Render (`render.yaml`), but **Render free sleeps and
causes cold starts**. For a public deployment, use an always-on host. See
[`hosting.md`](hosting.md) for the free/PAYG comparison and a Fly.io example.

The health check must be `/ready` because that endpoint verifies the exercise
dataset and, when configured, the database.

## Environment variables

Set these in the platform dashboard:

- `ENVIRONMENT=production`
- `CORS_ORIGINS=https://jymz.pages.dev` (use exact origins; `*` is temporary)
- `ALLOWED_HOSTS=your-api.example` (include the platform health-check hostname,
  or leave `*` if the platform uses a host you cannot enumerate)
- `API_KEY=...` (optional but recommended for the public recommendation API)
- `TRUST_PROXY_HEADERS=true`
- `RATE_LIMIT=120/minute`
- `RATE_LIMIT_STORAGE_URI=redis://...` if you run more than one instance
- `REQUEST_TIMEOUT_SECONDS=15`

P0.1 database and auth:

- `DATABASE_URL=postgresql://...` (the app converts it to psycopg 3)
- `DB_AUTO_CREATE=false`
- `AUTH_ENABLED=false` and `AUTH_PROFILES_ENABLED=false` until the OIDC provider
  and frontend onboarding are ready
- When enabling with Neon Auth:
  - `AUTH_ENABLED=true`
  - `AUTH_PROFILES_ENABLED=true`
  - `NEON_AUTH_BASE_URL=https://<host>/<db>/auth`
  - `AUTH_ALGORITHMS=EdDSA`
  - explicit `AUTH_ISSUER`, `AUTH_AUDIENCE`, `AUTH_JWKS_URL` are derived from
    `NEON_AUTH_BASE_URL`; override only if needed
- `CONSENT_POLICY_VERSION=2026-01`
- `ACCOUNT_DELETION_GRACE_DAYS=30`

P0.2 plans:

- `PLANS_ENABLED=true` only after bearer auth and frontend
  `Idempotency-Key` handling are ready.
- `PLANS_ENABLED` requires `AUTH_PROFILES_ENABLED=true` and a database.

P0.3 workouts:

- `WORKOUTS_ENABLED=true` only after the frontend can queue offline mutations.
- `WORKOUTS_ENABLED` requires `PLANS_ENABLED=true` and a database.

P0.4 feedback/safety:

- `FEEDBACK_ENABLED=true` to mount feedback, safety-report, and admin endpoints.
- `FEEDBACK_RATE_LIMIT_PER_HOUR` and `SAFETY_REPORT_RATE_LIMIT_PER_HOUR` are
  per-user limits.
- `ALERT_WEBHOOK_URL` is optional; critical reports use it with a PII-free
  payload.
- Seed `platform_admin` manually; see `p0-4-feedback-and-safety.md`.

P1.1 progress:

- `PROGRESS_ENABLED=true` after workouts are live.
- Requires `WORKOUTS_ENABLED=true` and a database.
- Rebuild-on-read keeps aggregates consistent; `scripts/rebuild_progress.py`
  supports backfill.

P1.2 trainer:

- `TRAINER_ENABLED=true` to mount trainer/client trainer endpoints.
- Requires `PLANS_ENABLED=true`.
- Seed the `trainer` role manually; see `p1-2-trainer-workspace.md`.
- Invite delivery is manual until P1.3 notifications.

P1.3 notifications:

- `NOTIFICATIONS_ENABLED=true` to mount preferences/devices/calendar/integrations.
- `NOTIFICATION_DELIVERY_MODE=log|webhook|disabled`.
- `NOTIFICATION_WEBHOOK_URL` is required for webhook mode.
- `TOKEN_ENCRYPTION_KEY` is a Fernet key for device/integration tokens.
- `INTEGRATION_STATE_SECRET` signs OAuth state and unsubscribe tokens.
- Run `python scripts/process_outbox.py` as a worker.

P2.1 organizations (free):

- `ORGANIZATIONS_ENABLED=true` to mount organization/membership endpoints.
- Requires `AUTH_PROFILES_ENABLED=true`.
- No billing/payment/seat configuration exists by design.
- Organization membership does not grant health-data access; P1.2 scopes still
  apply.

P2.2 research:

- `RESEARCH_ENABLED=true` to mount event/experiment/report/export endpoints.
- `RESEARCH_EXPORT_SECRET` (32+ chars) is required for exports; without it the
  export endpoint returns `503`.
- `RESEARCH_EVENT_RATE_LIMIT_PER_HOUR` defaults to 200.
- User-facing endpoints require active `research_analytics` consent.
- Reports/exports use explicit windows (max 366 days).

P2.3 operations:

- `OPS_ENABLED=true` mounts `/api/v1/admin/ops/status`.
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT_SECONDS`,
  `DB_CONNECT_TIMEOUT_SECONDS`, and `DB_POOL_RECYCLE_SECONDS` tune Postgres.
- `RATE_LIMIT_STORAGE_URI=redis://...` enables shared limiting;
  `RATE_LIMIT_FAIL_OPEN=true` keeps serving during Redis outages.
- Run `python scripts/worker.py` as the notification/outbox worker.
- Use `python scripts/ops_status.py` for external monitoring.
- Backup/restore uses Neon PITR/branches; verify with
  `python scripts/verify_restore.py`.

See [`p2-3-scale-and-reliability.md`](p2-3-scale-and-reliability.md).

See [`neon-auth.md`](neon-auth.md) for the Neon Auth token contract.

Run the migration before shifting traffic:

```bash
DATABASE_URL="postgresql://..." alembic upgrade head
```

Verify:

```bash
curl -fsS https://your-api.example/health
curl -fsS https://your-api.example/ready
# expect: status=ready, database=ok
```

The GA is CPU-bound. Scale with **instances**, not threads/workers. One worker
per instance is usually the right default on a small plan.

## Docker

```bash
docker build -t fitness-rs-api .
docker run --rm \
  -p 8080:8080 \
  -e ENVIRONMENT=production \
  -e CORS_ORIGINS=https://your-frontend.example \
  -e API_KEY=your-key \
  --env-file .env \
  fitness-rs-api
```

The image:

- uses Python 3.12
- runs as a non-root user
- has a `/ready` health check
- installs only runtime dependencies

## Why Vercel was removed

The old `vercel.json` used the legacy `builds`/`routes` format and Python 3.9.
The recommendation workload is CPU-bound and better served by a persistent
web service. Keeping two deployment paths made it unclear which one was
authoritative. See [`hosting.md`](hosting.md) for the current hosting options.

## Reverse proxy and client IP

If `TRUST_PROXY_HEADERS=true`, the rate limiter reads the first value of
`X-Forwarded-For`. Only enable this behind a proxy you control. Otherwise a
client can spoof the header and reset its own limit.

## Rate limiting

The rate limiter uses an in-memory `limits` store by default. That is fine for one instance.
For multiple instances, point `RATE_LIMIT_STORAGE_URI` at Redis so counters are
shared. Install the Redis client extra in that environment (for example,
`pip install "limits[redis]"`).

## Metrics

`/metrics` is exposed by `prometheus-fastapi-instrumentator` when
`METRICS_ENABLED=true`. In a public deployment, either keep it behind your
platform's network controls or disable it and rely on platform metrics.

## Rollback

- Keep the previous image tag/deploy on the platform.
- Roll back to the last healthy build.
- `/ready` must return 200 with `dataset_version` and `database=ok` before
  shifting traffic.
- Do not run destructive migrations during a rollback; prefer additive
  migrations and a forward fix.
