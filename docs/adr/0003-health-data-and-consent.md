# ADR 0003 — Health data, consent, and least privilege

**Status:** Accepted and implemented in P0.1 (backend consent, audit, export,
deletion request). Retention job and frontend consent UI are pending.
**Date:** 2026-11-22

## Context

The product handles injuries, pain reports, workout notes, and body metrics.
Even though it is not a medical device, this is sensitive health-adjacent data.
Trainers, gym admins, and platform support may need limited access.

## Decision

1. Collect only data needed for the recommendation and coaching workflow.
2. Require explicit `health_data_processing` consent before storing injuries or
   pain/notes.
3. Keep research analytics and marketing consent separate and optional.
4. Store the consent kind, policy version, grant time, and revocation time.
5. Treat trainer access as a relationship with explicit consent, never a global
   role permission.
6. Gym admins get aggregate data by default; individual health data requires
   explicit consent or a separate agreement.
7. Platform admin access is break-glass, reason-required, and audited.
8. Never log injury terms, notes, tokens, or raw email in application logs.
9. Soft delete first; hard delete through a retention job.
10. Provide user data export and account deletion.

## Consequences

Positive:

- clearer privacy posture
- safer trainer/B2B expansion
- auditable access
- easier to answer security questionnaires

Negative:

- more UI states (consent missing/revoked)
- more tests (access matrix)
- trainer workflows require invitation/consent
- deletion is asynchronous and needs retention jobs

## Alternatives considered

- **No consent, just a disclaimer:** rejected; storing injuries without consent
  is unnecessary risk.
- **Gym admin can see all client data:** rejected; violates least privilege.
- **Hard delete immediately:** rejected; needs audit/retention and recovery.
- **Anonymous analytics with full injury data:** rejected; use aggregate or
  de-identified events only.
