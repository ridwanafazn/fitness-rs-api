# Documentation index

This directory is the planning source of truth for the next product phase.
**P0.1 is implemented behind `AUTH_PROFILES_ENABLED=false` by default.** The
current live API remains the hardened recommendation engine documented in
`README.md`; enabling accounts is an additive deployment step.

## Start here

| Document | Purpose |
|---|---|
| [`product-roadmap.md`](product-roadmap.md) | Priorities, 10 phases, release plan, metrics, non-goals |
| [`backend-plan.md`](backend-plan.md) | Backend deliverables, APIs, jobs, and definition of done per phase |
| [`roles-and-access.md`](roles-and-access.md) | User roles, RBAC, consent, role vs entitlement vs ownership |
| [`data-model.md`](data-model.md) | Tables, relationships, invariants, migration order |
| [`p0-1-identity-and-profiles.md`](p0-1-identity-and-profiles.md) | P0.1 contract and implementation notes |
| [`hosting.md`](hosting.md) | Always-on cloud hosting without cold starts; free/PAYG options |
| [`adr/0001-modular-monolith.md`](adr/0001-modular-monolith.md) | Why modular monolith + Postgres/Redis/object storage |
| [`adr/0002-auth-and-guest-mode.md`](adr/0002-auth-and-guest-mode.md) | OIDC auth, local guest mode, and roles |
| [`adr/0003-health-data-and-consent.md`](adr/0003-health-data-and-consent.md) | Health data, consent, retention, and access |

## Current baseline

- FastAPI `0.165`, Starlette `1.10`, Pydantic `2.14`, Python 3.11+
- SQLAlchemy 2 + Alembic + psycopg 3 + PyJWT
- 171 tests passing (including P0.1 auth, consent, export, and migration tests)
- Live API on Render, live frontend on Cloudflare Pages (`jymz.pages.dev`)
- Existing endpoints remain compatible:
  - `POST /api/v1/recommendation/` (201)
  - `POST /api/v1/recommendation/by-focus` (201)
  - `GET /health`, `GET /ready`
- P0.1 endpoints are mounted only when `AUTH_PROFILES_ENABLED=true`:
  - `GET /api/v1/me`
  - `POST /api/v1/me/onboarding`
  - `GET/PATCH /api/v1/me/profile`
  - `PUT /api/v1/me/equipment`
  - `PUT /api/v1/me/injuries`
  - `GET/POST /api/v1/me/consents`
  - `GET /api/v1/me/export`
  - `DELETE /api/v1/me`

## Implementation status

| Phase | Status |
|---|---|
| P0.1 Identity, profile, consent | Implemented behind feature flag; needs a real OIDC provider and production Postgres to go live |
| P0.2 Plan lifecycle | Next |
| P0.3 Workout execution | Planned |
| P0.4 Feedback & safety | Planned |
| P1/P2 | Planned |

## Decision status

| Decision | Status |
|---|---|
| Modular monolith first | Accepted |
| Postgres for transactional data | Accepted |
| Redis for rate limiting/cache/queues | Accepted later; not required for P0.1 |
| OIDC auth with local-first guest mode | Accepted and implemented |
| Roles vs entitlements separation | Accepted |
| No microservices/Kubernetes now | Accepted |
| No LLM chatbot as core feature | Accepted |
| Always-on hosting instead of sleeping free tiers | Accepted; see `hosting.md` |

## How to use these documents

1. Read `product-roadmap.md` for the order of work.
2. Read `backend-plan.md` for the backend scope of each phase.
3. Read `roles-and-access.md` and `data-model.md` before designing endpoints.
4. Use `p0-1-identity-and-profiles.md` for the implemented P0.1 contract.
5. Read `hosting.md` before choosing a production host.
