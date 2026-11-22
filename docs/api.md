# API guide

Base URL: `http://127.0.0.1:8000` (local) or your deployed API URL.

Interactive docs: `/docs` (Swagger) and `/redoc`.

## Authentication

Two independent mechanisms:

1. **Recommendation API key (optional).** If `API_KEY` is set, send:
   ```http
   X-API-Key: your-key
   ```
   Requests without a valid key receive `401 unauthorized`.

2. **OIDC bearer token (P0.1, feature-flagged).** When
   `AUTH_PROFILES_ENABLED=true`, `/api/v1/me/*` requires:
   ```http
   Authorization: Bearer <access_token>
   ```
   The backend validates the token against the configured OIDC issuer,
   audience, and JWKS. Roles are read from the database, not from the token.

The public recommendation endpoint does **not** require an OIDC login.

## Endpoints

### `GET /health`

Liveness. Does not check the dataset.

```bash
curl http://127.0.0.1:8000/health
```

### `GET /ready`

Readiness. Fails with `503` if the dataset is missing/invalid. When
`DATABASE_URL` is configured, it also checks the database and returns
`database: "ok"`.

### `POST /api/v1/recommendation/`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recommendation/ \
  -H "Content-Type: application/json" \
  -d '{
    "gender": "male",
    "height_cm": 175,
    "weight_kg": 72,
    "injuries": ["lower back"],
    "available_days": 4,
    "preferred_body_part": ["chest", "biceps"],
    "preferred_equipment": ["dumbbell", "barbell"],
    "seed": 42
  }'
```

### `POST /api/v1/recommendation/by-focus`

```bash
curl -X POST http://127.0.0.1:8000/api/v1/recommendation/by-focus \
  -H "Content-Type: application/json" \
  -d '{"day_focus":"chest","injuries":["shoulder"],"seed":7}'
```

## P0.1 account endpoints

Mounted only when `AUTH_PROFILES_ENABLED=true`. Full contract:
[`p0-1-identity-and-profiles.md`](p0-1-identity-and-profiles.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/me` | Current user, roles, profile completeness, consent state |
| POST | `/api/v1/me/onboarding` | Idempotent profile + equipment + injuries + consent |
| GET/PATCH | `/api/v1/me/profile` | Read/update profile |
| PUT | `/api/v1/me/equipment` | Replace equipment list |
| PUT | `/api/v1/me/injuries` | Replace injury list (health consent required) |
| GET/POST | `/api/v1/me/consents` | Read/grant/revoke consent |
| GET | `/api/v1/me/export` | Export own data as JSON |
| DELETE | `/api/v1/me` | Request account deletion (`202`) |

## Response envelope

Success uses the endpoint-specific schema. Every response includes:

- `X-Request-ID`
- `X-Process-Time`

Errors always use:

```json
{
  "error": {
    "code": "validation_error",
    "message": "Payload request tidak valid.",
    "details": [
      {"field": "body.available_days", "message": "...", "type": "less_than_equal"}
    ]
  },
  "request_id": "...",
  "detail": "Payload request tidak valid.",
  "message": "Payload request tidak valid."
}
```

`detail` and top-level `message` are compatibility keys for older frontend
error handlers; new clients should read `error.code` and `error.message`.

## Status codes

| Code | Meaning |
|---:|---|
| 201 | Recommendation produced |
| 202 | Account deletion request accepted |
| 401 | API key or bearer token missing/invalid |
| 403 | Authenticated but not allowed, or account deletion pending |
| 409 | Consent required or update conflict |
| 413 | Request body too large |
| 422 | Validation or safety constraint failed |
| 429 | Rate limit exceeded |
| 500 | Unexpected error |
| 503 | Timeout, dataset not ready, database/auth not configured |

## Examples of safe failures

Requesting a chest session while `chest` is injured:

```json
{
  "error": {
    "code": "insufficient_exercise_pool",
    "message": "Tidak cukup latihan aman untuk menyusun jadwal pada fokus tersebut...",
    "details": {
      "day": "day_1",
      "focus": "chest",
      "required": 4,
      "available": 0,
      "injuries": ["chest"]
    }
  },
  "request_id": "..."
}
```

This is intentional: the API will not return a chest exercise for a chest
injury just to avoid an error.
