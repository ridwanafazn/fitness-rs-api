# P2.1 — Free organizations and collaboration

**Status:** implemented behind `ORGANIZATIONS_ENABLED=false`. Requires P0.1
auth/profile and a database.

## Goal

Let a gym, studio, coach, or research group organize members and future
trainer/client assignments without turning the project into a commercial
billing product. This phase intentionally has **no payments, invoices,
subscriptions, seats, or entitlements**. The project is a free hobby/research
build.

## Scope

- Organizations with name, slug, type, description, website, timezone, and
  branding.
- Memberships with `owner`, `admin`, `trainer`, and `member` roles.
- Email invitations with hashed, expiring tokens and one-time display.
- Accept, decline, revoke, leave, and role changes.
- Aggregate organization summary for admins.
- PII-free audit for every organization mutation.

Out of scope:

- Billing, payments, invoices, subscriptions, seats, and entitlements.
- Gym-wide access to member plans, workouts, feedback, or injuries.
- Per-organization branding assets/CDN.
- Cross-organization trainer assignment (P2.1.2 in the old plan).
- SSO/SCIM.

## Data model

```text
organizations
  id, name, slug (unique), type, description, website, timezone,
  branding jsonb, status, created_by, created_at, updated_at

organization_memberships
  id, organization_id, user_id, role, status,
  created_at, updated_at, revoked_at

organization_invitations
  id, organization_id, email, role, token_hash (unique), status,
  invited_by, expires_at, accepted_at, declined_at,
  created_at, updated_at
```

Rules:

- `organizations.slug` is unique. A generated slug gets `-2`, `-3`, ... on
  collision.
- A membership is unique per organization/user pair. Re-inviting a revoked
  member reactivates the same row.
- Invitations are unique by token hash, expire after 14 days, and are shown
  once. Only the hash is stored.
- An organization always has at least one active `owner`.
- Only an owner can transfer ownership or remove/demote another owner.
- An admin can manage members and invitations but cannot promote to owner.
- Invitation role cannot be `owner`.
- Accepting requires the signed-in account email to match the invitation email.
- Removing a member revokes the membership immediately. Leaving follows the
  same path, except the last owner cannot leave.
- `organization_memberships` and invitations are soft-state rows (`status`),
  not hard deletes, so audit/history survives.

## Privacy boundary

Organization membership **does not** grant access to health data.

- The summary endpoint returns counts only: members, trainers, clients, and
  active plans.
- It never returns plans, workouts, feedback, injuries, or notes.
- Trainer access still goes through the P1.2 relationship and scope grants.
- A gym admin who is not a trainer sees no client health data.
- Non-members receive `404` for organization resources so the API does not
  reveal whether an organization exists.

## Endpoints

Mounted only when `ORGANIZATIONS_ENABLED=true`:

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/api/v1/orgs` | user | Create organization |
| GET | `/api/v1/me/orgs` | user | List my organizations |
| GET | `/api/v1/orgs/{org_id}` | member | Organization detail |
| PATCH | `/api/v1/orgs/{org_id}` | owner/admin | Update organization |
| GET | `/api/v1/orgs/{org_id}/members` | member | List members |
| PATCH | `/api/v1/orgs/{org_id}/members/{user_id}` | owner/admin | Change role |
| DELETE | `/api/v1/orgs/{org_id}/members/{user_id}` | owner/admin | Remove member |
| POST | `/api/v1/orgs/{org_id}/leave` | member | Leave organization |
| GET | `/api/v1/orgs/{org_id}/summary` | owner/admin | Aggregate summary |
| GET | `/api/v1/orgs/{org_id}/invitations` | owner/admin | List invitations |
| POST | `/api/v1/orgs/{org_id}/invitations` | owner/admin | Create invitation |
| POST | `/api/v1/org-invitations/{token}/accept` | user | Accept invitation |
| POST | `/api/v1/org-invitations/{token}/decline` | user | Decline invitation |

## Requests

Create:

```json
POST /api/v1/orgs
{
  "name": "Garuda Gym",
  "slug": "garuda-gym",
  "type": "gym",
  "description": "Tempat latihan",
  "website": "https://garuda.example",
  "timezone": "Asia/Jakarta",
  "branding": {"primary_color": "#123456"}
}
```

`type` is one of `gym`, `studio`, `coach`, `research`, `other`.

Invite:

```json
POST /api/v1/orgs/{org_id}/invitations
{"email": "member@example.com", "role": "trainer"}
```

The response contains the raw `token` and `invite_url` **once**. Re-sending the
same pending invitation returns `409 organization_invitation_conflict`; revoke
or wait for expiry instead.

## Error codes

| Code | Status | Meaning |
|---|---|---|
| `organization_not_found` | 404 | Organization or member missing, or caller is not a member |
| `organization_access_denied` | 403 | Member lacks the required organization role |
| `organization_invitation_not_found` | 404 | Invitation missing, used, or expired |
| `organization_invitation_conflict` | 409 | Duplicate invitation or already a member |
| `organization_conflict` | 409 | Last-owner or archived-organization rule |
| `organization_invalid` | 422 | Invalid role/invitation payload |

## Audit

Every mutation records an `AuditLog` row with:

- actor user id and role label;
- action (`organization.created`, `organization.updated`,
  `organization.invitation_created`, `organization.invitation_accepted`,
  `organization.invitation_declined`, `organization.member_role_changed`,
  `organization.member_removed`, `organization.left`);
- organization/membership/invitation id;
- non-sensitive metadata (type, role, changed field names).

Audit metadata never contains emails, invitation tokens, or health data.

## Tests

`tests/integration/test_organizations.py` covers:

- feature flag;
- create/list/detail/update and slug collision;
- invalid slug/timezone;
- owner/admin/member permission matrix;
- invitation accept/decline, replay, expiry, email mismatch, duplicates;
- member removal and leaving;
- last-owner protection and ownership transfer guard;
- cross-organization isolation;
- aggregate summary and member denial;
- invitation listing admin-only;
- PII-free audit metadata;
- OpenAPI paths.

`tests/integration/test_migrations.py` checks the organization tables on SQLite
upgrade/downgrade.

## Deployment

```text
DATABASE_URL=postgresql://...
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
ORGANIZATIONS_ENABLED=true
```

```bash
alembic upgrade head   # 0008_organizations
```

## Known limitations

- No billing/payments by design.
- Trainer/client assignment is still governed by P1.2 invitations; it is not
  yet organization-scoped. A trainer in two organizations therefore sees the
  same P1.2 client list in both.
- The summary counts P1.2 clients of organization trainers without an
  organization filter. This is aggregate-only and contains no health data.
- No organization deletion flow yet; use `status=archived` and remove members.
- Invitations are delivered manually until an email adapter exists.
