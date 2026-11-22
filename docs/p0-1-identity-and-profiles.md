# P0.1 — Identity, profile, consent

**Status:** implemented behind `AUTH_PROFILES_ENABLED=false`. Backend, migration,
and tests are complete; production still needs a real OIDC provider, a Postgres
database, and frontend onboarding screens.

## Goal

A user can sign in, complete a useful profile, control health-data consent, and
delete/export their data. The existing public recommendation flow keeps working
without login.

## Scope

In scope:

- OIDC authentication on the frontend; bearer-token validation on the backend.
- First-login user upsert.
- Profile: gender, height, weight, goal, experience, session duration, timezone,
  locale, unit system.
- Equipment list and injury list.
- Consent records for health data, research analytics, trainer sharing, and
  marketing.
- Account data export request and account deletion request.
- Audit events for consent and profile changes.
- API contract and OpenAPI documentation.

Out of scope:

- Saving plans (P0.2).
- Workout logs (P0.3).
- Feedback/safety reports (P0.4).
- Trainer access (P1.2).
- Organizations/billing (P2.1).
- Guest accounts stored on the server. Guest remains local-first.

## Product flow

```text
Guest
  └─ generate plan locally (existing public endpoint)
  └─ sign in
       └─ GET /me
            ├─ profile complete? → dashboard
            └─ incomplete? → onboarding
                 └─ POST /me/onboarding
                      └─ consent (required for injuries)
                      └─ profile + equipment + injuries
```

## Auth decision

Use an **OIDC-compatible provider**. The backend must not be coupled to one
vendor.

Recommended implementation:

- If the database is on Neon, use **Neon Auth** (selected).
- Otherwise use **Clerk** or another OIDC provider.
- Backend validates JWT via JWKS; roles are loaded from our database.

Neon Auth setup, claims, and frontend token retrieval are in
[`neon-auth.md`](neon-auth.md).

Configuration:

```text
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
AUTH_ISSUER=https://...
AUTH_AUDIENCE=...
AUTH_JWKS_URL=https://.../.well-known/jwks.json
AUTH_ALGORITHMS=EdDSA,RS256,ES256
```

With Neon Auth, the issuer/audience/JWKS values are derived from the branch URL:

```text
NEON_AUTH_BASE_URL=https://<host>/<db>/auth
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
```

See [`neon-auth.md`](neon-auth.md).

Local/test only (never in production):

```text
AUTH_DEV_MODE=true
AUTH_DEV_SECRET=<min 32 characters>
AUTH_ISSUER=https://issuer.test
AUTH_AUDIENCE=fitness-api-test
```

`AUTH_DEV_MODE` uses HS256 and is rejected when `ENVIRONMENT=production`.
Production uses JWKS only; HS256 is rejected outside dev mode.

Token validation:

- signature, issuer, audience, expiry
- `sub` required
- email only if verified
- no roles trusted from the token

First authenticated request:

```text
validate token
  → find users by (auth_issuer, auth_subject)
    → found: load user
    → not found: insert user with default role "user"
```

This upsert is idempotent and safe under concurrent first requests. The token
`sub` is scoped by issuer, so two providers cannot collide.

## Guest mode

Guest is a **client-side mode** in P0. There is no server-side guest PII.

- Guest uses the existing public recommendation endpoint.
- Plans can be stored locally (IndexedDB/localStorage).
- On signup, the frontend imports local plans in P0.2 via
  `POST /api/v1/plans/import`.
- No guest injury/profile data is uploaded until the user signs in and consents.

Why: lower friction, lower privacy risk, simpler data model.

## Data model

See `data-model.md` for full columns. P0.1 creates:

- `users` — includes `auth_issuer`, `auth_subject`, `deletion_requested_at`,
  `deletion_scheduled_for`
- `profiles`
- `user_equipment`
- `user_injuries`
- `consents`
- `user_roles`
- `audit_log`

Default role on first login: `user`. `platform_admin` is seeded manually and
never granted through the API.

## API contract

All endpoints require `Authorization: Bearer <access_token>`.

### `GET /api/v1/me`

```json
{
  "user": {
    "id": "uuid",
    "email": "user@example.com",
    "display_name": "Ridwan",
    "roles": ["user"]
  },
  "profile_complete": false,
  "consents": {
    "health_data_processing": true,
    "research_analytics": false,
    "trainer_sharing": false,
    "marketing": false
  }
}
```

### `POST /api/v1/me/onboarding`

Idempotent: safe to retry. Creates or replaces the profile, equipment, injuries,
and consent records in one transaction.

```json
{
  "display_name": "Ridwan",
  "profile": {
    "gender": "male",
    "height_cm": 175,
    "weight_kg": 72,
    "goal": "muscle_gain",
    "experience": "beginner",
    "session_minutes": 60,
    "timezone": "Asia/Jakarta",
    "locale": "id-ID",
    "unit_system": "metric"
  },
  "equipment": ["dumbbell", "barbell", "body weight"],
  "injuries": ["knee"],
  "consents": {
    "health_data_processing": true,
    "research_analytics": true
  }
}
```

Rules:

- `profile` is required and must be complete.
- `equipment` and `injuries` are optional. Omit to leave existing data
  unchanged; send `[]` to clear. This keeps retries safe.
- `health_data_processing` is required if `injuries` is non-empty. The check
  uses the consent in the same request or the currently active consent.
- Unknown injuries return `422 unknown_injury`.
- Unknown equipment returns `422 validation_error`.
- Values use the same bounds as `RecommendationRequest`.
- Empty equipment means “all equipment allowed”.
- The operation is transactional: either all pieces are saved or none.
- Revoking `health_data_processing` deletes stored injuries immediately.

### `GET /api/v1/me/profile`

Returns the profile, equipment, and injuries.

### `PATCH /api/v1/me/profile`

Partial update of profile fields only.

### `PUT /api/v1/me/equipment`

Replace the whole equipment list. Idempotent.

### `PUT /api/v1/me/injuries`

Replace the whole injury list. Requires active health consent when non-empty.
Unknown terms rejected.

### `GET /api/v1/me/consents`

Returns current active consent state.

### `POST /api/v1/me/consents`

Grant or revoke a consent kind.

```json
{
  "kind": "research_analytics",
  "granted": false,
  "version": "2026-01"
}
```

### `DELETE /api/v1/me`

Creates an account-deletion request. Returns `202 Accepted` with the request id,
`requested_at`, and `scheduled_for`. A retention job performs the hard delete
after `ACCOUNT_DELETION_GRACE_DAYS` (default 30). After the request, the user's
token is rejected with `403 account_deletion_pending`.

### `GET /api/v1/me/export`

Returns the user's own data as JSON (profile, equipment, injuries, consents,
plans/workouts when those phases exist).

## Validation

- Reuse the domain enums and bounds from `app/domain/constants.py`.
- Reuse `map_injury_to_body_parts` to normalize injuries.
- Store both the normalized term and resolved body parts.
- Reject unknown values instead of silently dropping them for injuries.
- Soft preferences unknown values are not relevant here; this is stored profile
  data and must be explicit.

## Error codes

| Code | HTTP | Meaning |
|---|---:|---|
| `unauthorized` | 401 | Missing/invalid token |
| `forbidden` | 403 | Authenticated but not allowed |
| `consent_required` | 409 | Health data requires consent |
| `unknown_injury` | 422 | Injury term not supported |
| `validation_error` | 422 | Invalid profile/equipment |
| `conflict` | 409 | Concurrent update |
| `account_deletion_pending` | 403 | Account already scheduled for deletion |

Keep the existing error envelope (`error`, `request_id`, legacy `detail`). Add a
top-level `message` for the current frontend error handler if not already
present.

## Security and privacy

- OIDC access tokens only; no passwords in our database.
- Validate token signature and claims.
- No roles from JWT; load from DB.
- Do not log tokens, injury terms, notes, or email.
- Rate limit authenticated requests per user; public recommendation remains
  IP-limited.
- CORS: move from `*` to explicit frontend origins once auth is enabled.
- Bearer tokens must not be stored insecurely. Prefer provider SDK memory +
  refresh, or httpOnly cookies through a BFF.
- Never put provider secrets in `VITE_*` variables.
- Consent version is recorded.
- Account deletion removes health data; audit retains no PII.

## Observability

Events (no PII):

- `auth.login_succeeded`
- `auth.login_failed`
- `profile.onboarding_completed`
- `profile.updated`
- `consent.granted`
- `consent.revoked`
- `account.deletion_requested`
- `account.exported`

Metrics:

- onboarding completion rate
- auth failure rate
- profile update latency
- deletion request count

## Tests

Unit:

- token validation (valid, expired, wrong issuer, wrong audience, missing sub)
- profile validation bounds
- injury normalization and unknown rejection
- consent gate for injuries

Integration:

- first login creates user + default role
- second login does not duplicate user
- onboarding is idempotent
- user A cannot read/update user B
- equipment/injuries replace correctly
- consent revoke blocks future injury writes
- export contains only own data
- delete request is recorded

Contract:

- OpenAPI schema snapshot
- frontend TypeScript client can be generated

## Migration and rollout

1. Add database dependency and Alembic.
2. Create P0.1 migration.
3. Add auth settings and dependency.
4. Add `/me` endpoints behind `AUTH_PROFILES_ENABLED=false` initially.
5. Test in staging with a Neon branch/test database.
6. Enable for internal users.
7. Enable in production.
8. Keep existing public recommendation endpoint unchanged.

Rollback:

- Disable feature flag.
- Revert frontend onboarding route.
- Do not drop tables in the first rollback; keep data.

## Implementation notes

Implemented backend files:

- `app/db/` — SQLAlchemy models, engine/session, URL normalization
- `app/auth/` — OIDC/JWKS validation, principal dependency, first-login upsert
- `app/schemas/me.py` — request/response models
- `app/services/identity.py` — profile, equipment, injury, consent, deletion
- `app/services/audit.py` — append-only audit helper
- `app/api/me.py` — `/api/v1/me` endpoints
- `migrations/versions/0001_identity_profiles.py` — P0.1 migration
- `tests/integration/test_me.py`, `tests/integration/test_migrations.py`,
  `tests/unit/test_auth_config.py`

Local run:

```bash
DATABASE_URL=sqlite+pysqlite:///./local.db \
DB_AUTO_CREATE=true \
AUTH_ENABLED=true AUTH_PROFILES_ENABLED=true \
AUTH_DEV_MODE=true AUTH_DEV_SECRET=change-me-32-characters-minimum \
AUTH_ISSUER=https://dev.local AUTH_AUDIENCE=jymz-dev \
uvicorn app.main:app --reload
```

Mint a local token and call the API:

```bash
TOKEN=$(python scripts/mint_dev_token.py --sub dev-user)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/me
```

Production migration:

```bash
DATABASE_URL="postgresql://..." alembic upgrade head
```

Known limitations at this stage:

- No real OIDC provider is configured in the repository; tests use dev mode.
- Frontend onboarding, login callback, and consent screens are not built yet.
- `DELETE /me` records a request; the hard-delete retention job is future work.
- Rate limiting is still IP-based globally; per-user limits come later.
- Email is optional and only stored when the provider marks it verified.
- `GET /me/export` currently covers P0.1 data only; plans/workouts are added in
  later phases.

## Task checklist

### Backend

- [x] Add Postgres + SQLAlchemy + Alembic dependencies.
- [x] Add auth settings and JWKS validation.
- [x] Add `users` upsert on first login.
- [x] Add profile/equipment/injuries/consent repositories.
- [x] Add `/me` endpoints and schemas.
- [x] Add consent gate.
- [x] Add audit events.
- [x] Add export/delete request.
- [x] Add tests.
- [x] Update OpenAPI.

### Database

- [x] Create P0.1 migration.
- [x] Add indexes and constraints.
- [x] Seed `user` role behavior.
- [x] Test migration from empty DB (SQLite upgrade/downgrade; Postgres runbook
  documented).

### Frontend

- [ ] Add OIDC provider and callback.
- [ ] Add `GET /me` bootstrapping.
- [ ] Add onboarding screen.
- [ ] Add consent UI.
- [ ] Add profile/settings screen.
- [ ] Keep guest flow working.
- [ ] Add error handling for new codes.

### Docs

- [x] Update OpenAPI/API docs.
- [x] Add privacy/consent copy (draft; legal review pending).
- [x] Add deployment env vars.
- [x] Add ADR links.
- [x] Add hosting/cold-start guidance.

## Acceptance criteria

1. A new user can sign in and complete onboarding in under 60 seconds.
2. Injuries cannot be stored without health-data consent.
3. The same onboarding request can be retried without duplicates.
4. User A cannot access user B.
5. Existing recommendation endpoint remains public and unchanged.
6. Guest users can still generate and keep a plan locally.
7. Account deletion request is recorded and export works.
8. No token/PII appears in logs.
9. OpenAPI is updated and frontend types can be generated.
10. Feature flag can disable the new flow without breaking the old app.

Backend status: criteria 2, 3, 4, 5, 7, 8, 9, and 10 are covered by tests.
Criteria 1 and 6 depend on the frontend work that has not started; the backend
contract is ready. Criterion 3 is verified for a single client; the upsert also
has a concurrent-insert retry path.

## Open decisions

- OIDC provider: Neon Auth vs Clerk (choose based on database/hosting).
- Is email required for account creation? Recommended: provider-provided, optional.
- Consent copy and policy version: needs final legal wording.
- Deletion grace period: 30 days recommended.
- Unit system default: metric for Indonesia, but store canonical metric.
- Whether to expose a public `/me` demo account: not recommended.
