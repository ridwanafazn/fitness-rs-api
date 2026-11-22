# Fitness-RS API

Backend for a hybrid fitness-program recommender: a deterministic rule table
selects the weekly split and daily focus, then a genetic algorithm chooses the
exercises for each day from a curated exercise dataset.

This repository is the production-hardened version of the backend used in the
2025 undergraduate thesis *Sistem Rekomendasi Program Fitness Berbasis Aturan
dan Algoritma Optimasi Genetika* (UIN Sunan Gunung Djati Bandung).

- **Live API:** https://fitness-rs-api.onrender.com
- **Swagger UI:** https://fitness-rs-api.onrender.com/docs
- **Health:** `/health`, readiness: `/ready`

---

## What it does

Input:

- gender, height, weight
- available training days (1–5)
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
          "image_url": "https://..."
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
| `rate_limit_exceeded` | 429 | Too many requests |
| `request_too_large` | 413 | Request body exceeds the limit |
| `unauthorized` | 401 | Missing/invalid `X-API-Key` |
| `internal_error` | 500 | Unexpected server error |
| `service_unavailable` | 503 | Computation timeout |

---

## Configuration

All settings are environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `ENVIRONMENT` | `development` | `development`, `staging`, `production`, `test` |
| `DATASET_PATH` | `data/fitness_dataset.csv` | Exercise CSV |
| `CORS_ORIGINS` | localhost:3000,5173 | Exact allowed origins |
| `ALLOWED_HOSTS` | `*` | TrustedHost allowlist |
| `API_KEY` | empty | Optional `X-API-Key` gate |
| `RATE_LIMIT_ENABLED` | `true` | Enable the rate-limit middleware |
| `RATE_LIMIT` | `30/minute` | Default limit |
| `RATE_LIMIT_STORAGE_URI` | `memory://` | Use Redis for multiple instances |
| `TRUST_PROXY_HEADERS` | `false` | Trust `X-Forwarded-For` only behind your proxy |
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
2. Set explicit `CORS_ORIGINS` and `ALLOWED_HOSTS`.
3. Set `API_KEY` if the API is public.
4. Set `TRUST_PROXY_HEADERS=true` only behind Render/Cloud Run.
5. Use Redis for `RATE_LIMIT_STORAGE_URI` if you run more than one instance.
6. Keep `/ready` as the platform health check.

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

CI runs the same gates on Python 3.11 and 3.12 and builds/smokes the Docker
image.

---

## Project structure

```text
app/
  api/            thin HTTP routes and dependencies
  core/           settings, errors, logging, middleware, security
  domain/         pure rules, focus mapping, injury taxonomy, fitness
  rules/          compatibility facade for the old rule-engine API
  schemas/        Pydantic request/response models
  services/       dataset loader, filter, GA, orchestration
data/             222-row curated exercise dataset
tests/            unit, integration, and API tests
docs/             algorithm, API, deployment, and audit notes
scripts/          benchmark helper
```

---

## Deployment

**Render is the canonical deployment** (`render.yaml`). The old `vercel.json`
was removed because the computational workload and Python runtime do not fit
the serverless path cleanly.

```bash
# Docker
docker build -t fitness-rs-api .
docker run --rm -p 8080:8080 --env-file .env fitness-rs-api
```

Render settings:

- health check: `/ready`
- start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- one worker per instance; scale with instances, not threads, because the GA is
  CPU-bound
- set `TRUST_PROXY_HEADERS=true`
- set `CORS_ORIGINS` and `API_KEY` in the dashboard

See `docs/deployment.md` for details.

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
