# Fitness-RS API

Backend for a hybrid fitness-program recommender: a deterministic rule table
selects the weekly split and daily focus, then a genetic algorithm chooses the
exercises for each day from a curated exercise dataset.

This repository is the production-hardened version of the backend used in the
2025 undergraduate thesis *Sistem Rekomendasi Program Fitness Berbasis Aturan
dan Algoritma Optimasi Genetika* (UIN Sunan Gunung Djati Bandung).

- **Live API:** https://fitness-rs-api.onrender.com (Render free; cold start — see [`docs/hosting.md`](docs/hosting.md))
- **Swagger UI:** https://fitness-rs-api.onrender.com/docs
- **Health:** `/health`, readiness: `/ready`

---

## What it does

Input:

- gender, height, weight
- available training days (1–7; 6–7 are capped to 5 for backward compatibility)
- injury history (body parts, muscles, or common terms such as `knee`,
  `lower back`, `elbow`)
- preferred body parts and available equipment
- optional `seed` for reproducible runs

Output:

- BMI and BMI category
- split type (e.g. `upperlower`, `ppl+focus`)
- day-by-day focus (e.g. `upper`, `push`, `cardio`)
- exercise list per day (name, body part, equipment, muscles, image URL)
- the seed, dataset version, and algorithm version used

**Scope:** the API recommends exercise selection and weekly structure. It does
not prescribe sets, reps, load, tempo, or progressive overload.

---

## Architecture

```text
POST /api/v1/recommendation
        │
        ▼
Pydantic validation (enums, bounds, injury vocabulary)
        │
        ▼
Domain rule table ──► split + day focus
        │
        ▼
Safe exercise pool ──► injury hard constraint + focus + equipment
        │
        ▼
Genetic algorithm (one run per day, seeded)
        │
        ▼
Output validation ──► no injured body part, complete schedule
        │
        ▼
JSON response + X-Process-Time + X-Request-ID
```

Key design decisions:

- **Safety is a hard constraint.** Injured body parts are removed from the
  candidate pool before the GA runs. The final output is validated again. The
  API never falls back to the full dataset when a safe pool is too small; it
  returns `422` instead.
- **The rule engine is deterministic.** The original single-rule Experta
  implementation is preserved in git history. The runtime uses an equivalent
  decision table because Experta 1.9.4 (2019) is unmaintained and does not fit
  a modern Python runtime.
- **The GA is reproducible.** Every request returns the seed used. Set `seed`
  in the payload to reproduce a run exactly.
- **The dataset is validated at startup.** Missing columns, duplicate IDs,
  duplicate names, and unknown body parts/equipment fail fast.

---

## Quick start

### Local

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs.

> Python 3.11+ is required. The production container uses Python 3.12; CI runs
> 3.11 and 3.12. Python 3.9/3.10 are end-of-life upstream.

### Docker

```bash
docker build -t fitness-rs-api .
docker run --rm -p 8080:8080 --env-file .env fitness-rs-api
```

---

## API

### `POST /api/v1/recommendation/`

```json
{
  "gender": "male",
  "height_cm": 175,
  "weight_kg": 72,
  "injuries": ["lower back"],
  "available_days": 4,
  "preferred_body_part": ["chest", "biceps"],
  "preferred_equipment": ["dumbbell", "barbell"],
  "seed": 42
}
```

Example response (truncated):

```json
{
  "bmi": 23.51,
  "bmi_category": "Normal",
  "split_type": "upperlower",
  "schedule": {
    "day_1": "upper",
    "day_2": "lower",
    "day_3": "upper",
    "day_4": "lower"
  },
  "days": [
    {
      "day": 1,
      "day_focus": "upper",
      "exercises": [
        {
          "exercise_id": "5111",
          "exercise_name": "hanging toes to bar",
          "body_part": "abs",
          "equipment": ["body weight"],
          "primary_muscle": ["rectus abdominis"],
          "secondary_muscle": ["obliques"],
          "exercise_image": "https://..."
        }
      ]
    }
  ],
  "seed": 42,
  "dataset_version": "3d1e7609c1480520",
  "algorithm_version": "2.0.0",
  "warnings": []
}
```

### `POST /api/v1/recommendation/by-focus`

```json
{
  "day_focus": "chest",
  "injuries": ["shoulder"],
  "preferred_equipment": ["dumbbell"],
  "seed": 7
}
```

### Errors

All expected errors use the same envelope:

```json
{
  "error": {
    "code": "insufficient_exercise_pool",
    "message": "Tidak cukup latihan aman untuk menyusun jadwal pada fokus tersebut.",
    "details": {
      "day": "day_1",
      "focus": "chest",
      "required": 4,
      "available": 0
    }
  },
  "request_id": "3f2c..."
}
```

Common codes:

| Code | HTTP | Meaning |
|---|---:|---|
| `validation_error` | 422 | Invalid payload or enum value |
| `unknown_injury` | 422 | Injury term not supported |
| `insufficient_exercise_pool` | 422 | Not enough safe exercises |
| `consent_required` | 409 | Health data requires consent |
| `conflict` | 409 | Concurrent update or consent-version mismatch |
| `account_deletion_pending` | 403 | Account is scheduled for deletion |
| `rate_limit_exceeded` | 429 | Too many requests |
| `request_too_large` | 413 | Request body exceeds the limit |
| `unauthorized` | 401 | Missing/invalid API key or bearer token |
| `forbidden` | 403 | Authenticated but not allowed |
| `auth_not_configured` | 503 | OIDC/auth settings are missing |
| `database_not_configured` | 503 | `DATABASE_URL` is missing |
| `internal_error` | 500 | Unexpected server error |
| `service_unavailable` | 503 | Computation timeout or auth provider unavailable |

---

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `staging`, `production`, `test` |
| `DATASET_PATH` | `data/fitness_dataset.csv` | Exercise CSV |
| `CORS_ORIGINS` | `*` | Allowed origins; set explicit values in production |
| `ALLOWED_HOSTS` | `*` | TrustedHost allowlist |
| `API_KEY` | empty | Optional `X-API-Key` gate |
| `DATABASE_URL` | empty | Postgres/SQLite URL; required for P0.1 |
| `DB_AUTO_CREATE` | `false` | Create tables locally/tests only; use Alembic in production |
| `AUTH_ENABLED` | `false` | Validate OIDC bearer tokens |
| `AUTH_PROFILES_ENABLED` | `false` | Mount `/api/v1/me` endpoints |
| `AUTH_ISSUER` | empty | OIDC issuer |
| `AUTH_AUDIENCE` | empty | OIDC audience |
| `AUTH_JWKS_URL` | empty | HTTPS JWKS endpoint |
| `AUTH_ALGORITHMS` | `RS256,ES256` | Allowed JWT algorithms |
| `AUTH_DEV_MODE` | `false` | HS256 local/test only; rejected in production |
| `AUTH_DEV_SECRET` | empty | Dev-only signing secret, min 32 chars |
| `CONSENT_POLICY_VERSION` | `2026-01` | Consent policy version |
| `ACCOUNT_DELETION_GRACE_DAYS` | `30` | Hard-delete window (job future work) |
| `RATE_LIMIT_ENABLED` | `true` | Enable the rate-limit middleware |
| `RATE_LIMIT` | `120/minute` | Default limit |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Use Redis for multiple instances |
| `TRUST_PROXY_HEADERS` | `true` | Trust `X-Forwarded-For` only behind your proxy |
| `MAX_REQUEST_BYTES` | `16384` | Reject oversized bodies |
| `REQUEST_TIMEOUT_SECONDS` | `15` | Recommendation timeout |
| `GA_NUM_GENERATIONS` | `25` | GA generations |
| `GA_SOL_PER_POP` | `20` | Population size |
| `GA_NUM_PARENTS_MATING` | `8` | Parents per generation |
| `GA_MUTATION_PERCENT_GENES` | `12` | Mutation rate |
| `GA_STOP_CRITERIA` | `saturate_8` | PyGAD stop criterion |
| `GA_RANDOM_SEED` | empty | Fixed seed for local research |
| `DOCS_ENABLED` | `true` | Expose `/docs` and `/openapi.json` |
| `METRICS_ENABLED` | `true` | Expose `/metrics` |

Production checklist:

1. Set `ENVIRONMENT=production`.
2. Set explicit `CORS_ORIGINS` and `ALLOWED_HOSTS`. Tighten them after
   confirming the frontend origin.
3. Set `API_KEY` if the recommendation API is public.
4. Set `TRUST_PROXY_HEADERS=true` only behind your proxy.
5. Use Redis for `RATE_LIMIT_STORAGE_URI` if you run more than one instance.
6. Keep `/ready` as the platform health check.
7. For P0.1, set `DATABASE_URL`, run `alembic upgrade head`, and keep
   `AUTH_PROFILES_ENABLED=false` until the OIDC provider and frontend are ready.
8. Use an always-on host without cold starts; see [`docs/hosting.md`](docs/hosting.md).

---

## Accounts and profiles (P0.1)

P0.1 adds identity, profile, equipment, injury, consent, export, and deletion
endpoints. They are **feature-flagged** so the recommendation API stays unchanged
until auth is ready.

Mounted only when `AUTH_PROFILES_ENABLED=true`:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me` | Current user, roles, profile completeness, consent state |
| POST | `/api/v1/me/onboarding` | Idempotent profile + equipment + injuries + consent |
| GET/PATCH | `/api/v1/me/profile` | Read or partially update profile |
| PUT | `/api/v1/me/equipment` | Replace equipment list |
| PUT | `/api/v1/me/injuries` | Replace injury list (health consent required) |
| GET/POST | `/api/v1/me/consents` | Read/grant/revoke consent |
| GET | `/api/v1/me/export` | Export own data as JSON |
| DELETE | `/api/v1/me` | Request account deletion |

Auth is provider-agnostic OIDC: the backend validates `Authorization: Bearer`
against `AUTH_ISSUER`, `AUTH_AUDIENCE`, and `AUTH_JWKS_URL`. Roles are loaded from
the database, never trusted from the token. There is no password storage.

Local development:

```bash
DATABASE_URL=sqlite+pysqlite:///./local.db \
DB_AUTO_CREATE=true \
AUTH_ENABLED=true AUTH_PROFILES_ENABLED=true \
AUTH_DEV_MODE=true AUTH_DEV_SECRET=change-me-32-characters-minimum \
AUTH_ISSUER=https://dev.local AUTH_AUDIENCE=jymz-dev \
uvicorn app.main:app --reload
```

Mint a local token:

```bash
TOKEN=$(python scripts/mint_dev_token.py --sub dev-user)
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/v1/me
```

Production:

```bash
DATABASE_URL="postgresql://..." alembic upgrade head
```

- Injuries cannot be stored without active `health_data_processing` consent.
- Revoking health consent deletes stored injuries.
- `DELETE /me` records a request and blocks authentication; the hard-delete
  retention job is future work.
- `AUTH_DEV_MODE` is rejected in production.
- Keep `AUTH_PROFILES_ENABLED=false` until the frontend login/onboarding flow
  exists.

See [`docs/p0-1-identity-and-profiles.md`](docs/p0-1-identity-and-profiles.md)
for the full contract and [`docs/hosting.md`](docs/hosting.md) for deployment.

---

## Quality gates

```bash
ruff check app tests
mypy app
pytest -q --cov=app --cov-report=term-missing
pip-audit -r requirements.txt
```

The test suite covers:

- 20 rule-table combinations (gender × BMI × days)
- injury mapping (`knee`, `lower back`, body parts, muscles, unknown terms)
- focus mapping and exercise counts
- fitness-function rewards/penalties
- dataset validation (duplicates, missing columns, unknown vocabulary)
- GA invariants (unique exercises, seed reproducibility, tiny-pool failure)
- API contract, error envelope, API key, request size, rate limit
- safety regression: an injured body part must never appear in output
- P0.1 auth: expired/wrong issuer/audience/signature, unsigned token, first-login
  idempotency, JWT roles not trusted, unverified email not stored
- P0.1 profile/consent: onboarding idempotency, injury consent gate, unknown
  injury/equipment rejection, consent revoke deletes injuries, export isolation,
  deletion request, PII-free audit metadata
- Alembic upgrade/downgrade on a fresh SQLite database

CI runs the same gates on Python 3.11 and 3.12 and builds/smokes the Docker
image.

---

## Project structure

```text
app/
  api/            thin HTTP routes and dependencies
  auth/           OIDC/JWKS validation, principal, first-login upsert
  core/           settings, errors, logging, middleware, security
  db/             SQLAlchemy models, engine/session, URL normalization
  domain/         pure rules, focus mapping, injury taxonomy, fitness
  rules/          compatibility facade for the old rule-engine API
  schemas/        Pydantic request/response models
  services/       dataset loader, filter, GA, orchestration, identity, audit
data/             222-row curated exercise dataset
migrations/       Alembic environment and P0.1 migration
tests/            unit, integration, and API tests
docs/             algorithm, API, deployment, hosting, audit, and product plans
scripts/          benchmark helper
```

---

## Product roadmap and plans

The backend is being extended beyond the recommendation engine into a usable
product (accounts, saved plans, workout logging, feedback, trainer access).

Start with:

- [`docs/README.md`](docs/README.md) — documentation index
- [`docs/product-roadmap.md`](docs/product-roadmap.md) — 3 priorities and 10 phases
- [`docs/backend-plan.md`](docs/backend-plan.md) — backend scope per phase
- [`docs/roles-and-access.md`](docs/roles-and-access.md) — roles, RBAC, consent
- [`docs/data-model.md`](docs/data-model.md) — tables and invariants
- [`docs/p0-1-identity-and-profiles.md`](docs/p0-1-identity-and-profiles.md) — implemented P0.1 contract
- [`docs/hosting.md`](docs/hosting.md) — always-on hosting without cold starts

Frontend: [`ridwanafazn/city-master-v2`](https://github.com/ridwanafazn/city-master-v2), live at [`jymz.pages.dev`](https://jymz.pages.dev/).

---

## Deployment

The API is a persistent Python web service. **Do not use a sleeping free tier**
(Render free/Koyeb free) for production because the cold start is unacceptable.
See [`docs/hosting.md`](docs/hosting.md) for always-on free/PAYG options.

The repository includes a Dockerfile and `render.yaml`; Render is kept as a
compatibility target, not the recommended long-term host. The old `vercel.json`
was removed because the computational workload and Python runtime do not fit the
serverless path cleanly.

```bash
# Docker
docker build -t fitness-rs-api .
docker run --rm -p 8080:8080 --env-file .env fitness-rs-api
```

Container/platform settings:

- health check: `/ready`
- start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- one worker per instance; scale with instances, not threads, because the GA is
  CPU-bound
- set `TRUST_PROXY_HEADERS=true`
- set `CORS_ORIGINS` and `API_KEY` in the dashboard
- for P0.1: set `DATABASE_URL` and run `alembic upgrade head` before traffic

See [`docs/deployment.md`](docs/deployment.md) and
[`docs/hosting.md`](docs/hosting.md) for details.

---

## Research context and limitations

- The thesis evaluated convergence, diversity, and expert validation with one
  personal trainer (16 July 2025). The production hardening does not add new
  clinical evidence.
- The system is **not medical advice** and does not replace a trainer or
  physiotherapist.
- Injury mapping is conservative and body-part based; it does not yet model
  movement-specific contraindications (e.g. deep knee flexion vs. hip hinge).
- The dataset has 222 exercises, with hamstrings and neck underrepresented.
- The GA fitness weights are inherited from the thesis; they are documented in
  `docs/algorithm.md` but not clinically calibrated.
- Multi-expert validation, user studies, and ablation experiments are future
  research work.

See `docs/audit.md` for the hardening audit and remaining roadmap.

---

## License

MIT. See `LICENSE`.
