# ADR 0002 — OIDC auth, local guest mode, and database roles

**Status:** Accepted and implemented in P0.1 (backend). Production OIDC provider
and frontend login screens are still pending.
**Date:** 2026-11-22

## Context

The current app is public and stateless. Adding saved plans, workout history,
trainer access, and billing requires identity and authorization. The existing
frontend should keep working for visitors who have not signed in.

## Decision

1. Use an **OIDC-compatible provider** for authentication. Neon Auth is the
   selected provider; the backend remains provider-agnostic.
2. Keep guest mode **local-first**: no server-side guest PII. The public
   recommendation endpoint remains available without login.
3. Validate bearer tokens in the backend with provider JWKS.
4. Store authorization data in our database:
   - role (`user`, `trainer`, `org_admin`, `platform_admin`)
   - organization membership
   - entitlements
   - ownership/consent relationships
5. Do not trust roles from JWT claims alone.
6. On first authenticated request, upsert the user by
   `(auth_issuer, auth_subject)` and assign the default `user` role.
7. Separate **role** (who you are), **entitlement** (what you bought), and
   **ownership** (whose data it is).
8. Use a local-only `AUTH_DEV_MODE` (HS256) for tests; reject it in production.

## Consequences

Positive:

- no password storage
- provider handles MFA, reset, OAuth, passkeys
- guest flow stays fast and private
- authorization is auditable and can change without reissuing tokens
- one identity model supports member, trainer, gym, and admin

Negative:

- depends on an external identity provider
- token validation and JWKS caching need care
- frontend must handle login redirects and session refresh
- server-side guest data migration is deferred; local plan import is required

## Alternatives considered

- **Custom auth/passwords:** rejected; security burden and no product benefit.
- **Roles only in JWT:** rejected; role changes would require token refresh and
  are harder to audit.
- **Server-side guest accounts:** rejected for P0; privacy and cleanup cost.
- **Anonymous-only product:** rejected; prevents history, progress, and trainer
  features.
