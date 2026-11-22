# Documentation index

This directory is the planning source of truth for the next product phase.
**No P0.1 backend code has been started yet.** The current live API remains the
hardened recommendation engine documented in `README.md`.

## Start here

| Document | Purpose |
|---|---|
| [`product-roadmap.md`](product-roadmap.md) | Priorities, 10 phases, release plan, metrics, non-goals |
| [`backend-plan.md`](backend-plan.md) | Backend deliverables, APIs, jobs, and definition of done per phase |
| [`roles-and-access.md`](roles-and-access.md) | User roles, RBAC, consent, role vs entitlement vs ownership |
| [`data-model.md`](data-model.md) | Tables, relationships, invariants, migration order |
| [`p0-1-identity-and-profiles.md`](p0-1-identity-and-profiles.md) | Detailed implementation plan for the first phase |
| [`adr/0001-modular-monolith.md`](adr/0001-modular-monolith.md) | Why modular monolith + Postgres/Redis/object storage |
| [`adr/0002-auth-and-guest-mode.md`](adr/0002-auth-and-guest-mode.md) | OIDC auth, local guest mode, and roles |
| [`adr/0003-health-data-and-consent.md`](adr/0003-health-data-and-consent.md) | Health data, consent, retention, and access |

## Current baseline

- FastAPI `0.165`, Starlette `1.10`, Pydantic `2.14`, Python 3.11+
- Live API on Render, live frontend on Cloudflare Pages (`jymz.pages.dev`)
- 135 tests, ~94% coverage
- `pip-audit`: no known vulnerabilities
- Existing endpoints remain compatible:
  - `POST /api/v1/recommendation/` (201)
  - `POST /api/v1/recommendation/by-focus` (201)
  - `GET /health`, `GET /ready`

## Decision status

| Decision | Status |
|---|---|
| Modular monolith first | Accepted |
| Postgres for transactional data | Accepted |
| Redis for rate limiting/cache/queues | Accepted later; not required for P0.1 |
| OIDC auth with local-first guest mode | Accepted |
| Roles vs entitlements separation | Accepted |
| No microservices/Kubernetes now | Accepted |
| No LLM chatbot as core feature | Accepted |

## How to use these documents

1. Read `product-roadmap.md` for the order of work.
2. Read `backend-plan.md` for the backend scope of each phase.
3. Read `roles-and-access.md` and `data-model.md` before designing endpoints.
4. Use `p0-1-identity-and-profiles.md` as the implementation contract for the
   first coding phase.
