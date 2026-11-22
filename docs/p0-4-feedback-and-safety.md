# P0.4 — Feedback, safety reports, and admin triage

**Status:** implemented behind `FEEDBACK_ENABLED=false` by default. Requires
P0.1 auth and a database; plan/workout context is optional but recommended.

## Goal

Close the trust loop: users can rate a plan, report pain or an unsafe exercise,
and a platform admin can triage and resolve the report with an audit trail.

## Scope

- Plan/workout feedback: rating, difficulty, pain/discomfort, comment.
- Unsafe exercise reports with severity and status.
- Per-user hourly rate limits for feedback and reports.
- Platform-admin queue, filters, pagination, triage, escalation, resolution.
- Admin feedback list, audit trail, and quality summary.
- Optional webhook alert for critical reports.
- Audit metadata without comments, pain areas, reasons, notes, or PII.

Out of scope:

- Trainer/medical expert review (P1.2).
- Automatic dataset retraining or exercise removal.
- User-facing notification inbox.
- Email/push delivery of admin responses.
- Public report browsing.

## Data model

```text
feedback
  id, owner_user_id, plan_id, plan_version_id, workout_session_id,
  rating, difficulty, pain, pain_area, comment, created_at

unsafe_reports
  id, reporter_user_id, plan_id, plan_exercise_id, workout_session_id,
  exercise_id, exercise_name, reason, severity, status,
  resolution_note, resolved_by, triaged_at, resolved_at,
  created_at, updated_at
```

Rules:

- `feedback` belongs to the user; plan/workout context is optional.
- `rating` is 1–5; `difficulty` is `too_easy`, `just_right`, or `too_hard`.
- A pain area implies `pain=true`.
- `unsafe_reports` keep context IDs with `SET NULL` on hard delete, so the
  safety record survives plan/workout cleanup.
- Reporter/resolver user IDs are `SET NULL` on user deletion.
- `severity`: `low`, `medium`, `high`, `critical`.
- `status`: `open`, `triaged`, `resolved`, `dismissed`.
- `reason`, `resolution_note`, comments, and pain areas are sensitive; never log
  or put them in audit metadata.

## Endpoints

Mounted only when `FEEDBACK_ENABLED=true`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/feedback` | Submit plan/workout feedback |
| POST | `/api/v1/safety-reports` | Report an unsafe exercise |
| GET | `/api/v1/admin/safety-reports` | Admin queue (`status`, `severity`, cursor) |
| PATCH | `/api/v1/admin/safety-reports/{id}` | Triage/escalate/resolve |
| GET | `/api/v1/admin/feedback` | Admin feedback list |
| GET | `/api/v1/admin/audit` | Audit trail |
| GET | `/api/v1/admin/quality-summary` | Safety/feedback metrics |

## Feedback contract

```json
POST /api/v1/feedback
{
  "plan_id": "uuid",
  "workout_session_id": "uuid",
  "rating": 4,
  "difficulty": "just_right",
  "pain": false,
  "pain_area": null,
  "comment": "good session"
}
```

- At least one of `rating`, `difficulty`, `pain`, or `comment` is required.
- Plan/workout must belong to the caller.
- If both plan and workout are given, they must match.
- `plan_version_id` is recorded from the workout or the plan's current version.
- Rate limit: `FEEDBACK_RATE_LIMIT_PER_HOUR` (default 20).

## Safety report contract

```json
POST /api/v1/safety-reports
{
  "plan_id": "uuid",
  "plan_exercise_id": "uuid",
  "workout_session_id": null,
  "exercise_id": "dataset-id",
  "reason": "sharp pain in the shoulder",
  "severity": "high"
}
```

- At least one of `plan_exercise_id`, `workout_session_id`, or `exercise_id`
  is required.
- The exercise ID must exist in the dataset.
- Plan/workout context must belong to the caller.
- If `plan_exercise_id` is used, `exercise_id`/`exercise_name` are derived.
- Severity defaults to `medium`; critical reports trigger the optional
  `ALERT_WEBHOOK_URL` with no reason/PII.
- Rate limit: `SAFETY_REPORT_RATE_LIMIT_PER_HOUR` (default 10).

## Admin triage

`platform_admin` is required. It is seeded manually, never granted via API.

```json
PATCH /api/v1/admin/safety-reports/{id}
{
  "status": "triaged",
  "severity": "critical",
  "resolution_note": "reviewing with safety reviewer"
}
```

Allowed transitions:

```text
open      -> triaged | resolved | dismissed
triaged   -> resolved | dismissed
resolved  -> terminal
dismissed -> terminal
```

- `triaged_at` is set on first triage.
- `resolved_at`/`resolved_by` are set on resolve/dismiss.
- Invalid transitions return `409 invalid_safety_transition`.
- Severity changes and status changes are audited separately.
- Resolution-note changes are audited without storing the note text.

## Admin metrics

`GET /api/v1/admin/quality-summary` returns:

- total plans and feedback;
- average rating;
- reports by status and severity;
- reports per 1,000 plans;
- median resolution time in hours.

## Audit

Actions include:

- `feedback.submitted`
- `safety_report.created`
- `safety_report.triaged`
- `safety_report.resolved`
- `safety_report.dismissed`
- `safety_report.severity_changed`
- `safety_report.note_updated`

Audit metadata contains IDs, enum values, and booleans only. It never contains
comments, pain areas, report reasons, resolution notes, email, or tokens.

## Tests

`tests/integration/test_feedback.py` covers:

- feature flag;
- feedback submission and validation;
- feedback rate limit;
- safety report from plan and workout;
- unknown exercise rejection;
- safety report rate limit;
- admin authorization;
- triage transitions and terminal-state rejection;
- filters, pagination, feedback list, audit, quality summary;
- PII-free audit metadata;
- critical alert hook;
- OpenAPI paths.

`tests/integration/test_migrations.py` checks the P0.4 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
FEEDBACK_ENABLED=true
FEEDBACK_RATE_LIMIT_PER_HOUR=20
SAFETY_REPORT_RATE_LIMIT_PER_HOUR=10
ALERT_WEBHOOK_URL=https://hooks.slack.com/...
```

```bash
alembic upgrade head
```

Grant platform admin manually:

```sql
INSERT INTO user_roles (id, user_id, role, granted_at)
SELECT gen_random_uuid(), id, 'platform_admin', now()
FROM users
WHERE email = 'admin@example.com'
  AND NOT EXISTS (
    SELECT 1 FROM user_roles
    WHERE user_id = users.id
      AND role = 'platform_admin'
      AND org_id IS NULL
  );
```

## Known limitations

- No trainer/medical reviewer role yet; platform admin is the safety owner.
- Critical alert is a best-effort webhook, not a guaranteed notification system.
- No user-facing report status notification.
- No automated exercise removal/retraining from reports.
- No appeal workflow; terminal reports can only be superseded by a new report.
