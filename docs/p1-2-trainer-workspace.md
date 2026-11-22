# P1.2 — Trainer workspace

**Status:** implemented behind `TRAINER_ENABLED=false` by default. Requires
P0.2 plans, P0.1 auth, and a database.

## Goal

A trainer can invite a client, the client grants scoped consent, and the trainer
can review plans, see permitted adherence data, comment, and leave a plan
review. Access is relationship-scoped and revocable.

## Roles and consent

- `trainer` is an application role, seeded manually.
- `platform_admin` can also use trainer endpoints.
- A client grants explicit scopes:
  - `plans`
  - `workouts`
  - `feedback`
  - `progress`
- Access is tied to one `trainer_clients` relationship.
- The client can revoke all scopes at any time.
- A trainer cannot browse all users, and cannot access another trainer's client.

## Data model

```text
trainer_profiles
  id, user_id, display_name, bio, specialties jsonb,
  years_experience, created_at, updated_at

trainer_clients
  id, trainer_user_id, client_user_id, status, created_at,
  updated_at, revoked_at

trainer_invitations
  id, trainer_user_id, client_user_id, client_email, token_hash,
  requested_scopes jsonb, status, message, expires_at,
  accepted_at, declined_at, revoked_at, created_at, updated_at

access_grants
  id, trainer_client_id, scope, granted_at, revoked_at,
  created_at, updated_at

plan_reviews
  id, plan_id, plan_version_id, trainer_user_id, status, note,
  created_at, updated_at

trainer_comments
  id, trainer_user_id, client_user_id, plan_id, workout_session_id,
  body, created_at
```

Rules:

- Invitation tokens are random, stored as SHA-256, expire after 14 days, and
  are shown only once.
- `trainer_clients` is unique per trainer/client.
- `access_grants` is unique per relationship/scope; revoke sets `revoked_at`.
- `plan_reviews` is unique per plan/trainer.
- `trainer_comments` are client-visible; revoked access does not delete history.
- Comments, invitation emails, and review notes are never logged or put in audit
  metadata.

## Endpoints

Mounted only when `TRAINER_ENABLED=true`:

| Method | Path | Actor | Purpose |
|---|---|---|---|
| GET/PUT | `/api/v1/trainer/profile` | trainer | Read/update profile |
| POST | `/api/v1/trainer/invitations` | trainer | Invite client |
| GET | `/api/v1/trainer/invitations` | trainer | List invitations |
| POST | `/api/v1/trainer/invitations/{token}/accept` | client | Accept with scopes |
| POST | `/api/v1/trainer/invitations/{token}/decline` | client | Decline |
| GET | `/api/v1/trainer/clients` | trainer | Active clients |
| GET | `/api/v1/trainer/clients/{id}/plans` | trainer | Client plans (`plans`) |
| GET | `/api/v1/trainer/clients/{id}/workouts` | trainer | Completed workouts (`workouts`) |
| GET | `/api/v1/trainer/clients/{id}/feedback` | trainer | Feedback (`feedback`) |
| GET | `/api/v1/trainer/clients/{id}/progress` | trainer | Progress (`progress`) |
| POST | `/api/v1/trainer/clients/{id}/comments` | trainer | Comment (`plans`) |
| PATCH | `/api/v1/trainer/plans/{plan_id}/review` | trainer | Review/approve plan (`plans`) |
| GET | `/api/v1/me/trainers` | client | Trainers with access |
| DELETE | `/api/v1/me/trainers/{trainer_id}` | client | Revoke access |
| GET | `/api/v1/me/trainer/comments` | client | Comments from trainers |
| GET | `/api/v1/me/trainer/reviews` | client | Plan reviews from trainers |

## Invitation flow

1. Trainer sends `POST /trainer/invitations` with the client email and requested
   scopes.
2. Response contains a one-time token and invite URL.
3. Client signs in with the matching verified email and calls
   `POST /trainer/invitations/{token}/accept` with the scopes they consent to.
4. Backend creates/reactivates `trainer_clients` and upserts active
   `access_grants` for the selected scopes.
5. Client can revoke via `DELETE /me/trainers/{trainer_id}`.

If the client account does not exist yet, the invitation stores the email. The
client must sign up with that verified email before accepting.

## Scope enforcement

Every client-data endpoint calls `_require_access(trainer, client, scope)`:

- no active relationship → `404 trainer_client_not_found`;
- relationship exists but scope missing/revoked → `403 trainer_access_denied`;
- another trainer's client → `404`.

Every access is audited with the actor trainer and client ID.

## Plan review

`PATCH /trainer/plans/{plan_id}/review` accepts:

```json
{ "status": "approved", "note": "looks safe" }
```

Statuses:

- `pending`
- `approved`
- `changes_requested`

The review records the client's current plan version. Review notes are visible
to the client through `/me/trainer/reviews`.

## Comments

`POST /trainer/clients/{id}/comments` accepts:

```json
{
  "body": "keep the first set easy",
  "plan_id": "optional-uuid",
  "workout_session_id": "optional-uuid"
}
```

The plan/workout, if provided, must belong to the client. Comments require the
`plans` scope. The client can read them via `/me/trainer/comments`.

## Audit actions

- `trainer.profile_created` / `trainer.profile_updated`
- `trainer.invitation_created`
- `trainer.invitation_accepted`
- `trainer.invitation_declined`
- `trainer.access_revoked`
- `trainer.client_plans_viewed`
- `trainer.client_workouts_viewed`
- `trainer.client_feedback_viewed`
- `trainer.client_progress_viewed`
- `trainer.comment_created`
- `trainer.plan_reviewed`

Audit metadata contains IDs, counts, scopes, and statuses only.

## Tests

`tests/integration/test_trainer.py` covers:

- feature flag;
- trainer role gating and profile;
- self/duplicate invitation rejection;
- accept/decline, wrong user, expiry;
- scope enforcement;
- cross-trainer isolation;
- client plans/workouts/feedback/progress access;
- comments and plan reviews;
- client revocation;
- PII-free audit;
- OpenAPI.

`tests/integration/test_migrations.py` checks the P1.2 tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
NEON_AUTH_BASE_URL=https://.../neondb/auth
PLANS_ENABLED=true
TRAINER_ENABLED=true
```

Seed the trainer role manually:

```sql
INSERT INTO user_roles (id, user_id, role, granted_at)
SELECT gen_random_uuid(), id, 'trainer', now()
FROM users
WHERE email = 'coach@example.com'
  AND NOT EXISTS (
    SELECT 1 FROM user_roles
    WHERE user_id = users.id
      AND role = 'trainer'
      AND org_id IS NULL
  );
```

## Known limitations

- Invite email delivery is not implemented; the trainer shares the token/URL
  manually until P1.3 notifications.
- Trainer applications/verification are manual.
- Comments require the `plans` scope; a separate `comments` scope is future work.
- Comments/reviews have no pagination yet.
- Client revocation does not delete historical comments/reviews.
- No trainer dashboard aggregates yet.
