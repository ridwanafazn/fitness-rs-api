# API guide

Base URL: `http://127.0.0.1:8000` (local) or the Render URL.

Interactive docs: `/docs` (Swagger) and `/redoc`.

## Authentication

Authentication is optional. If `API_KEY` is set, send:

```http
X-API-Key: your-key
```

Requests without a valid key receive `401 unauthorized`.

## Endpoints

### `GET /health`

Liveness. Does not check the dataset.

```bash
curl http://127.0.0.1:8000/health
```

### `GET /ready`

Readiness. Fails with `503` if the dataset is missing/invalid.

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
  "request_id": "..."
}
```

## Status codes

| Code | Meaning |
|---:|---|
| 201 | Recommendation produced |
| 401 | API key missing/invalid |
| 413 | Request body too large |
| 422 | Validation or safety constraint failed |
| 429 | Rate limit exceeded |
| 500 | Unexpected error |
| 503 | Timeout / dataset not ready |

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
