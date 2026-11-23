# API guide

Base URL: `http://127.0.0.1:8000` (local) or your deployed API URL.

Interactive docs: `/docs` (Swagger) and `/redoc`.

## Authentication

Two independent mechanisms:

1. **Recommendation API key (optional).** If `API_KEY` is set, send:
   ```http
   X-API-Key: your-key
   ```
   Requests without a valid key receive `401 unauthorized`.

2. **OIDC bearer token (P0.1, feature-flagged).** When
   `AUTH_PROFILES_ENABLED=true`, `/api/v1/me/*` requires:
   ```http
   Authorization: Bearer <access_token>
   ```
   The backend validates the token against the configured OIDC issuer,
   audience, and JWKS. Roles are read from the database, not from the token.

The public recommendation endpoint does **not** require an OIDC login.

## Endpoints

### `GET /health`

Liveness. Does not check the dataset.

```bash
curl http://127.0.0.1:8000/health
```

### `GET /ready`

Readiness. Fails with `503` if the dataset is missing/invalid. When
`DATABASE_URL` is configured, it also checks the database and returns
`database: "ok"`.

### `POST /api/v1/recommendation/`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recommendation/ \
  -H "Content-Type: application/json" \
  -d '{
    "gender": "male",
    "height_cm": 175,
    "weight_kg": 72,
    "injuries": ["lower back"],
    "available_days": 4,
    "preferred_body_part": ["chest", "biceps"],
    "preferred_equipment": ["dumbbell", "barbell"],
    "seed": 42
  }'
```

### `POST /api/v1/recommendation/by-focus`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recommendation/by-focus \
  -H "Content-Type: application/json" \
  -d '{"day_focus":"chest","injuries":["shoulder"],"seed":7}'
```

## P0.1 account endpoints

Mounted only when `AUTH_PROFILES_ENABLED=true`. Full contract:
[`p0-1-identity-and-profiles.md`](p0-1-identity-and-profiles.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me` | Current user, roles, profile completeness, consent state |
| POST | `/api/v1/me/onboarding` | Idempotent profile + equipment + injuries + consent |
| GET/PATCH | `/api/v1/me/profile` | Read/update profile |
| PUT | `/api/v1/me/equipment` | Replace equipment list |
| PUT | `/api/v1/me/injuries` | Replace injury list (health consent required) |
| GET/POST | `/api/v1/me/consents` | Read/grant/revoke consent |
| GET | `/api/v1/me/export` | Export own data as JSON |
| DELETE | `/api/v1/me` | Request account deletion (`202`) |

## P0.2 plan endpoints

Mounted only when `PLANS_ENABLED=true`. Full contract:
[`p0-2-plan-lifecycle.md`](p0-2-plan-lifecycle.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/plans` | Create from recommendation input/result |
| POST | `/api/v1/plans/import` | Import a guest/recommendation result |
| GET | `/api/v1/plans` | List own plans (`limit`, `cursor`) |
| GET | `/api/v1/plans/{id}` | Plan detail |
| GET | `/api/v1/plans/{id}/versions` | Version history |
| PATCH | `/api/v1/plans/{id}` | Lock/swap/regenerate day |
| DELETE | `/api/v1/plans/{id}` | Soft delete (`204`) |
| POST | `/api/v1/plans/{id}/share` | Create read-only share link |
| DELETE | `/api/v1/plans/{id}/share` | Revoke shares (`204`) |
| GET | `/api/v1/plans/{id}/export.pdf` | PDF export |
| GET | `/api/v1/plans/{id}/export.ics` | Calendar export |
| GET | `/api/v1/shared/{token}` | Public read-only plan |

`POST /plans` and `/plans/import` require:

```http
Idempotency-Key: <1-128 characters>
Authorization: Bearer <token>
```

`PATCH /plans/{id}` requires `expected_revision` in the body or
`If-Match: "<revision>"`.

## P0.3 workout endpoints

Mounted only when `WORKOUTS_ENABLED=true`. Full contract:
[`p0-3-workout-execution.md`](p0-3-workout-execution.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/workouts/start` | Start from a plan day |
| GET | `/api/v1/workouts` | History (`limit`, `cursor`, `status`) |
| GET | `/api/v1/workouts/{id}` | Detail with exercises/sets |
| PATCH | `/api/v1/workouts/{id}` | Update notes |
| POST | `/api/v1/workouts/{id}/complete` | Finish workout |
| POST | `/api/v1/workouts/{id}/sets` | Add a set |
| POST | `/api/v1/workouts/{id}/exercises/{exercise_id}/substitute` | Substitute |
| PATCH | `/api/v1/sets/{id}` | Update a set |
| DELETE | `/api/v1/sets/{id}` | Soft-delete a set (`204`) |
| POST | `/api/v1/sync/batch` | Apply offline mutations |

`client_session_id` and `client_set_id` provide retry idempotency.
`POST /sync/batch` returns `applied`, `duplicate`, or `error` per mutation.

## P0.4 feedback and safety endpoints

Mounted only when `FEEDBACK_ENABLED=true`. Full contract:
[`p0-4-feedback-and-safety.md`](p0-4-feedback-and-safety.md).

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/feedback` | Submit plan/workout feedback |
| POST | `/api/v1/safety-reports` | Report an unsafe exercise |
| GET | `/api/v1/admin/safety-reports` | Admin queue (`status`, `severity`, cursor) |
| PATCH | `/api/v1/admin/safety-reports/{id}` | Triage/escalate/resolve |
| GET | `/api/v1/admin/feedback` | Feedback list |
| GET | `/api/v1/admin/audit` | Audit trail |
| GET | `/api/v1/admin/quality-summary` | Safety/feedback metrics |

Admin endpoints require the `platform_admin` role. Feedback and safety
submissions are rate-limited per user per hour.

## P1.1 progress endpoints

Mounted only when `PROGRESS_ENABLED=true`. Full contract:
[`p1-1-progress-and-insights.md`](p1-1-progress-and-insights.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me/progress` | Daily metrics + totals + streak |
| GET | `/api/v1/me/history` | Completed workout history |
| GET | `/api/v1/me/insights` | Streak, weekly review, body-part balance, PRs |

`/me/progress` accepts `from_date`, `to_date`, and `timezone`; defaults to the
last 30 days. `timezone` is IANA, e.g. `Asia/Jakarta`.

## P1.2 trainer endpoints

Mounted only when `TRAINER_ENABLED=true`. Full contract:
[`p1-2-trainer-workspace.md`](p1-2-trainer-workspace.md).

| Method | Path | Actor | Purpose |
|---|---|---|---|
| GET/PUT | `/api/v1/trainer/profile` | trainer | Profile |
| POST/GET | `/api/v1/trainer/invitations` | trainer | Invite/list invitations |
| POST | `/api/v1/trainer/invitations/{token}/accept` | client | Accept with scopes |
| POST | `/api/v1/trainer/invitations/{token}/decline` | client | Decline |
| GET | `/api/v1/trainer/clients` | trainer | Active clients |
| GET | `/api/v1/trainer/clients/{id}/plans` | trainer | Plans (`plans` scope) |
| GET | `/api/v1/trainer/clients/{id}/workouts` | trainer | Workouts (`workouts`) |
| GET | `/api/v1/trainer/clients/{id}/feedback` | trainer | Feedback (`feedback`) |
| GET | `/api/v1/trainer/clients/{id}/progress` | trainer | Progress (`progress`) |
| POST | `/api/v1/trainer/clients/{id}/comments` | trainer | Comment (`plans`) |
| PATCH | `/api/v1/trainer/plans/{plan_id}/review` | trainer | Review/approve plan |
| GET | `/api/v1/me/trainers` | client | Trainers with access |
| DELETE | `/api/v1/me/trainers/{trainer_id}` | client | Revoke access |
| GET | `/api/v1/me/trainer/comments` | client | Comments from trainers |
| GET | `/api/v1/me/trainer/reviews` | client | Plan reviews |

The `trainer` role is seeded manually. Client scopes are `plans`, `workouts`,
`feedback`, and `progress`; missing/revoked scope returns `403
trainer_access_denied`.

## P1.3 notification endpoints

Mounted only when `NOTIFICATIONS_ENABLED=true`. Full contract:
[`p1-3-notifications-and-integrations.md`](p1-3-notifications-and-integrations.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET/PATCH | `/api/v1/me/notifications` | user | Preferences |
| POST | `/api/v1/me/notifications/test` | user | Enqueue test |
| GET | `/api/v1/me/notifications/unsubscribe-token` | user | Email unsubscribe link |
| GET | `/api/v1/notifications/unsubscribe/{token}` | public | Unsubscribe email |
| GET/POST | `/api/v1/me/devices` | user | List/register devices |
| DELETE | `/api/v1/me/devices/{id}` | user | Remove device |
| GET | `/api/v1/me/calendar.ics` | user | Authenticated calendar |
| POST | `/api/v1/me/calendar/token` | user | Public calendar token |
| GET | `/api/v1/calendar/{token}.ics` | public | Public calendar |
| GET/DELETE | `/api/v1/me/integrations` | user | List/disconnect |
| POST | `/api/v1/me/integrations/{provider}/authorize` | user | Start OAuth |
| POST | `/api/v1/integrations/{provider}/callback` | public | OAuth callback |

Delivery modes are `log`, `webhook`, or `disabled`. Run
`python scripts/process_outbox.py` to enqueue due reminders and process the
outbox.

## P2.1 organization endpoints (free)

Mounted only when `ORGANIZATIONS_ENABLED=true`. Full contract:
[`p2-1-organizations.md`](p2-1-organizations.md). There is no billing or
payment API.

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/orgs` | user | Create organization |
| GET | `/api/v1/me/orgs` | user | List my organizations |
| GET/PATCH | `/api/v1/orgs/{org_id}` | member / owner-admin | Detail/update |
| GET | `/api/v1/orgs/{org_id}/summary` | owner/admin | Counts only |
| GET | `/api/v1/orgs/{org_id}/members` | member | List members |
| PATCH | `/api/v1/orgs/{org_id}/members/{user_id}` | owner/admin | Change role |
| DELETE | `/api/v1/orgs/{org_id}/members/{user_id}` | owner/admin | Remove member |
| POST | `/api/v1/orgs/{org_id}/leave` | member | Leave |
| GET/POST | `/api/v1/orgs/{org_id}/invitations` | owner/admin | List/create invitations |
| POST | `/api/v1/org-invitations/{token}/accept` | user | Accept invitation |
| POST | `/api/v1/org-invitations/{token}/decline` | user | Decline invitation |

Organization membership is separate from health-data access. Non-members
receive `404`; members without the required role receive `403
organization_access_denied`.

## P2.2 research endpoints (consent-gated)

Mounted only when `RESEARCH_ENABLED=true`. Full contract:
[`p2-2-research-and-quality.md`](p2-2-research-and-quality.md).

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/me/events` | user + research consent | Submit allowlisted event |
| GET | `/api/v1/me/experiments` | user + research consent | Assign/read variants |
| POST | `/api/v1/admin/research/versions/register` | platform admin | Snapshot versions |
| GET | `/api/v1/admin/research/versions` | platform admin | List versions |
| GET | `/api/v1/admin/research/report` | platform admin | Aggregate report |
| GET | `/api/v1/admin/research/export` | platform admin | Redacted export |
| POST/GET | `/api/v1/admin/experiments` | platform admin | Create/list experiments |
| GET/PATCH | `/api/v1/admin/experiments/{experiment_id}` | platform admin | Report/update |
| POST/GET | `/api/v1/admin/quality-reviews` | platform admin | Create/list reviews |
| GET/PATCH | `/api/v1/admin/quality-reviews/{review_id}` | platform admin | Detail/update |

`start` and `end` are required ISO 8601 query parameters for reports/exports,
with a maximum 366-day window. Exports require `RESEARCH_EXPORT_SECRET` and
replace user/plan/workout IDs with HMAC pseudonyms. No comments, notes,
reasons, emails, or titles are exported.

## P2.3 operations endpoint

Mounted only when `OPS_ENABLED=true`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/api/v1/admin/ops/status` | platform admin | DB/migration/outbox/Redis status |

`/ready` remains the platform health check and now includes:

```json
{
  "status": "ready",
  "database": "ok",
  "redis": "not_configured",
  "redis_detail": null,
  "rate_limit": "memory",
  "degraded": false
}
```

Redis being unavailable is reported as `degraded` but does not make the API
unready while `RATE_LIMIT_FAIL_OPEN=true`. With fail-closed enabled, requests
receive `503 rate_limit_unavailable`.

## Response envelope

Success uses the endpoint-specific schema. Every response includes:

- `X-Request-ID`
- `X-Process-Time`

Errors always use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Payload request tidak valid.",
    "details": [
      {"field": "body.available_days", "message": "...", "type": "less_than_equal"}
    ]
  },
  "request_id": "...",
  "detail": "Payload request tidak valid.",
  "message": "Payload request tidak valid."
}
```

`detail` and top-level `message` are compatibility keys for older frontend
error handlers; new clients should read `error.code` and `error.message`.

## Status codes

| Code | Meaning |
|---:|---|
| 201 | Recommendation or plan created |
| 202 | Account deletion request accepted |
| 204 | Delete/revoke succeeded |
| 401 | API key or bearer token missing/invalid |
| 403 | Authenticated but not allowed, or account deletion pending |
| 404 | Plan/share not found |
| 409 | Consent required, revision conflict, locked exercise, or idempotency conflict |
| 413 | Request body too large |
| 422 | Validation or safety constraint failed |
| 428 | `expected_revision`/`If-Match` required |
| 429 | Rate limit exceeded |
| 500 | Unexpected error |
| 503 | Timeout, dataset not ready, database/auth not configured, or rate-limit backend fail-closed |

## Examples of safe failures

Requesting a chest session while `chest` is injured:

```json
{
  "error": {
    "code": "insufficient_exercise_pool",
    "message": "Tidak cukup latihan aman untuk menyusun jadwal pada fokus tersebut...",
    "details": {
      "day": "day_1",
      "focus": "chest",
      "required": 4,
      "available": 0,
      "injuries": ["chest"]
    }
  },
  "request_id": "..."
}
```

This is intentional: the API will not return a chest exercise for a chest
injury just to avoid an error.
