# P1.1 — Progress, history, and insights

**Status:** implemented behind `PROGRESS_ENABLED=false` by default. Requires
P0.3 workouts, P0.1 auth, and a database.

## Goal

Turn workout logs into feedback the user can act on:

- how consistent they have been;
- how much volume they have done;
- which body parts are under/over-trained;
- current personal records;
- a weekly review.

## Scope

- Daily aggregates from completed workouts.
- Personal records per exercise.
- Weekly reviews.
- Workout history with cursor pagination.
- Streak, 28-day consistency, body-part balance, and insights.
- Timezone-aware local dates.
- Rebuild on read for consistency after set/workout changes.

Out of scope:

- Charts/UI.
- Trainer commentary (P1.2).
- Wearable/health-platform imports (P1.3).
- Long-term analytics warehouse.
- Automatic programming changes from insights.

## Data model

```text
daily_metrics
  id, owner_user_id, metric_date, timezone,
  workouts_completed, total_sets, total_reps, total_volume_kg,
  duration_seconds, sets_by_body_part jsonb, volume_by_body_part jsonb,
  created_at, updated_at

personal_records
  id, owner_user_id, exercise_id, exercise_name, record_type,
  value, reps, weight_kg, achieved_at, set_log_id, created_at, updated_at

weekly_reviews
  id, owner_user_id, week_start, timezone,
  workouts_completed, total_sets, total_reps, total_volume_kg,
  duration_seconds, sets_by_body_part jsonb, volume_by_body_part jsonb,
  summary, created_at, updated_at
```

Rules:

- `daily_metrics` is unique per user/date.
- `weekly_reviews` is unique per user/week (Monday start).
- `personal_records` is unique per user/exercise/record type:
  - `max_weight`
  - `max_reps`
  - `max_volume`
- Only completed workouts and non-deleted, completed sets count.
- Local dates use the requested timezone (or the profile timezone).
- Rebuilding a range replaces existing daily/weekly rows so deleted sets or
  workouts do not leave stale totals.
- Personal records are rebuilt all-time per user.

## Endpoints

Mounted only when `PROGRESS_ENABLED=true`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me/progress` | Daily metrics + totals + streak |
| GET | `/api/v1/me/history` | Completed workout history |
| GET | `/api/v1/me/insights` | Streak, weekly review, balance, PRs |

### Progress

```http
GET /api/v1/me/progress?from_date=2026-11-01&to_date=2026-11-30&timezone=Asia/Jakarta
```

- Defaults to the last 30 days.
- Maximum range: 366 days.
- `from_date > to_date` → `422 progress_invalid`.
- Invalid timezone → `422 progress_invalid`.

Response contains:

- totals: workouts, sets, reps, volume, duration;
- daily rows;
- sets/volume by body part;
- streak days.

### History

```http
GET /api/v1/me/history?limit=20&cursor=...
```

Returns completed workouts only, using the same summary shape as P0.3.

### Insights

```http
GET /api/v1/me/insights?timezone=Asia/Jakarta
```

Response contains:

- streak days;
- workouts in the last 28 days;
- current week review;
- volume by body part (28 days);
- top 10 personal records;
- a short text summary.

## Rebuild strategy

P1.1 uses **rebuild-on-read** for correctness:

1. `refresh_progress` deletes daily metrics in the requested range.
2. Recomputes them from completed workouts/sets.
3. Rebuilds weekly reviews for the affected weeks.
4. Rebuilds all-time personal records.
5. Commits.

This is fast for the current data size and guarantees that deleted sets or
workouts do not leave stale numbers. A scheduled job can call the same service
if reads become expensive.

Backfill one user or all users:

```bash
DATABASE_URL=... python scripts/rebuild_progress.py --days 90
DATABASE_URL=... python scripts/rebuild_progress.py --days 365 --user-id <uuid>
```

## Tests

`tests/integration/test_progress.py` covers:

- feature flag;
- progress after a completed workout;
- deleted sets excluded;
- local-date streak;
- history pagination and owner isolation;
- personal records, weekly review, body-part balance, summary;
- invalid date range/timezone;
- OpenAPI paths.

`tests/integration/test_migrations.py` checks the P1.1 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
PLANS_ENABLED=true
WORKOUTS_ENABLED=true
PROGRESS_ENABLED=true
```

```bash
alembic upgrade head
```

## Known limitations

- Rebuild-on-read is not a long-term analytics pipeline.
- Streak is limited to the queried window (default 90 days for insights).
- Personal records are recomputed all-time on every rebuild.
- No charts, export, or trainer annotations.
- Timezone changes can shift historical local dates; callers should pass a
  stable timezone.
