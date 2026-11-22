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
- **`available_days` is 1–5.** The old schema accepted 6–7 but the rule table
  silently produced a 5-day plan.
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
- 128 tests covering rules, injuries, focus, fitness, dataset, GA, and API.
- GitHub Actions CI for Python 3.11/3.12 and Docker build.
- Docker runs as a non-root user and has a health check.
- Structured JSON logging and `/ready`.

### Dependencies

- Upgraded to the current FastAPI/Starlette/AnyIO/Pydantic generation.
- Upgraded PyGAD to 3.9, whose plotting/matplotlib dependency is optional; the
  runtime no longer installs Pillow/fonttools/matplotlib.
- Removed `slowapi` in favour of the `limits` moving-window middleware, which
  is compatible with the current Starlette generation.
- `pip-audit -r requirements.txt` reports no known vulnerabilities.

### Deployment

- Render is the single documented target (`render.yaml`).
- Legacy `vercel.json` removed.
- `.env.example` documents every setting.
- `.dockerignore` excludes tests, docs, caches, and secrets.

## Known limitations / future work

- Injury mapping is body-part based, not movement-pattern based.
- Dataset is 222 exercises; hamstrings and neck are underrepresented.
- Fitness weights are inherited from the thesis and are not clinically tuned.
- No multi-expert validation, user study, or ablation in this engineering pass.
- No database or user accounts; the API is stateless by design.
- `/metrics` should be protected in a public deployment.
- A shared Redis store is required for rate limiting across multiple instances.
- The in-memory `limits` store is per-process; use Redis for multiple instances.
- The legacy Experta notebook/engine is not part of runtime; it remains in git
  history for academic reference.
