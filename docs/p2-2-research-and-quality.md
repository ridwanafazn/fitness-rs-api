# P2.2 — Research, experimentation, and quality

**Status:** implemented behind `RESEARCH_ENABLED=false`. Requires P0.1
auth/profile and a database. This remains a free hobby/research project.

## Goal

Give the project a small, honest learning loop:

- collect a fixed set of product events without PII;
- run simple deterministic experiments without an external feature-flag
  service;
- register dataset/algorithm versions so reports can be reproduced;
- let a platform admin record expert quality reviews;
- produce aggregate research reports and a PII-redacted export.

No fake metrics, no LLM scoring, no medical claims, and no paid analytics or
experimentation vendor.

## Scope

- Consent-gated events with an allowlist and flat, PII-safe properties.
- Deterministic experiment assignment with traffic and weighted variants.
- Dataset/algorithm version registry.
- Quality reviews with a fixed rubric.
- Research report over an explicit date window.
- PII-redacted JSON export with pseudonymous references.
- PII-free audit for admin mutations and exports.

Out of scope:

- Statistical significance, confidence intervals, or Bayesian analysis.
- Multi-armed bandits or automatic experiment promotion.
- SDKs for external apps.
- Raw event firehose / streaming.
- CSV/Parquet export, object storage, or scheduled report delivery.
- External expert accounts; quality review is a `platform_admin` capability.
- Cross-device event batching.

## Consent boundary

All user-facing research endpoints require an active
`research_analytics` consent (the existing P0.1 consent kind).

- `POST /me/events` returns `403 research_consent_required` without consent.
- `GET /me/experiments` returns an empty list without consent.
- Reports and exports include only users with active research consent at the
  time of the request. Revoking consent removes the user from aggregates and
  exports immediately.
- Events are never used for advertising or cross-site tracking.

## Data model

```text
research_events
  id, owner_user_id, name, properties jsonb, occurred_at, received_at,
  idempotency_key, created_at

experiments
  id, key (unique), name, description, status, variants jsonb,
  traffic_percent, created_by, started_at, ended_at, created_at, updated_at

experiment_assignments
  id, experiment_id, user_id, variant, assigned_at, exposed_at
  unique(experiment_id, user_id)

research_versions
  id, kind (dataset|algorithm), version, checksum, row_count,
  metadata jsonb, created_at
  unique(kind, version)

quality_reviews
  id, reviewer_user_id, subject_type, subject_id, status, rubric jsonb,
  notes, created_at, updated_at
```

Rules:

- Event idempotency is unique per `(owner_user_id, idempotency_key)`.
- Experiment assignment is unique per `(experiment_id, user_id)` and is never
  rewritten.
- Quality review subject is a plan version UUID, dataset version, or algorithm
  version. Dataset/algorithm subjects must exist in `research_versions`.
- Admin audit metadata never contains quality notes, event properties, export
  secrets, emails, or health data.

## Event schema

Allowlisted names:

```text
app_opened
recommendation_viewed
plan_generated
plan_saved
plan_shared
workout_started
workout_completed
set_logged
feedback_submitted
safety_report_submitted
trainer_invitation_accepted
calendar_connected
integration_connected
organization_joined
experiment_exposed
```

Properties:

- flat object only (no nested objects/lists);
- at most 20 keys, 2048 bytes serialized;
- scalar values only: string (≤200), int/float (finite, ≤1e9), boolean, null;
- sensitive key markers are rejected, including email, phone, address, name,
  note, comment, reason, injury, pain, token, secret, password, birth, location,
  user/plan/workout/session IDs, and device;
- `occurred_at` may be at most 5 minutes in the future and 30 days in the past;
- per-user rate limit (`RESEARCH_EVENT_RATE_LIMIT_PER_HOUR`, default 200).
- Idempotency key is optional and scoped per user.

Example:

```json
POST /api/v1/me/events
{
  "name": "plan_generated",
  "properties": {"surface": "mobile", "duration_bucket": "1_5m"},
  "idempotency_key": "evt-2026-11-23-001"
}
```

## Experiments

Experiment:

```json
POST /api/v1/admin/experiments
{
  "key": "onboarding-copy",
  "name": "Onboarding copy",
  "status": "running",
  "traffic_percent": 50,
  "variants": [
    {"key": "control", "weight": 50},
    {"key": "treatment", "weight": 50}
  ]
}
```

Assignment:

1. Compute SHA-256 of `experiment.key:user_id`.
2. Use the first 32 bits for the traffic gate.
3. Use the next 32 bits for weighted variant selection.
4. Persist the assignment on the first `GET /me/experiments`.
5. Set `exposed_at` the first time the assignment is returned.

Properties:

- deterministic and stable for the same experiment key/user;
- 2–4 variants, each weight 1–100;
- traffic 0–100; 0 means no assignment;
- pausing stops new assignments and hides assignments from the user endpoint;
- resuming keeps existing assignments;
- editing variants does not rewrite historical assignments; reports include
  removed variants if assignments still reference them;
- experiment keys are unique.

## Version registry

`POST /api/v1/admin/research/versions/register` snapshots the currently loaded
dataset and application/algorithm version:

- dataset version (SHA-256 prefix from the loader), checksum, exercise count;
- algorithm version (`APP_VERSION`), GA parameters, dataset version.

Registration is idempotent. Reports and exports include the registry so a
window can be interpreted against exact dataset/algorithm versions.

## Quality reviews

Platform admins can record expert-style reviews:

- subject types: `plan_version`, `dataset_version`, `algorithm_version`;
- statuses: `pending`, `in_review`, `approved`, `changes_requested`;
- rubric keys: `safety`, `variety`, `equipment_fit`, `clarity`, `progression`;
- scores are integers 1–5;
- notes are internal and never included in research exports or audit metadata.

This is a lightweight record of review, not a replacement for a real clinical
or expert validation study.

## Research report

`GET /api/v1/admin/research/report?start=...&end=...`

- `start` and `end` are required ISO 8601 timestamps;
- the window must be positive and at most 366 days;
- only users with active research consent are counted;
- report fields:
  - event total, unique users, counts by name;
  - plan total and counts by dataset/algorithm version;
  - workout total/completed/completion rate;
  - feedback total and average rating;
  - safety-report total and counts by severity/status;
  - version registry;
  - per-experiment assignment/exposure/variant/event counts.
- `generated_at` and the exact window are included. Re-running the same window
  against the same data produces the same aggregate values.

## Research export

`GET /api/v1/admin/research/export?start=...&end=...`

Requires `RESEARCH_EXPORT_SECRET` (minimum 32 characters). If missing, the API
returns `503 research_export_not_configured`.

Redaction rules:

- only users with active research consent;
- user/plan/workout IDs are replaced with deterministic HMAC-SHA256 pseudonyms
  scoped by `RESEARCH_EXPORT_SECRET`;
- no email, display name, plan title, workout notes, feedback comment/pain area,
  safety reason, resolution note, or raw user/plan/workout UUID;
- event properties are re-validated and sensitive keys are dropped;
- JSON only;
- hard caps: 2000 events, 1000 plans, 1000 workouts, 500 feedback rows,
  200 safety reports; each cap is reported in `truncated`.

Every export writes an audit row with the window, counts, and truncation data —
never the secret or row contents.

## Endpoints

Mounted only when `RESEARCH_ENABLED=true`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/me/events` | user + consent | Submit event |
| GET | `/api/v1/me/experiments` | user + consent | Assignments/exposures |
| POST | `/api/v1/admin/research/versions/register` | platform admin | Register versions |
| GET | `/api/v1/admin/research/versions` | platform admin | List versions |
| GET | `/api/v1/admin/research/report` | platform admin | Aggregate report |
| GET | `/api/v1/admin/research/export` | platform admin | Redacted export |
| POST | `/api/v1/admin/experiments` | platform admin | Create experiment |
| GET | `/api/v1/admin/experiments` | platform admin | List experiments |
| GET | `/api/v1/admin/experiments/{id}` | platform admin | Experiment report |
| PATCH | `/api/v1/admin/experiments/{id}` | platform admin | Update experiment |
| POST | `/api/v1/admin/quality-reviews` | platform admin | Create review |
| GET | `/api/v1/admin/quality-reviews` | platform admin | List reviews |
| GET | `/api/v1/admin/quality-reviews/{id}` | platform admin | Review detail |
| PATCH | `/api/v1/admin/quality-reviews/{id}` | platform admin | Update review |

## Error codes

| Code | Status | Meaning |
|---|---|---|
| `research_consent_required` | 403 | No active research consent |
| `research_event_invalid` | 422 | Invalid event or persistence conflict |
| `experiment_not_found` | 404 | Experiment missing |
| `experiment_conflict` | 409 | Duplicate key/version conflict |
| `experiment_invalid` | 422 | Invalid experiment payload |
| `quality_review_not_found` | 404 | Review missing |
| `quality_review_invalid` | 422 | Invalid subject/rubric |
| `research_range_invalid` | 422 | Bad/too-wide window |
| `research_export_not_configured` | 503 | Missing export secret |

## Configuration

```text
RESEARCH_ENABLED=true
RESEARCH_EXPORT_SECRET=<32+ random characters>
RESEARCH_EVENT_RATE_LIMIT_PER_HOUR=200
```

Requires `AUTH_PROFILES_ENABLED=true` and `DATABASE_URL` in production.

## Tests

`tests/integration/test_research.py` covers:

- feature flag;
- research consent gate and revocation;
- event allowlist/property validation/idempotency/rate limit;
- deterministic assignment, exposure, pause/resume, consent gating;
- experiment validation/duplicate/access control and report counts;
- version registration idempotency and filtering;
- quality reviews for dataset and plan versions, rubric validation, audit
  redaction;
- aggregate report counts and range validation;
- PII-redacted export, consent filtering, pseudonyms, truncation flags, and
  missing-secret behavior;
- OpenAPI paths.

`tests/integration/test_migrations.py` checks the P2.2 tables on SQLite
upgrade/downgrade.

## Known limitations

- Assignment uses hashing, not a sequential allocator; traffic and weights are
  approximate at small sample sizes.
- Reports are descriptive only. There is no significance testing, confidence
  interval, or causal claim.
- Exposure is recorded when the client fetches assignments, not when a UI
  element is rendered.
- Event attribution to an experiment counts events after assignment within the
  report window.
- Export is JSON and capped; no streaming, Parquet, or warehouse delivery.
- Quality review is a platform-admin record, not an external expert workflow.
- Events have no automatic retention job yet; use the account deletion/retention
  work when it lands.
