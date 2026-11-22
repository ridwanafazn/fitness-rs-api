# Documentation index

This directory is the planning and implementation source of truth.

- **P0.1** identity/profiles/consent is implemented behind
  `AUTH_PROFILES_ENABLED=false`.
- **P0.2** plan lifecycle is implemented behind `PLANS_ENABLED=false`.
- **P0.3** workout execution/offline sync is implemented behind
  `WORKOUTS_ENABLED=false`.
- **P0.4** feedback/safety/admin triage is implemented behind
  `FEEDBACK_ENABLED=false`.
- **P1.1** progress/insights is implemented behind `PROGRESS_ENABLED=false`.
- **P1.2** trainer workspace is implemented behind `TRAINER_ENABLED=false`.
- Neon Auth is the selected identity provider; see `neon-auth.md`.

The existing recommendation API remains unchanged and public.

## Start here

| Document | Purpose |
|---|---|
| [`product-roadmap.md`](product-roadmap.md) | Priorities, 10 phases, release plan, metrics, non-goals |
| [`backend-plan.md`](backend-plan.md) | Backend deliverables, APIs, jobs, and definition of done per phase |
| [`roles-and-access.md`](roles-and-access.md) | User roles, RBAC, consent, role vs entitlement vs ownership |
| [`data-model.md`](data-model.md) | Tables, relationships, invariants, migration order |
| [`p0-1-identity-and-profiles.md`](p0-1-identity-and-profiles.md) | Implemented P0.1 contract |
| [`p0-2-plan-lifecycle.md`](p0-2-plan-lifecycle.md) | Implemented P0.2 contract |
| [`p0-3-workout-execution.md`](p0-3-workout-execution.md) | Implemented P0.3 contract |
| [`p0-4-feedback-and-safety.md`](p0-4-feedback-and-safety.md) | Implemented P0.4 contract |
| [`p1-1-progress-and-insights.md`](p1-1-progress-and-insights.md) | Implemented P1.1 contract |
| [`p1-2-trainer-workspace.md`](p1-2-trainer-workspace.md) | Implemented P1.2 contract |
| [`neon-auth.md`](neon-auth.md) | Neon Auth setup and JWT contract |
| [`provisioned-resources.md`](provisioned-resources.md) | Neon project/Auth IDs, migration head, local env loading |
| [`hosting.md`](hosting.md) | Always-on cloud hosting without cold starts; free/PAYG options |
| [`adr/0001-modular-monolith.md`](adr/0001-modular-monolith.md) | Why modular monolith + Postgres/Redis/object storage |
| [`adr/0002-auth-and-guest-mode.md`](adr/0002-auth-and-guest-mode.md) | OIDC auth, local guest mode, and roles |
| [`adr/0003-health-data-and-consent.md`](adr/0003-health-data-and-consent.md) | Health data, consent, retention, and access |

## Current baseline

- FastAPI `0.165`, Starlette `1.10`, Pydantic `2.14`, Python 3.11+
- SQLAlchemy 2 + Alembic + psycopg 3 + PyJWT + ReportLab
- 240 tests passing
- Live API on Render, live frontend on Cloudflare Pages (`jymz.pages.dev`)
- Existing endpoints remain compatible:
  - `POST /api/v1/recommendation/` (201)
  - `POST /api/v1/recommendation/by-focus` (201)
  - `GET /health`, `GET /ready`
- P0.1 endpoints (`AUTH_PROFILES_ENABLED=true`):
  - `GET /api/v1/me`
  - `POST /api/v1/me/onboarding`
  - `GET/PATCH /api/v1/me/profile`
  - `PUT /api/v1/me/equipment`
  - `PUT /api/v1/me/injuries`
  - `GET/POST /api/v1/me/consents`
  - `GET /api/v1/me/export`
  - `DELETE /api/v1/me`
- P0.2 endpoints (`PLANS_ENABLED=true`):
  - `POST /api/v1/plans`, `POST /api/v1/plans/import`
  - `GET /api/v1/plans`, `GET /api/v1/plans/{id}`
  - `PATCH/DELETE /api/v1/plans/{id}`
  - `GET /api/v1/plans/{id}/versions`
  - `POST/DELETE /api/v1/plans/{id}/share`
  - `GET /api/v1/plans/{id}/export.pdf`, `export.ics`
  - `GET /api/v1/shared/{token}` (public, read-only)
- P0.3 endpoints (`WORKOUTS_ENABLED=true`):
  - `POST /api/v1/workouts/start`
  - `GET /api/v1/workouts`, `GET /api/v1/workouts/{id}`
  - `PATCH /api/v1/workouts/{id}`
  - `POST /api/v1/workouts/{id}/complete`
  - `POST /api/v1/workouts/{id}/sets`
  - `POST /api/v1/workouts/{id}/exercises/{exercise_id}/substitute`
  - `PATCH/DELETE /api/v1/sets/{id}`
  - `POST /api/v1/sync/batch`
- P0.4 endpoints (`FEEDBACK_ENABLED=true`):
  - `POST /api/v1/feedback`
  - `POST /api/v1/safety-reports`
  - `GET /api/v1/admin/safety-reports`
  - `PATCH /api/v1/admin/safety-reports/{id}`
  - `GET /api/v1/admin/feedback`
  - `GET /api/v1/admin/audit`
  - `GET /api/v1/admin/quality-summary`
- P1.1 endpoints (`PROGRESS_ENABLED=true`):
  - `GET /api/v1/me/progress`
  - `GET /api/v1/me/history`
  - `GET /api/v1/me/insights`
- P1.2 endpoints (`TRAINER_ENABLED=true`):
  - `GET/PUT /api/v1/trainer/profile`
  - `POST/GET /api/v1/trainer/invitations`
  - `POST /api/v1/trainer/invitations/{token}/accept`, `/decline`
  - `GET /api/v1/trainer/clients`
  - `GET /api/v1/trainer/clients/{id}/plans`, `/workouts`, `/feedback`, `/progress`
  - `POST /api/v1/trainer/clients/{id}/comments`
  - `PATCH /api/v1/trainer/plans/{plan_id}/review`
  - `GET /api/v1/me/trainers`, `DELETE /api/v1/me/trainers/{trainer_id}`
  - `GET /api/v1/me/trainer/comments`, `/reviews`

## Implementation status

| Phase | Status |
|---|---|
| P0.1 Identity, profile, consent | Implemented behind feature flag; Neon Auth + production Postgres configured on a dedicated Neon branch |
| P0.2 Plan lifecycle | Implemented behind feature flag |
| P0.3 Workout execution | Implemented behind feature flag |
| P0.4 Feedback & safety | Implemented behind feature flag |
| P1.1 Progress & insights | Implemented behind feature flag; needs frontend charts |
| P1.2 Trainer workspace | Implemented behind feature flag; needs frontend UI + manual trainer role |
| P1.3 Notifications | Next |
| P2 | Planned |

## Decision status

| Decision | Status |
|---|---|
| Modular monolith first | Accepted |
| Postgres for transactional data | Accepted |
| Redis for rate limiting/cache/queues | Accepted later; not required for P0.1/P0.2 |
| Neon Auth as identity provider | Accepted and backend-integrated |
| OIDC auth with local-first guest mode | Accepted and implemented |
| Roles vs entitlements separation | Accepted |
| No microservices/Kubernetes now | Accepted |
| No LLM chatbot as core feature | Accepted |
| Always-on hosting instead of sleeping free tiers | Accepted; see `hosting.md` |

## How to use these documents

1. Read `product-roadmap.md` for the order of work.
2. Read `backend-plan.md` for the backend scope of each phase.
3. Read `roles-and-access.md` and `data-model.md` before designing endpoints.
4. Use `p0-1-identity-and-profiles.md` and `p0-2-plan-lifecycle.md` for the
   implemented contracts.
5. Read `neon-auth.md` before enabling login.
6. Read `hosting.md` before choosing a production host.
