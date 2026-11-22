# Deployment guide

## Canonical target: Render

`render.yaml` defines the service. The health check must be `/ready` because
that endpoint verifies the exercise dataset.

Environment variables to set in the Render dashboard:

- `ENVIRONMENT=production`
- `CORS_ORIGINS=https://your-frontend.example` (the blueprint temporarily uses
  `*` to match the old API while the frontend origin is being confirmed;
  tighten it as soon as possible)
- `ALLOWED_HOSTS=your-api.onrender.com` (include any internal health-check
  hostname, or leave `*` if the platform's health checker uses a host you
  cannot enumerate)
- `API_KEY=...` (optional but recommended for a public API)
- `TRUST_PROXY_HEADERS=true`
- `RATE_LIMIT=120/minute`
- `RATE_LIMIT_STORAGE_URI=redis://...` if you run more than one instance
- `REQUEST_TIMEOUT_SECONDS=15`

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
authoritative. Render is now the single documented path.

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

- Keep the previous image tag / Render deploy.
- Roll back the Render deploy to the last healthy build.
- `/ready` must return 200 and `dataset_version` before shifting traffic.
