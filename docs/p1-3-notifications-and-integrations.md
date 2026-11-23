# P1.3 — Notifications, calendar, devices, and integrations

**Status:** implemented behind `NOTIFICATIONS_ENABLED=false` by default. Requires
P0.2 plans, P0.1 auth, and a database.

## Goal

Give users control over reminders and calendar access without blocking the API
on external providers. Delivery uses a durable outbox with retries; provider
secrets are encrypted.

## Scope

- Notification preferences: email/push/WhatsApp flags, reminder time, timezone,
  quiet hours, weekly review.
- Push/web device registration; tokens hashed and encrypted when a key is set.
- Durable outbox with idempotency keys, attempts, backoff, and status.
- Due workout reminders and weekly reviews.
- Authenticated and public read-only calendar feeds.
- Email unsubscribe links.
- Strava OAuth connect/disconnect with encrypted tokens.
- Google Fit/Apple Health are explicitly unsupported for now.

Out of scope:

- Real email/SMS/push provider credentials in this repository.
- Google Fit/Apple Health OAuth.
- Multi-worker queue locking in P1.3; added later in P2.3.
- Delivery receipts/analytics.
- In-app notification inbox.

## Data model

```text
notification_preferences
  id, owner_user_id, email_enabled, push_enabled, whatsapp_enabled,
  reminder_enabled, reminder_time, timezone,
  quiet_hours_start, quiet_hours_end, weekly_review_enabled,
  calendar_token_hash, calendar_token_created_at, created_at, updated_at

devices
  id, owner_user_id, platform, device_name, token_hash,
  token_ciphertext, last_seen_at, created_at, updated_at

notification_outbox
  id, owner_user_id, channel, template, payload jsonb, scheduled_at,
  status, attempts, max_attempts, idempotency_key, last_error,
  sent_at, created_at, updated_at

integration_tokens
  id, owner_user_id, provider, external_user_id,
  access_token_ciphertext, refresh_token_ciphertext, scopes jsonb,
  expires_at, status, created_at, updated_at
```

Rules:

- `notification_preferences` is one row per user.
- Device tokens are stored as SHA-256 for lookup and Fernet ciphertext for
  delivery. Without `TOKEN_ENCRYPTION_KEY`, `has_token=false` and push delivery
  is not possible.
- Outbox `idempotency_key` is unique; enqueue is a no-op if it already exists.
- Failed deliveries retry with exponential backoff up to `max_attempts`.
- Integration tokens are encrypted; raw tokens are never returned by the API.
- Calendar and unsubscribe tokens are random/HMAC, stored/verified without
  exposing PII.

## Endpoints

Mounted only when `NOTIFICATIONS_ENABLED=true`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET/PATCH | `/api/v1/me/notifications` | user | Preferences |
| POST | `/api/v1/me/notifications/test` | user | Enqueue test message |
| GET | `/api/v1/me/notifications/unsubscribe-token` | user | Email unsubscribe link |
| GET | `/api/v1/notifications/unsubscribe/{token}` | public | Unsubscribe email |
| GET/POST | `/api/v1/me/devices` | user | List/register devices |
| DELETE | `/api/v1/me/devices/{id}` | user | Remove device |
| GET | `/api/v1/me/calendar.ics` | user | Authenticated calendar |
| POST | `/api/v1/me/calendar/token` | user | Create public calendar token |
| GET | `/api/v1/calendar/{token}.ics` | public | Public calendar feed |
| GET | `/api/v1/me/integrations` | user | List active integrations |
| DELETE | `/api/v1/me/integrations/{provider}` | user | Disconnect integration |
| POST | `/api/v1/me/integrations/{provider}/authorize` | user | Start OAuth |
| POST | `/api/v1/integrations/{provider}/callback` | public | OAuth callback |

## Preferences

```json
PATCH /api/v1/me/notifications
{
  "email_enabled": true,
  "push_enabled": false,
  "whatsapp_enabled": false,
  "reminder_enabled": true,
  "reminder_time": "18:30",
  "timezone": "Asia/Jakarta",
  "quiet_hours_start": "22:00",
  "quiet_hours_end": "07:00",
  "weekly_review_enabled": true
}
```

- Time format is `HH:MM`; timezone is IANA.
- Quiet hours may wrap midnight.
- Reminders require at least one enabled channel.
- Due reminders are suppressed during quiet hours.

## Outbox and worker

Delivery modes:

- `log`: log a PII-free line and mark sent (default; safe for local).
- `webhook`: POST `{id, channel, template, payload, idempotency_key}` to
  `NOTIFICATION_WEBHOOK_URL`.
- `disabled`: no processing.

Run the worker:

```bash
DATABASE_URL=... python scripts/process_outbox.py --limit 100
DATABASE_URL=... python scripts/process_outbox.py --no-reminders --limit 100
```

The script:

1. enqueues due reminders/weekly reviews (unless `--no-reminders`),
2. processes due outbox rows,
3. retries failures with backoff,
4. prints `processed/sent/retry/failed`.

## Calendar

- Authenticated: `GET /me/calendar.ics` uses the latest active plan.
- Public: `POST /me/calendar/token` returns a one-time token and URL; the URL is
  `GET /api/v1/calendar/{token}.ics`.
- Regenerating the token invalidates the previous URL.
- No owner identity is included in the feed.

## Integrations

Strava is implemented when these are set:

```text
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REDIRECT_URI=https://api.example/api/v1/integrations/strava/callback
INTEGRATION_STATE_SECRET=...
TOKEN_ENCRYPTION_KEY=...
```

Flow:

1. `POST /me/integrations/strava/authorize` returns the Strava URL and signed
   state.
2. The browser completes Strava OAuth.
3. Strava redirects to the callback; the backend verifies state, exchanges the
   code, encrypts tokens, and stores the integration.
4. `DELETE /me/integrations/strava` revokes and clears tokens.

Google Fit/Apple Health return `422 integration_unsupported`.

## Tests

`tests/integration/test_notifications.py` covers:

- feature flag;
- preferences and validation;
- device registration/encryption/delete;
- test notification and outbox delivery;
- retry then success;
- due-reminder idempotency;
- authenticated/public calendar;
- unsubscribe;
- Strava authorize/callback/disconnect with mocked exchange;
- unsupported provider;
- OpenAPI paths.

`tests/integration/test_migrations.py` checks the P1.3 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
PLANS_ENABLED=true
NOTIFICATIONS_ENABLED=true
NOTIFICATION_DELIVERY_MODE=log
TOKEN_ENCRYPTION_KEY=<Fernet key>
INTEGRATION_STATE_SECRET=<random secret>
```

```bash
alembic upgrade head
python scripts/process_outbox.py
```

## Known limitations

- Built-in delivery is log/webhook; real email/SMS/push adapters are future
  work.
- Strava only; Google Fit/Apple Health are unsupported.
- Outbox delivery is at-least-once. P2.3 adds a worker lease
  (`locked_until`/`locked_by`) and `FOR UPDATE SKIP LOCKED` on Postgres, but a
  crash after external delivery can still duplicate a notification.
- Quiet hours suppress rather than reschedule.
- Unsubscribe currently disables email only.
- Calendar feed uses the latest active plan.
