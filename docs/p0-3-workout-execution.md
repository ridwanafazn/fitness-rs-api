# P0.3 — Workout execution and offline sync

**Status:** implemented behind `WORKOUTS_ENABLED=false` by default. Requires
P0.2 plans, P0.1 auth, and a database.

## Goal

A user can start a workout from a saved plan day, log sets, substitute an
exercise safely, finish the session, and keep logging when the connection is
unreliable.

## Scope

- Start from a plan day (current or explicit plan version).
- Client-generated session/set IDs for idempotent retries.
- Set logs: reps, weight, RPE, completed flag, notes.
- Soft-delete sets.
- Exercise substitution with injury/focus safety.
- Complete workout with server-side totals and duration.
- Workout history with cursor pagination.
- Offline batch sync with per-item results.
- Timezone stored on the session; timestamps stored UTC.

Out of scope:

- Rest timer (client-side).
- Progress aggregates/PRs (P1.1).
- Trainer review (P1.2).
- Background sync worker.
- Health platform integrations (P1.3).

## Data model

```text
workout_sessions
  id, owner_user_id, plan_id, plan_version_id, plan_day_id,
  day_number, title, focus, status, timezone, injuries jsonb,
  started_at, completed_at, notes, client_session_id,
  total_sets, total_reps, total_volume_kg, exercise_count,
  duration_seconds, created_at, updated_at, deleted_at

workout_exercises
  id, workout_session_id, source_plan_exercise_id,
  exercise_id, exercise_name, body_part, equipment jsonb,
  primary_muscle jsonb, secondary_muscle jsonb, image_url,
  position, notes, substituted_from_exercise_id, created_at

set_logs
  id, workout_exercise_id, owner_user_id, set_number,
  reps, weight_kg, rpe, completed, notes, client_set_id,
  created_at, updated_at, deleted_at

client_mutations
  id, owner_user_id, client_mutation_id, mutation_type,
  result jsonb, occurred_at, applied_at, created_at
```

Rules:

- A workout belongs to one user; every query is owner-scoped.
- `client_session_id` is unique per owner when present.
- `client_set_id` is unique per owner when present.
- `(workout_exercise_id, set_number)` is unique among non-deleted sets.
- Sets are soft-deleted; history is never destroyed.
- `client_mutations` is the offline idempotency ledger; a replayed mutation
  returns the stored result.
- `plan_id`/`plan_version_id`/`plan_day_id` are `SET NULL` on hard delete so
  workout history survives plan cleanup.
- `injuries` is copied at start so substitution safety still works if the plan
  later changes.

## Endpoints

Mounted only when `WORKOUTS_ENABLED=true`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/workouts/start` | Start from a plan day |
| GET | `/api/v1/workouts` | History (`limit`, `cursor`, `status`) |
| GET | `/api/v1/workouts/{id}` | Detail with exercises and sets |
| PATCH | `/api/v1/workouts/{id}` | Update workout notes |
| POST | `/api/v1/workouts/{id}/complete` | Finish workout |
| POST | `/api/v1/workouts/{id}/sets` | Add a set |
| POST | `/api/v1/workouts/{workout_id}/exercises/{workout_exercise_id}/substitute` | Substitute |
| PATCH | `/api/v1/sets/{id}` | Update a set |
| DELETE | `/api/v1/sets/{id}` | Soft-delete a set |
| POST | `/api/v1/sync/batch` | Apply offline mutations |

## Start contract

```json
POST /api/v1/workouts/start
{
  "plan_id": "uuid",
  "day": 1,
  "plan_version": 3,
  "timezone": "Asia/Jakarta",
  "client_session_id": "uuid"
}
```

- `day` is optional only when the plan version has exactly one day.
- `plan_version` defaults to the plan's current version.
- `timezone` defaults to the profile timezone, then `UTC`.
- `client_session_id` makes retries idempotent.
- The plan must be owned by the caller and not deleted.

## Set contract

```json
POST /api/v1/workouts/{id}/sets
{
  "workout_exercise_id": "uuid",
  "set_number": 1,
  "reps": 10,
  "weight_kg": 20,
  "rpe": 8,
  "completed": true,
  "notes": "felt easy",
  "client_set_id": "uuid"
}
```

Rules:

- The workout must be `in_progress`.
- The exercise must belong to the workout.
- Replaying the same `client_set_id` returns the original set.
- A different client ID with an existing set number returns `409 set_conflict`.
- `PATCH /sets/{id}` accepts partial reps/weight/RPE/completed/notes.
- `DELETE /sets/{id}` sets `deleted_at` and excludes it from detail/totals.

## Complete contract

```json
POST /api/v1/workouts/{id}/complete
{ "notes": "session done" }
```

- Idempotent: completing an already completed workout returns the same result.
- Sets `completed_at`, `duration_seconds`.
- Recomputes `total_sets`, `total_reps`, `total_volume_kg`, `exercise_count`.
- Set changes are rejected after completion (`409 workout_completed`).

## Substitution

```json
POST /api/v1/workouts/{id}/exercises/{workout_exercise_id}/substitute
{ "replacement_exercise_id": "dataset-id" }
```

Rejects if:

- the workout is completed;
- the replacement is not in the dataset;
- it is already used in the workout;
- its body part is in the workout's injury snapshot;
- it is not compatible with the workout focus.

`substituted_from_exercise_id` records the original exercise ID.

## Offline sync

```json
POST /api/v1/sync/batch
{
  "mutations": [
    {
      "client_mutation_id": "device-uuid-1",
      "type": "set.create",
      "occurred_at": "2026-11-23T10:00:00Z",
      "payload": {
        "workout_id": "uuid",
        "workout_exercise_id": "uuid",
        "set_number": 1,
        "reps": 10,
        "weight_kg": 20,
        "client_set_id": "uuid"
      }
    }
  ]
}
```

Supported types:

| Type | Required payload |
|---|---|
| `set.create` | `workout_id`, set fields, optional `client_set_id` |
| `set.update` | `set_id`, at least one mutable field |
| `set.delete` | `set_id` |
| `workout.complete` | `workout_id`, optional `notes` |
| `exercise.substitute` | `workout_id`, `workout_exercise_id`, `replacement_exercise_id` |

Response:

```json
{
  "results": [
    {
      "client_mutation_id": "device-uuid-1",
      "status": "applied",
      "result": { "set_id": "uuid", "set_number": 1 },
      "error": null
    }
  ]
}
```

- `status` is `applied`, `duplicate`, or `error`.
- A duplicate returns the stored result; the mutation is not applied again.
- Each mutation has its own savepoint. A bad item does not roll back good items.
- Failed mutations are not written to `client_mutations`, so the client can
  retry them.
- Batch size is 1–100.
- Replaying the same batch three times must not duplicate sets.

## Safety invariants

1. Workout access is owner-scoped.
2. Substitution never introduces an injured body part.
3. Substitution must match the workout focus.
4. Set numbers are unique per exercise among active sets.
5. Completed workouts reject set/substitution changes.
6. Client set/session IDs are unique per owner.
7. Offline replay is idempotent.
8. Audit metadata contains no notes, injury terms, email, or tokens.

## Tests

`tests/integration/test_workouts.py` covers:

- feature flag;
- start + client-session idempotency;
- set logging, replay, conflict, update, delete, totals;
- completion idempotency and post-completion rejection;
- substitution and unsafe replacement rejection;
- history pagination and owner isolation;
- sync partial failure and three-time replay;
- sync update/substitute/delete/complete;
- PII-free audit;
- OpenAPI paths and invalid timezone/empty set update.

`tests/integration/test_migrations.py` checks the P0.3 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
PLANS_ENABLED=true
WORKOUTS_ENABLED=true
```

```bash
alembic upgrade head
```

Keep `WORKOUTS_ENABLED=false` until the frontend can send bearer tokens and
queue offline mutations.

## Known limitations

- No rest timer server state; it is client-side.
- No progress charts/PR detection yet (P1.1).
- No background sync; the client must retry failed batch items.
- No trainer access to workout logs yet (P1.2).
- Workout delete/archive is not exposed; sessions are retained for history.
