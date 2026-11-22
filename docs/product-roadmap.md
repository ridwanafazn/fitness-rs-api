# Product roadmap

## Goal

Turn the current research prototype into a product that a beginner can use
before, during, and after a workout:

> **Plan → do → review → improve**

The recommendation engine already answers “what should I train?”. The next
phases answer “how do I use this safely, consistently, and with confidence?”.

## Priorities

| Priority | Theme | Phases | Outcome |
|---|---|---:|---|
| **P0** | Layak dipakai | 4 | Account, plan persistence, workout execution, safety feedback |
| **P1** | Retensi & kepercayaan | 3 | Progress, trainer workspace, reminders |
| **P2** | Skala & bisnis | 3 | Organizations, experiments, reliability |

Total: **10 phases**.

## Phase map

### P0 — Layak dipakai

| Phase | Name | What is finished | Release | Status |
|---|---|---|---|---|
| P0.1 | Identity, profile, consent | Auth, profile, equipment, injuries, consent, delete/export | R1 | Backend done; FE pending |
| P0.2 | Plan lifecycle | Save, history, versions, swap/lock, share, PDF/ICS | R1 | Backend done; FE pending |
| P0.3 | Workout execution | Start/finish workout, set logs, notes, offline sync | R2 | Backend done; FE pending |
| P0.4 | Feedback & safety | Ratings, difficulty, pain, unsafe reports, admin triage | R1 | Backend done; FE pending |

### P1 — Retensi & kepercayaan

| Phase | Name | What is finished | Release | Status |
|---|---|---|---|---|
| P1.1 | Progress & insights | Adherence, streak, volume, PRs, weekly review | R2 | Backend done; FE pending |
| P1.2 | Trainer workspace | Invite client, review plan, comments, consent-based access | R3 | Planned |
| P1.3 | Notifications & integrations | Reminders, calendar, email/push/WhatsApp, health integrations | R3 | Planned |

### P2 — Skala & bisnis

| Phase | Name | What is finished | Release |
|---|---|---|---|
| P2.1 | Organizations, billing | Gym/org, seats, roles, subscription, entitlements | R4 |
| P2.2 | Experimentation & quality | Event tracking, A/B, quality dashboard, research export | R4 |
| P2.3 | Scale & reliability | Redis, workers, caching, SLO, tracing, backups, DR | R5 |

## Release plan

| Release | Contents | Why |
|---|---|---|
| **R1** | P0.1 + P0.2 + P0.4 | Product can be used, saved, shared, and reported |
| **R2** | P0.3 + P1.1 | Real workout loop + progress |
| **R3** | P1.2 + P1.3 | Trainer trust + reminders |
| **R4** | P2.1 + P2.2 | Gym/B2B + learning loop |
| **R5** | P2.3 | Scale, reliability, and operational maturity |

Do not start R4 before there are real users. Do not start R5 before load or
reliability pain is measurable.

## Success metrics

### Engineering

- p95 recommendation latency < 1 s
- p95 saved-plan read < 300 ms
- 0 cross-tenant data leaks
- 0 unsafe exercise in saved plans after injury constraints
- ≥ 99% successful workout sync (including retries)
- error rate < 1% on core endpoints

### Product

- onboarding completion rate
- plan generation → save rate
- workout start → completion rate
- 7-day and 28-day return rate
- export/share rate
- feedback completion rate
- unsafe-report resolution time

### Research

- injury violation rate = 0
- body-part coverage and exercise diversity
- expert safety/quality score
- user comprehension, trust, and willingness to use
- rule-only vs hybrid comparison
- reproducibility across seeds

## Non-goals for now

- Replacing a trainer, physiotherapist, or doctor
- Medical diagnosis or rehabilitation prescriptions
- Social network/feed
- Real-time multiplayer
- Microservices/Kubernetes
- LLM chatbot as the core product
- Blockchain/tokens
- Native mobile apps before PWA proves demand

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Health data privacy | Consent, minimization, access control, deletion, encryption |
| Unsafe recommendations | Hard constraints, safety reports, expert review, disclaimers |
| Scope explosion | Phase gates and release plan |
| Cold-start latency | Keep-alive, paid instance, timeout/retry UX |
| Trainer access misuse | Explicit consent, scoped access, audit log, revoke |
| Algorithm overclaim | Publish evaluation, limitations, and baseline comparison |
| Frontend/backend drift | OpenAPI contract + generated TypeScript client |
| Multi-tenant leak | `org_id` on every tenant-owned table + isolation tests |

## Definition of done (every phase)

A phase is complete only when:

1. API contract is documented in OpenAPI and examples.
2. Database migration is reversible and tested.
3. Authorization and ownership tests pass.
4. Error envelope is consistent.
5. Unit + integration tests pass.
6. Observability exists (logs, request ID, key metrics).
7. Frontend can consume the contract without breaking old clients.
8. Rollout and rollback steps are documented.

## Effort estimate

Relative estimate for one full-stack engineer, not a promise:

| Priority | Effort |
|---|---|
| P0 | 6–10 weeks |
| P1 | 4–6 weeks |
| P2 | 6–10 weeks |

For a portfolio, P0 + P1.1 + P1.2 is already a strong product. P2 is for a real
B2B/SaaS attempt.
