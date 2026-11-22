# ADR 0001 — Modular monolith first

**Status:** Accepted  
**Date:** 2026-11-22

## Context

The product currently has one FastAPI service, one recommendation domain, a
small frontend, and no multi-team ownership. The next phases add profiles,
plans, workouts, feedback, trainer access, and eventually organizations. The
workload is still request/response plus a few background jobs.

## Decision

Use a **modular monolith**:

- one FastAPI application
- clear modules (`profiles`, `plans`, `workouts`, `feedback`, ...)
- Postgres for transactional data
- Redis for rate limiting/cache/queues when needed
- object storage for generated files/media
- background worker only for slow jobs

Do not introduce microservices or Kubernetes at this stage.

## Consequences

Positive:

- simple transactions and joins
- one deploy, one migration pipeline
- easy local development and testing
- lower operational cost
- easier to change domain boundaries while the product is still being shaped

Negative:

- CPU-heavy work must be moved to a worker when it grows
- one deploy can affect all modules
- module boundaries must be enforced by code review and tests

## Alternatives considered

- **Microservices:** rejected; too much operational overhead for one small team.
- **Serverless-only:** rejected for the long-running GA and future background
  jobs; the API is already a persistent web service.
- **NoSQL-only:** rejected; the data is relational (users, plans, workouts,
  consent, access grants).
