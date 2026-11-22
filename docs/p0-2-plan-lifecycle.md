# P0.2 — Plan lifecycle

**Status:** implemented behind `PLANS_ENABLED=false` by default. Requires
P0.1 auth/profile endpoints, a database, and a signed-in user.

## Goal

A generated recommendation becomes a durable artifact the user can reopen,
edit safely, share read-only, and export. The recommendation response remains
unchanged.

## Scope

- Save a generated recommendation or import an existing/guest plan.
- Idempotent create with `Idempotency-Key`.
- Plan list, detail, version history, and soft delete.
- Immutable versions: every edit creates a new version.
- Lock, swap, and regenerate one day.
- Optimistic concurrency with `expected_revision` or `If-Match`.
- Read-only share links with hashed tokens and expiry.
- PDF and ICS export.
- Safety validation: no injured body part, focus-safe exercises, dataset match.

Out of scope:

- Trainer review/assignment (P1.2).
- Workout logs (P0.3).
- Async PDF worker and object storage (P2.3).
- Hard delete retention job.

## Data model

```text
plans
  id, owner_user_id, title, status, current_version, revision,
  input_snapshot jsonb, seed, dataset_version, algorithm_version,
  split_type, day_count, bmi, bmi_category,
  idempotency_key, idempotency_hash,
  created_at, updated_at, deleted_at

plan_versions
  id, plan_id, version, split_type, schedule jsonb, warnings jsonb,
  day_count, created_at, created_by

plan_days
  id, plan_version_id, day_number, focus, created_at

plan_exercises
  id, plan_day_id, exercise_id, exercise_name, body_part,
  equipment jsonb, primary_muscle jsonb, secondary_muscle jsonb,
  image_url, position, locked, created_at

plan_shares
  id, plan_id, token_hash, expires_at, revoked_at, created_at
```

Rules:

- `plan_versions`, `plan_days`, and `plan_exercises` are immutable snapshots.
- `plans.current_version` points to the active snapshot.
- `plans.revision` is the optimistic-concurrency counter.
- `locked` lives on the exercise in the snapshot; there is no separate lock
  table in this phase.
- Share tokens are random, hashed at rest, expiring, and read-only.
- Exercise display data is denormalized so old versions remain readable if the
  dataset changes.
- Soft delete keeps versions for recovery/audit; share links are revoked.

## Endpoints

Mounted only when `PLANS_ENABLED=true`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/plans` | Create from input (server generates) or save a result |
| POST | `/api/v1/plans/import` | Import a guest/recommendation result |
| GET | `/api/v1/plans` | List own plans (cursor pagination) |
| GET | `/api/v1/plans/{id}` | Current plan detail |
| PATCH | `/api/v1/plans/{id}` | Lock, swap, or regenerate a day |
| DELETE | `/api/v1/plans/{id}` | Soft delete + revoke shares |
| GET | `/api/v1/plans/{id}/versions` | Version history |
| POST | `/api/v1/plans/{id}/share` | Create read-only share token |
| DELETE | `/api/v1/plans/{id}/share` | Revoke active share tokens |
| GET | `/api/v1/plans/{id}/export.pdf` | PDF export |
| GET | `/api/v1/plans/{id}/export.ics` | Calendar export |
| GET | `/api/v1/shared/{token}` | Public read-only plan (no auth) |

`POST /plans` and `POST /plans/import` **require** an `Idempotency-Key` header
(1–128 chars). Repeating the same key and body returns the original plan;
reusing the key with a different body returns `409 idempotency_conflict`.

## Create contract

Generate server-side:

```json
{
  "recommendation": {
    "gender": "male",
    "height_cm": 175,
    "weight_kg": 72,
    "injuries": ["knee"],
    "available_days": 3,
    "preferred_body_part": [],
    "preferred_equipment": ["dumbbell"],
    "seed": 42
  },
  "title": "My 3-day plan"
}
```

Save an existing recommendation response:

```json
{
  "recommendation": { "...": "same input" },
  "result": { "...": "RecommendationResponse from /api/v1/recommendation/" },
  "title": "Imported plan"
}
```

`POST /plans/import` is the same shape with `result` required.

The service uses the dataset as the source of truth for names, body parts,
equipment, muscles, and image URLs. Client-provided display fields are not
trusted.

## Edit contract

`PATCH /api/v1/plans/{id}`:

```json
{
  "action": "lock",
  "expected_revision": 3,
  "plan_exercise_id": "uuid",
  "locked": true
}
```

```json
{
  "action": "swap",
  "expected_revision": 4,
  "plan_exercise_id": "uuid",
  "replacement_exercise_id": "optional-dataset-id"
}
```

```json
{
  "action": "regenerate_day",
  "expected_revision": 5,
  "day": 2
}
```

`expected_revision` may be replaced by `If-Match: "3"` (weak validators are
accepted). If both are sent, they must match. Missing both returns `428
precondition_required`; a stale revision returns `409 plan_revision_conflict`.

Rules:

- **Lock** creates a new version and toggles `locked` on that exercise.
- **Swap** is rejected with `409 exercise_locked` if the exercise is locked.
- Swap without an explicit replacement chooses a deterministic safe alternative,
  preferring the same body part, excluding injured parts and already-used
  exercises.
- **Regenerate day** preserves locked exercises and fills the remaining slots.
  It tries multiple seeds and falls back to the safe focus pool.
- Every successful edit increments `current_version` and `revision` and creates
  a new immutable snapshot.
- Old versions are never mutated.

## Share contract

```json
POST /api/v1/plans/{id}/share
{ "expires_in_days": 7 }
```

Response `201`:

```json
{
  "token": "one-time-visible-token",
  "expires_at": "2026-11-29T...",
  "share_url": "https://api.example/api/v1/shared/one-time-visible-token"
}
```

- The raw token is returned once and stored only as SHA-256.
- Default expiry 7 days; maximum 90.
- Public response excludes owner id, email, injuries, and the input snapshot.
- `DELETE /plans/{id}/share` revokes all active tokens for the plan.
- Deleted or expired plans return `404 share_not_found`.

## Export

- PDF uses ReportLab, A4, one section per day, exercise table, warnings, and a
  non-medical disclaimer.
- ICS creates one all-day event per plan day, starting next Monday, with the
  exercise list in the description.
- Export is owner-only and audited as `plan.exported`.
- Both are synchronous in P0.2; move to a worker/object storage if plans grow or
  PDF generation exceeds ~500 ms.

## Error codes

| Code | HTTP | Meaning |
|---|---:|---|
| `plan_not_found` | 404 | Plan missing or not owned by caller |
| `share_not_found` | 404 | Share token missing, revoked, expired, or plan deleted |
| `plan_revision_conflict` | 409 | Stale `expected_revision`/`If-Match` |
| `plan_dataset_mismatch` | 409 | Imported result was produced with another dataset |
| `plan_invalid` | 422 | Invalid day/exercise/safety/focus |
| `exercise_locked` | 409 | Swap attempted on a locked exercise |
| `idempotency_conflict` | 409 | Same key used with a different request body |
| `precondition_required` | 428 | Missing revision precondition |
| `invalid_cursor` | 422 | Invalid list cursor |

## Safety invariants

1. An imported plan cannot contain an exercise whose body part is in the
   user's injury mapping.
2. Every exercise must be focus-safe for its day.
3. Exercise IDs must exist in the current dataset; display data comes from the
   dataset.
4. Each day must have the expected exercise count for its focus
   (cardio 3, specific body part 4, composite 5).
5. Swap/regenerate never relaxes injuries.
6. Locked exercises survive regeneration.
7. Share/public responses contain no owner PII or injury data.
8. Plan access is owner-scoped in every query.

## Tests

`tests/integration/test_plans.py` covers:

- feature flag, required idempotency key, replay, and key/body conflict;
- generated plan and imported recommendation result;
- dataset mismatch and unsafe import rejection;
- owner isolation and version history;
- lock creating a new immutable version;
- swap requiring unlock and changing the exercise;
- regenerate preserving locked exercises;
- revision conflict, missing precondition, and `If-Match`;
- share token hashing, public read-only response, revoke, expiry, and delete;
- PDF/ICS content and export audit;
- pagination and OpenAPI paths.

`tests/integration/test_migrations.py` checks the P0.2 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
PLANS_ENABLED=true
```

```bash
alembic upgrade head
```

Keep `PLANS_ENABLED=false` until the frontend can send a bearer token and an
`Idempotency-Key`.

## Known limitations

- No trainer/client access to plans yet; that is P1.2.
- No plan duplication/archive UI yet; `status` supports `archived` for later.
- PDF/ICS are generated in-process.
- No hard-delete retention job; soft delete only.
- Share links are plan-wide, not per-version.
- No public plan discovery, likes, or social features.
