# Roles and access

## Principle

Use the smallest set of roles that supports the product. Every extra role adds
UI, tests, support cost, and a new way to leak data.

Start with:

1. **Guest** (local-only)
2. **Member / Athlete**
3. **Trainer / Coach**
4. **Platform Admin / Support**

Add later:

5. **Gym / Organization Admin**
6. **Service / API Client**

Do not add an “Expert Reviewer” role yet. It can be a permission of Platform
Admin until the review workflow is real.

---

## Role definitions

### Guest / Anonymous

A visitor who has not signed in.

**Can:**
- Generate a recommendation using the public engine.
- Keep the plan locally in the browser (IndexedDB/local storage).
- Export locally.
- Start a local workout log.

**Cannot:**
- Cloud-save plans.
- Use trainer features.
- Access progress across devices.

**Why:** removing login friction is important for a fitness product. The guest
is a **client-side mode**, not a server-side account. No guest PII is stored on
the server. This avoids privacy risk and guest-account cleanup complexity.

**Upgrade:** after signup, the frontend imports the local plan through
`POST /api/v1/plans/import` (idempotent).

---

### Member / Athlete

The primary user.

**Can:**
- Manage own profile, equipment, injuries, consent.
- Generate/save/share plans.
- Log workouts and sets.
- View own progress.
- Submit feedback and safety reports.
- Export/delete own data.
- Grant/revoke trainer access.

**Cannot:**
- Read another member's data.
- Access trainer/admin areas.

**Why:** this is the data owner and the consent owner.

---

### Trainer / Coach

A professional who coaches clients. Added in P1.2.

**Can:**
- Invite a client.
- View a client's plan, workout adherence, and feedback **only after consent**.
- Comment on plans.
- Review/approve plan changes.
- See client list.

**Cannot:**
- Browse all users.
- Access a client's data after consent is revoked.
- Change billing or platform configuration.

**Why:** trainers are a trust multiplier and a B2B wedge. Access must be
relationship-scoped, not role-wide.

---

### Gym / Organization Admin

A customer-side administrator for a gym or coaching business. Added in P2.1.

**Can:**
- Manage organization profile and branding.
- Invite/remove trainers.
- Manage seats and billing.
- View aggregate usage and adherence.
- Configure organization-level equipment profiles.

**Cannot (by default):**
- Read individual health data or injury notes.
- Read a member's private plans unless the member explicitly shares them.

**Why:** the buyer is the gym, but the health data belongs to the member.
Billing/admin access must not imply clinical access.

---

### Platform Admin / Support

Internal operator. Seeded manually; never granted through the public API.

**Can:**
- Support users.
- Triage safety reports.
- Manage dataset/algorithm configuration.
- View audit logs.
- Perform break-glass access with a reason.

**Cannot:**
- Use admin access silently. Every action is audited.
- Export health data without a reviewed process.

**Why:** safety reports need an owner. This role is the operational safety net.

---

### Service / API Client

A machine identity for integrations. Added in P2.1/P2.2.

**Can:**
- Call scoped endpoints with an API key.
- Read/write only the resources allowed by its scopes and organization.
- Receive webhooks.

**Cannot:**
- Log in to the UI.
- Access data outside its organization/scope.

**Why:** gyms and partner apps need integrations without sharing a human
account. API keys are hashed, prefixed, rotatable, and rate-limited.

---

## Role vs entitlement vs ownership

These are different concepts:

| Concept | Question | Example |
|---|---|---|
| **Role** | Who are you? | member, trainer, org_admin, platform_admin |
| **Entitlement** | What feature did you buy? | free, pro, gym_10, api_pilot |
| **Ownership** | Whose data is this? | self, client, organization |

Never encode `is_premium` inside a role. Never rely only on a JWT claim for
authorization. Check ownership and entitlement in the database/service layer.

---

## Access matrix

| Capability | Guest | Member | Trainer | Gym Admin | Platform Admin | Service Client |
|---|---:|---:|---:|---:|---:|---:|
| Generate public plan | yes | yes | yes | yes | yes | yes |
| Save own plan | local | yes | yes | yes | yes | scoped |
| Read own profile | local | yes | yes | yes | yes | no |
| Read client profile | no | no | consent | no* | break-glass | scoped |
| Read client plan | no | no | consent | no* | break-glass | scoped |
| Read client injury data | no | no | consent | no | break-glass | no |
| Write plan review | no | no | consent | no | yes | scoped |
| View org aggregate | no | no | org member | yes | yes | scoped |
| Manage org billing | no | no | no | yes | yes | scoped |
| Triage safety reports | no | no | related only | aggregate | yes | no |
| Configure dataset/algorithm | no | no | no | no | yes | no |
| Export own data | local | yes | yes | yes | yes | no |

\* Gym Admin can be granted explicit member consent or an organization-level
agreement; default is aggregate-only.

---

## Consent model

Consent is a first-class record, not a boolean in the profile.

Kinds:

- `health_data_processing` — required before storing injuries/notes.
- `research_analytics` — optional; for aggregate research.
- `trainer_sharing` — optional; per trainer/client relationship.
- `marketing` — optional; separate from product consent.

Rules:

- Consent has a version (`2026-01`) and timestamp.
- Revocation is immediate for future access; historical audit remains.
- Revoking `health_data_processing` also deletes stored injury rows.
- Trainer access requires an active `trainer_sharing` grant.
- A member can see who has access and revoke it.
- Minors: do not support without a separate legal review.

---

## Auth flow

1. Frontend authenticates with an OIDC provider (Clerk, Neon Auth, Supabase,
   Auth0, etc.).
2. Frontend sends `Authorization: Bearer <access_token>`.
3. Backend validates signature via JWKS, issuer, audience, and expiry.
4. Backend maps `(iss, sub)` to `(users.auth_issuer, users.auth_subject)`; first
   request upserts the user and assigns the default `user` role.
5. Roles are loaded from `user_roles`/`memberships`, not trusted from the token.
6. Guest mode never sends a token; it uses the public recommendation endpoint and
   local storage.

Implementation status (P0.1):

- Backend token validation, first-login upsert, roles, consent, export, and
  deletion request are implemented.
- `AUTH_DEV_MODE` (HS256) exists for local/test only and is rejected in
  production. Production requires `AUTH_ISSUER`, `AUTH_AUDIENCE`, and
  `AUTH_JWKS_URL`.
- The frontend login callback and onboarding screens are not built yet.
- Per-user rate limiting is still future work; the current limiter is IP-based.

Implementation status (P1.2):

- Trainer access is relationship-scoped (`trainer_clients`) and scope-scoped
  (`access_grants`: plans/workouts/feedback/progress).
- `trainer` is seeded manually; it is not self-granted through the API.
- Client consent is explicit on invitation acceptance and revocable anytime.
- Every trainer client-data read is audited.
- Cross-trainer access is denied at the repository/service layer.

Token rules:

- Access token short-lived; refresh handled by the provider.
- If cookies are used, add CSRF protection; bearer tokens avoid CSRF but must be
  stored safely.
- Never expose provider secrets in the frontend.
- Never put an API key in `VITE_*` variables; use a server-side proxy/BFF.

---

## Permission names (suggested)

```text
profile:read:self
profile:write:self
plan:read:self
plan:write:self
plan:share:self
workout:write:self
progress:read:self
feedback:write:self
safety:report
client:read:consented
client:review:consented
org:read
org:manage
billing:manage
safety:review
config:write
audit:read
```

Use permissions in code, roles as bundles. This makes later roles cheaper to add.

---

## Multi-tenancy rules

- Every tenant-owned table has `org_id`.
- Every user-owned table has `owner_user_id`.
- Repositories always filter by the current principal.
- Trainer/client access uses an explicit `trainer_clients`/`access_grants` row.
- Admin break-glass access requires a reason and writes an audit record.
- Add integration tests that attempt cross-user and cross-org reads.

---

## Audit events

At minimum:

- login/first-login
- consent grant/revoke
- profile/injury/equipment change
- plan create/update/share/revoke
- trainer access grant/revoke
- client-data read by trainer/admin
- safety report create/triage/resolve
- account deletion/export

Never put raw injury terms, notes, or tokens in audit metadata.

---

## Anti-patterns to avoid

- One giant `role` string with `is_premium` mixed in.
- Trusting a role from the frontend or JWT alone.
- Gym admin can read all member health data by default.
- Trainer can browse all users.
- Guest PII stored server-side without need.
- Admin access without audit.
- Hard delete without retention review.
- Sharing plans with tokens that never expire.
