# Backend implementation plan

## Architecture decision

Start with a **modular monolith**:

```text
FastAPI
  ├── api/v1          HTTP boundary
  ├── auth            OIDC/JWT validation, current principal
  ├── profiles        user profile, equipment, injuries, consent
  ├── plans           plan persistence, versions, sharing, export
  ├── workouts        sessions, sets, offline sync
  ├── feedback        ratings, difficulty, pain, unsafe reports
  ├── progress        aggregates and insights
  ├── trainer         client relationships and reviews
  ├── admin           safety triage, audit, operations
  └── core            config, errors, logging, db, security
```

Storage:

- **Postgres** (`Neon` or equivalent) for transactional data.
- **Redis** for rate limiting/cache/queues from P1 onward; not required for P0.1.
- **Object storage** (S3-compatible/R2) for generated PDFs and exercise media.
- **Worker** only when a job is too slow for HTTP (PDF, notifications, aggregates).

Do **not** split into microservices. The current domain is small and the
transaction boundaries are simple.

## Cross-cutting conventions

### API

- Prefix new endpoints with `/api/v1`.
- Keep existing endpoints unchanged:
  - `POST /api/v1/recommendation/`
  - `POST /api/v1/recommendation/by-focus`
  - `GET /health`, `GET /ready`
- Additive changes only. Breaking changes go to `/api/v2`.
- JSON only; UTC timestamps; UUID ids.
- Pagination: `limit` + `cursor` for lists.
- Idempotency: `Idempotency-Key` for plan creation, workout sync, webhooks.
- Error envelope: `error.code`, `error.message`, `error.details`, `request_id`,
  plus legacy `detail` and flat `message` for the current frontend.
- Every response: `X-Request-ID`, `X-Process-Time` where relevant.

### Security

- Validate OIDC access tokens with provider JWKS; never trust a client-supplied
  role.
- Store authorization roles/permissions in our database, not only in JWT claims.
- Rate limit by user id, then IP. Guest/anonymous generation is IP-limited.
- Do not log injury terms, notes, or tokens. Redact PII in logs.
- All tenant-owned tables carry `org_id`; all user-owned tables carry
  `owner_user_id`. Enforce at repository level and test cross-user/cross-tenant.
- Soft delete (`deleted_at`); hard delete only through a controlled retention job.
- Audit trail for trainer access, admin actions, consent changes, plan edits.

### Data

- `uuid` primary keys (`gen_random_uuid()`).
- `timestamptz` timestamps.
- `created_at`, `updated_at`, optional `deleted_at`.
- Optimistic concurrency with `version` on mutable resources.
- Migrations with Alembic; one migration per phase; reversible where possible.
- Seed data is separate from runtime migrations.

---

# P0.1 — Identity, profile, consent

**Status:** implemented behind `AUTH_PROFILES_ENABLED=false`. See
`p0-1-identity-and-profiles.md` for the contract and implementation notes.

**Goal:** users can create an account, complete a profile, and control their
health data. Existing public recommendation still works without login.

### Scope

- OIDC login/session on the frontend; backend validates bearer tokens.
- First authenticated request upserts `users` from verified claims.
- Profile: gender, height, weight, goal, experience, session duration, timezone,
  locale.
- Equipment profile and injury list.
- Consent for health-data processing and optional research analytics.
- Account export/delete request.
- Guest remains local-first: no guest PII on the server.

### Data

`users`, `profiles`, `user_equipment`, `user_injuries`, `consents`,
`user_roles`, `audit_log` (minimal).

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me` | current user, roles, profile completeness |
| POST | `/api/v1/me/onboarding` | idempotent profile + equipment + injuries + consent |
| GET | `/api/v1/me/profile` | read profile |
| PATCH | `/api/v1/me/profile` | update profile |
| PUT | `/api/v1/me/equipment` | replace equipment list |
| PUT | `/api/v1/me/injuries` | replace injury list |
| GET | `/api/v1/me/consents` | consent status |
| POST | `/api/v1/me/consents` | grant/revoke consent |
| DELETE | `/api/v1/me` | request account deletion |
| GET | `/api/v1/me/export` | export own data (JSON) |

### Rules

- `POST /me/onboarding` requires `health_data_processing` consent when injuries
  are present.
- Injury terms are normalized by the existing domain vocabulary; unknown terms
  return `422 unknown_injury`.
- Equipment must be a known enum value; unknown equipment is rejected.
- Profile values use the same bounds as the recommendation request.
- `DELETE /me` is a request; a worker/retention job performs the hard delete.
- Default role: `user`. `platform_admin` is seeded manually, never via API.

### Definition of done

- OIDC token validation tests (valid, expired, wrong issuer, wrong audience).
- First-login upsert is idempotent.
- Profile/equipment/injuries round-trip.
- Consent required before injuries are stored.
- User A cannot read/update user B.
- Export contains the user's own data only.
- OpenAPI updated; frontend can consume it without breaking the old flow.

---

# P0.2 — Plan lifecycle

**Status:** implemented behind `PLANS_ENABLED=false`. See
`p0-2-plan-lifecycle.md` for the contract and tests.

**Goal:** plans become durable artifacts instead of transient responses.

### Scope

- Save generated plan with a snapshot of input, seed, dataset version, algorithm
  version.
- List/get/delete plans.
- Version history.
- Swap exercise with safe alternatives; lock exercise; regenerate a day.
- Read-only share link.
- PDF and ICS export.

### Data

`plans`, `plan_versions`, `plan_days`, `plan_exercises`, `plan_shares`.
`locked` is stored on `plan_exercises`; no separate lock table.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/plans` | create from recommendation input/result |
| POST | `/api/v1/plans/import` | import a local guest plan after signup |
| GET | `/api/v1/plans` | list plans (cursor pagination) |
| GET | `/api/v1/plans/{id}` | plan detail |
| GET | `/api/v1/plans/{id}/versions` | version history |
| PATCH | `/api/v1/plans/{id}` | lock/swap/regenerate day |
| DELETE | `/api/v1/plans/{id}` | soft delete |
| POST | `/api/v1/plans/{id}/share` | create read-only token |
| DELETE | `/api/v1/plans/{id}/share` | revoke share |
| GET | `/api/v1/plans/{id}/export.pdf` | PDF stream |
| GET | `/api/v1/plans/{id}/export.ics` | calendar feed |
| GET | `/api/v1/shared/{token}` | public read-only plan |

### Rules

- Share token is random, hashed at rest, expires, and contains no PII.
- Plan version is immutable once created; edits create a new version.
- Swap must respect injury hard constraints and focus; never bypass safety.
- `Idempotency-Key` is required for create/import.
- `PATCH` uses `expected_revision` or `If-Match` to avoid lost updates.
- PDF/ICS generation is synchronous in P0.2; move to a worker if >500 ms.
- New plan endpoints are mounted only when `PLANS_ENABLED=true`.

### Definition of done

- Same seed + dataset/algorithm version reproduces the same plan.
- Share link works without auth and can be revoked.
- Swap cannot introduce an injured body part.
- Lock survives regeneration.
- Export files are valid and contain no tokens/PII.

---

# P0.3 — Workout execution and offline sync

**Status:** implemented behind `WORKOUTS_ENABLED=false`. See
`p0-3-workout-execution.md` for the contract and tests.

**Goal:** users can follow the plan in the gym.

### Scope

- Start/finish workout.
- Log sets: reps, weight, RPE, notes.
- Exercise substitutions.
- Offline queue and batch sync.
- Workout history.

### Data

`workout_sessions`, `workout_exercises`, `set_logs`, `client_mutations`.
Notes live on the session/exercise/set rows.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/workouts/start` | start from a plan day |
| GET | `/api/v1/workouts` | workout history |
| GET | `/api/v1/workouts/{id}` | workout detail |
| PATCH | `/api/v1/workouts/{id}` | update notes |
| POST | `/api/v1/workouts/{id}/sets` | add set |
| PATCH | `/api/v1/sets/{id}` | edit set |
| DELETE | `/api/v1/sets/{id}` | soft-delete set |
| POST | `/api/v1/workouts/{id}/complete` | finish |
| POST | `/api/v1/workouts/{id}/exercises/{exercise_id}/substitute` | substitute exercise |
| POST | `/api/v1/sync/batch` | batch offline mutations |

### Rules

- Client-generated session/set IDs; server accepts retries idempotently.
- `client_mutation_id` unique per user; replay returns the stored result.
- Timestamps are UTC; the session stores the IANA timezone for display.
- A workout belongs to one user; no cross-user access.
- Soft delete sets; preserve history.
- Offline batch is all-or-nothing per item, with per-item results.
- Substitution must respect injury and focus constraints.
- Completed workouts reject set/substitution changes.
- Mounted only when `WORKOUTS_ENABLED=true` (requires `PLANS_ENABLED=true`).

### Definition of done

- Replaying the same batch 3× does not duplicate sets.
- Workout completion stores totals/duration.
- Sync works with partial failures.
- History is paginated and timezone-correct.

---

# P0.4 — Feedback, safety reports, admin triage

**Status:** implemented behind `FEEDBACK_ENABLED=false`. See
`p0-4-feedback-and-safety.md` for the contract and tests.

**Goal:** close the trust loop and collect research data.

### Scope

- Plan rating and difficulty.
- Pain/discomfort report.
- Unsafe exercise report.
- Admin triage and resolution.
- Audit trail.

### Data

`feedback`, `unsafe_reports`; admin actions reuse `audit_log`.

### Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/feedback` | rating/difficulty/pain |
| POST | `/api/v1/safety-reports` | unsafe exercise |
| GET | `/api/v1/admin/safety-reports` | queue + filters/cursor |
| PATCH | `/api/v1/admin/safety-reports/{id}` | triage/escalate/resolve |
| GET | `/api/v1/admin/feedback` | feedback list |
| GET | `/api/v1/admin/audit` | audit trail |
| GET | `/api/v1/admin/quality-summary` | safety/feedback metrics |

### Rules

- Safety report severity: low/medium/high/critical.
- Critical reports trigger an optional operator webhook.
- Admin actions are audited; audit metadata excludes reasons/notes/comments.
- Feedback is linked to plan version and workout when available.
- Rate limit feedback/reports per user per hour.
- Platform admin is seeded manually; never granted via API.
- Mounted only when `FEEDBACK_ENABLED=true`.

### Definition of done

- Report is never lost; status transitions are valid.
- Admin can resolve with a reason.
- Metrics: reports per 1,000 plans, median time-to-resolution.
- Feedback/safety data is included in account deletion cleanup by FK cascade or
  retention policy.

---

# P1.1 — Progress and insights

**Status:** implemented behind `PROGRESS_ENABLED=false`. See
`p1-1-progress-and-insights.md` for the contract and tests.

- `daily_metrics`, `personal_records`, `weekly_reviews`.
- Rebuild-on-read for consistency; `scripts/rebuild_progress.py` for backfill.
- `GET /me/progress`, `/me/history`, `/me/insights`.
- Timezone-aware; backfillable.
- Dashboard reads from aggregates, not raw set logs.

# P1.2 — Trainer workspace

**Status:** implemented behind `TRAINER_ENABLED=false`. See
`p1-2-trainer-workspace.md` for the contract and tests.

- `trainer_profiles`, `trainer_clients`, `trainer_invitations`, `access_grants`,
  `plan_reviews`, `trainer_comments`.
- Invite/accept, client list, plan review, comments.
- Access only with explicit client consent; revoke anytime.
- Audit every client-data access.
- Tests for cross-trainer isolation.

# P1.3 — Notifications and integrations

- `notification_preferences`, `devices`, `integration_tokens`, `outbox`.
- Email/push/WhatsApp, calendar feed, optional Strava/Health.
- Outbox + queue + retry + idempotency.
- Unsubscribe and quiet hours.

# P2.1 — Organizations and billing

- `organizations`, `memberships`, `subscriptions`, `entitlements`, `invoices`.
- `org_id` on every tenant-owned table.
- Seats, roles, branding, Stripe webhooks (idempotent).
- Role vs entitlement separation.
- Cross-tenant isolation tests.

# P2.2 — Experimentation and quality

- Event schema, experiment assignment, feature flags.
- Quality dashboard, expert review, unsafe-report analytics.
- Dataset/algorithm version registry.
- Export for research with PII redaction.
- Reproducible experiment reports.

# P2.3 — Scale and reliability

- Redis rate limit/cache/queue.
- Worker for PDF/notifications/aggregates.
- Read replica, backups, restore tests.
- SLOs, tracing, metrics, alerts, runbooks.
- Load test 50–100 concurrent users.
- Security review and dependency audit.

---

## Backend delivery order

```text
P0.1 → P0.2 → P0.4 → P0.3 → P1.1 → P1.2 → P1.3 → P2.1 → P2.2 → P2.3
```

P0.4 can ship with P0.2 (safety reporting) before P0.3 if the priority is
trust. P0.3 is the biggest retention feature, so do not delay it too long.
