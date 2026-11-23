# Provisioned resources

**Date:** 2026-11-23

This file records non-secret infrastructure identifiers. Credentials are not
committed.

## Neon project

| Item | Value |
|---|---|
| Project | `jymz` (`super-unit-28510107`) |
| Organization | `org-summer-hat-71197051` |
| Region | `aws-ap-southeast-1` |
| Postgres | 18 |
| Default branch | `main` (`br-plain-union-b34jhwqt`) |
| Database | `neondb` |
| Migration head | `0010_outbox_lease` |

## Neon Auth

| Item | Value |
|---|---|
| Provider | `better_auth` |
| Auth base URL | `https://ep-shiny-king-b3gh2lv3.neonauth.c-4.ap-southeast-1.aws.neon.tech/neondb/auth` |
| JWKS URL | `<auth-base-url>/.well-known/jwks.json` |
| Signing | EdDSA / Ed25519 |
| Trusted domains | `https://jymz.pages.dev`, `http://localhost:5173` |
| Schema | `neon_auth` |

The backend derives `AUTH_ISSUER` and `AUTH_AUDIENCE` from the **origin** of the
Auth base URL:

```text
https://ep-shiny-king-b3gh2lv3.neonauth.c-4.ap-southeast-1.aws.neon.tech
```

## Local credentials

`neon env pull --file .env.local` wrote:

- `DATABASE_URL`
- `DATABASE_URL_UNPOOLED`
- `NEON_AUTH_BASE_URL`
- `NEON_AUTH_JWKS_URL`

`.env.local` and `.neon` are gitignored. Do not commit them.

Load them into a shell before running the app:

```powershell
Get-Content .env.local | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') {
    Set-Item -Path "Env:$($matches[1])" -Value $matches[2].Trim('"')
  }
}
```

Then set the feature flags for local development:

```text
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
PLANS_ENABLED=true
WORKOUTS_ENABLED=true
FEEDBACK_ENABLED=true
PROGRESS_ENABLED=true
TRAINER_ENABLED=true
NOTIFICATIONS_ENABLED=true
ORGANIZATIONS_ENABLED=true
RESEARCH_ENABLED=true
OPS_ENABLED=true
AUTH_ALGORITHMS=EdDSA
```

## Deployment checklist

1. Choose the always-on host (`hosting.md`).
2. Set `DATABASE_URL`, `NEON_AUTH_BASE_URL`, `AUTH_ENABLED=true`,
   `AUTH_PROFILES_ENABLED=true`, `PLANS_ENABLED=true`, `WORKOUTS_ENABLED=true`,
   `FEEDBACK_ENABLED=true`, `PROGRESS_ENABLED=true`, `TRAINER_ENABLED=true`,
   `NOTIFICATIONS_ENABLED=true`, `ORGANIZATIONS_ENABLED=true`,
   `RESEARCH_ENABLED=true`, and `OPS_ENABLED=true`.
3. `alembic upgrade head` (already at `0010_outbox_lease` on the current branch).
4. Verify `/ready` returns `database: ok`.
5. Sign in through Neon Auth and confirm `GET /api/v1/me`.
6. Test plan create/export and workout start/sync.

Render is still running with feature flags disabled and without `DATABASE_URL`;
do not enable the features there before moving to an always-on host.
