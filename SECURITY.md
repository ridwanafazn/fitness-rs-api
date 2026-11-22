# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Contact the
maintainer privately (GitHub: `@ridwanafazn`) with:

- affected endpoint/version
- reproduction steps
- expected vs. actual behavior
- any suggested fix

## Deployment expectations

- Set `API_KEY` for any public deployment that still uses the API-key gate.
- Set explicit `CORS_ORIGINS` and `ALLOWED_HOSTS` as soon as the frontend
  origin is known. The default is `*` only to keep the existing frontend
  working during migration.
- Keep `TRUST_PROXY_HEADERS=true` only when the API is behind a proxy you
  control (Render/Fly/Cloud Run); set it to `false` for direct exposure.
- Use a shared Redis store for rate limiting when running multiple instances.
- The app checks `Content-Length`; also enforce a body-size limit at your
  reverse proxy for chunked requests.
- Keep dependencies current; Dependabot is configured for pip, Docker, and
  GitHub Actions.
- Never enable `AUTH_DEV_MODE` in production. Production must use an OIDC
  issuer, audience, and HTTPS JWKS URL.
- Keep `DATABASE_URL`, `AUTH_DEV_SECRET`, and provider secrets in the platform
  secret store, never in the repository or frontend `VITE_*` variables.
- Use a least-privilege database role for the application; run migrations with a
  separate migration role where possible.
- Set `DB_AUTO_CREATE=false` in production and run `alembic upgrade head` as a
  release step.
- Back up the database and test restore before storing real user data.
- Review `docs/p0-1-identity-and-profiles.md` and `docs/hosting.md` before
  enabling `AUTH_PROFILES_ENABLED`.

## Data handling (P0.1)

- The recommendation endpoint remains public and stateless.
- Account/profile endpoints are mounted only when `AUTH_PROFILES_ENABLED=true`.
- `users`, `profiles`, `user_equipment`, `user_injuries`, `consents`,
  `user_roles`, and `audit_log` are stored in Postgres (SQLite is local/test only).
- Injuries are health-adjacent data. They are stored only with active
  `health_data_processing` consent; revoking consent deletes the stored injury
  rows.
- Email is stored only when the OIDC provider marks it verified.
- Audit metadata must not contain injury terms, notes, email, or tokens.
- `DELETE /me` records a deletion request and blocks authentication; the
  hard-delete retention job is future work.
- Do not add new categories of health data without reviewing consent, retention,
  and access controls.

## Scope

This is a fitness recommendation API, not a medical device. It must not be
used as a substitute for medical advice, diagnosis, or treatment.
