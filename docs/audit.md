# Hardening audit log

This file records what changed during the production-grade pass and what is
still intentionally left for future work.

## Fixed

### Safety / correctness

- **Injury fallback removed.** The old filter could return the full dataset when
  a safe pool was too small, silently reintroducing injured body parts. The new
  filter never relaxes injuries; it raises `422 insufficient_exercise_pool`.
- **Injury taxonomy added.** Common terms such as `knee`, `lower back`, `ACL`,
  `elbow`, `wrist`, `hip`, and `ankle` map to body parts. Unknown terms are
  rejected instead of ignored.
- **Hard injury constraint in the GA.** Injured body parts are removed from the
  gene space, not merely penalised. A final output check is a second safety net.
- **Composite focus fitness fixed.** The old `body_part in day_focus` check was
  always false for `upper`, `lower`, `push`, `pull`, `legs`, and `fullbody`.
  The new scorer uses the focus mapping.
- **Preferences outside gender defaults work.** A male user can request glutes;
  a female user can request chest. Focus options are the union of defaults and
  valid preferences.
- **`available_days` is 1–7 for backward compatibility.** 6–7 are explicitly
  capped to a 5-day plan and return a warning; the thesis-supported range is
  1–5.
- **No silent partial plans.** Every scheduled day must be present in the GA
  output.
- **Safe schedule adaptation.** If a focus (e.g. `legs`) has too few safe body
  parts because of an injury, the day is replaced with a specific safe focus or
  `cardio` and the response includes a warning, instead of failing the whole
  upper-body plan.
- **Reproducibility.** Requests accept `seed`; the response returns it; PyGAD
  receives a per-day seed.
- **Cross-day variety.** Exercises used on an earlier day are excluded from
  later pools when enough alternatives remain; a small penalty covers the
  unavoidable case.
- **Pool-size guard.** A safe pool smaller than the number of genes returns
  `422` instead of letting PyGAD fail with a 500.

### API / contract

- Enum validation for gender, body part, equipment, and focus.
- Case/spacing normalisation at the request boundary.
- `extra="forbid"` so typos are not silently ignored.
- Unified error envelope with `code`, `message`, `details`, and `request_id`.
- 200 for successful computation; 422 for invalid/unsatisfiable constraints.
- Request size limit and request timeout.
- `X-Request-ID` and `X-Process-Time` on every response.
- Optional `X-API-Key`.
- Optional rate limiting via the `limits` moving-window strategy.
- OpenAPI response models for error cases.

### Architecture / maintainability

- Pure `app/domain/` layer for rules, focus, injuries, and fitness.
- Dataset loading moved from pandas to the standard library, with startup
  validation.
- CSV path resolved from the project root, not the process CWD.
- Dead `csv_loader.py`, `dependencies.py`, and empty `app/models` removed.
- `pyproject.toml` with Ruff, mypy, pytest, and coverage configuration.
- 240 tests covering rules, injuries, focus, fitness, dataset, GA, API, P0.1
  auth/profile/consent, P0.2 plan lifecycle, P0.3 workout execution, P0.4
  feedback/safety, P1.1 progress, P1.2 trainer workspace, and SQLite migration
  upgrade/downgrade.
- GitHub Actions CI for Python 3.11/3.12 and Docker build.
- Docker runs as a non-root user and has a health check.
- Structured JSON logging and `/ready`.

### P0.1 identity and profiles

- SQLAlchemy 2 models and Alembic migration for `users`, `profiles`,
  `user_equipment`, `user_injuries`, `consents`, `user_roles`, and `audit_log`.
- OIDC/JWKS bearer-token validation; first-login user upsert keyed by
  `(auth_issuer, auth_subject)`; default `user` role from the database.
- Local/test `AUTH_DEV_MODE` (HS256) is rejected in production.
- Profile, equipment, injury, consent, export, and account-deletion-request
  endpoints under `/api/v1/me`, mounted only when `AUTH_PROFILES_ENABLED=true`.
- Injury consent gate; revoking health consent deletes stored injuries.
- PII-free audit metadata and explicit data export.
- P0.1 is feature-flagged so the existing recommendation deployment is unchanged.

### P0.2 plan lifecycle

- SQLAlchemy models and Alembic migration for `plans`, `plan_versions`,
  `plan_days`, `plan_exercises`, and `plan_shares`.
- Create from recommendation input or save/import an existing recommendation
  result; `Idempotency-Key` replay and conflict detection.
- Immutable version snapshots; lock, swap, and regenerate-day create a new
  version; locked exercises survive regeneration.
- Optimistic concurrency with `expected_revision` or `If-Match`.
- Owner-scoped list/detail/delete, cursor pagination, version history.
- Hashed read-only share tokens with expiry/revocation and a public endpoint
  that excludes owner PII and injury input.
- PDF (ReportLab) and ICS export, audited.
- Import safety: dataset match, focus match, no injured body part, expected
  exercise count, no duplicates.
- Mounted only when `PLANS_ENABLED=true`.

### P0.3 workout execution

- SQLAlchemy models and Alembic migration for `workout_sessions`,
  `workout_exercises`, `set_logs`, and `client_mutations`.
- Start from a plan day/version; copy exercise snapshots and injury context.
- Client-generated session/set IDs; set numbers unique per exercise; soft delete.
- Set logging with reps, weight, RPE, completion, notes.
- Completion stores duration and totals; post-completion edits are rejected.
- Exercise substitution with injury and focus safety.
- Workout history with cursor pagination and owner isolation.
- Offline batch sync with per-item savepoints and idempotent replay.
- Audit metadata excludes notes and PII.
- Mounted only when `WORKOUTS_ENABLED=true`.

### P0.4 feedback and safety

- SQLAlchemy models and Alembic migration for `feedback` and `unsafe_reports`.
- Plan/workout feedback with rating, difficulty, pain, and comment.
- Safety reports from plan exercise, workout, or dataset exercise context.
- Severity/status transitions with platform-admin triage.
- Per-user hourly rate limits.
- Optional critical-report webhook with no PII in the payload.
- Admin queue filters/pagination, feedback list, audit trail, and quality
  summary (reports per 1,000 plans, median resolution time).
- PII-free audit metadata.
- Mounted only when `FEEDBACK_ENABLED=true`.

### P1.1 progress and insights

- SQLAlchemy models and Alembic migration for `daily_metrics`,
  `personal_records`, and `weekly_reviews`.
- Rebuild-on-read aggregation from completed workouts and non-deleted sets.
- Local-date/timezone-aware daily and weekly metrics.
- Personal records: max weight, max reps, max volume.
- Endpoints for progress, completed history, and insights.
- Backfill script for one user or all users.
- Mounted only when `PROGRESS_ENABLED=true`.

### P1.2 trainer workspace

- SQLAlchemy models and Alembic migration for trainer profiles, invitations,
  client relationships, access grants, plan reviews, and comments.
- Trainer role gate; trainer role seeded manually.
- Hashed, expiring, one-time invitation tokens.
- Client-consented scopes: plans, workouts, feedback, progress.
- Scope-enforced trainer reads, comments, and plan reviews.
- Client revocation and cross-trainer isolation.
- PII-free audit for every client-data access.
- Mounted only when `TRAINER_ENABLED=true`.


### Dependencies

- Upgraded to the current FastAPI/Starlette/AnyIO/Pydantic generation.
- Upgraded PyGAD to 3.9, whose plotting/matplotlib dependency is optional; the
  runtime does not need matplotlib for the recommendation path.
- ReportLab (and Pillow, its image dependency) is included for P0.2 PDF export.
- Removed `slowapi` in favour of the `limits` moving-window middleware, which
  is compatible with the current Starlette generation.
- `pip-audit -r requirements.txt` reports no known vulnerabilities.

### Deployment

- Render remains a compatibility target (`render.yaml`); always-on hosting
  options are documented in `hosting.md`.
- Legacy `vercel.json` removed.
- `.env.example` documents every setting.
- `.dockerignore` excludes tests, docs, caches, and secrets.

## Known limitations / future work

- Injury mapping is body-part based, not movement-pattern based.
- Dataset is 222 exercises; hamstrings and neck are underrepresented.
- Fitness weights are inherited from the thesis and are not clinically tuned.
- No multi-expert validation, user study, or ablation in this engineering pass.
- P0.1/P0.2 are implemented, but no live Neon Auth branch or production
  database is configured in the repository; the frontend login/onboarding/plan
  screens are not built yet.
- Account deletion currently records a request; the hard-delete retention job
  is future work.
- Rate limiting is IP-based globally; per-user limits are future work.
- P0.2 PDF/ICS export is synchronous in-process; move to a worker/object storage
  if it grows.
- P0.3 has no server-side rest timer or progress charts; those are client-side /
  P1.1.
- P0.4 admin triage is platform-admin only; trainer/medical reviewer roles are
  P1.2.
- Critical alerts are best-effort webhooks, not guaranteed delivery.
- P1.1 rebuild-on-read is not a long-term analytics pipeline; a scheduled job
  can call the same service later.
- P1.2 invite delivery is manual until P1.3 notifications; trainer role is
  seeded manually.
- Share links are plan-wide, not per-version; no public discovery/social layer.
- `/metrics` should be protected in a public deployment.
- A shared Redis store is required for rate limiting across multiple instances.
- The in-memory `limits` store is per-process; use Redis for multiple instances.
- The legacy Experta notebook/engine is not part of runtime; it remains in git
  history for academic reference.

The execution plan for the product phases is in
[`product-roadmap.md`](product-roadmap.md).
