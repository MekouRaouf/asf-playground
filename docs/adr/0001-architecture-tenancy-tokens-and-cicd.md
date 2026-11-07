# ADR-0001: Architecture, tenancy, token and CI/CD decisions for RelayDesk

Status: Proposed

## Context

RelayDesk (feature #8) is a multi-tenant ticketing service: organizations, RBAC, invitations, tickets, assignment, workflow, comments, audit and reporting. The repository currently holds only a trivial Python module (`app.py`) with `pytest` tests, so there is no architecture to preserve. Four decisions shape every later task and are costly to change once code exists:

1. How the codebase is structured.
2. How one organization's data is kept from another's.
3. How users authenticate and how sessions are revoked.
4. How we ship and roll back.

Forces: a small team, one deployable unit preferred, strong data-leak consequences for a tenancy bug, and a need to roll back quickly without data loss.

## Options considered

### A. Module layout
- **Modular monolith**: one deployable, one package per domain module. Pros: simple ops, transactional consistency, easy refactoring. Cons: boundaries rely on discipline.
- **Microservices**: Pros: hard boundaries. Cons: operational overhead and distributed transactions, which are unjustified at this size.
- **Layered by technical type** (all models together, all routers together): Pros: familiar. Cons: no domain boundaries and heavy coupling.

### B. Tenant isolation
- **Shared schema, `org_id` on every row, org-scoped repositories**: Pros: simple, cheap migrations. Cons: a missed filter leaks data.
- **Same, plus PostgreSQL Row-Level Security (RLS)** as defense in depth: Pros: the database enforces isolation even if the app forgets. Cons: per-request session variable, a little complexity, and a test burden.
- **Schema or database per tenant**: Pros: strongest isolation. Cons: migrations multiply per tenant and it scales poorly.

### C. Tokens
- **Server-side sessions**: Pros: easy revocation. Cons: shared session store, harder for API clients.
- **Long-lived JWT only**: Pros: stateless. Cons: cannot be revoked.
- **Short-lived JWT access token + rotating, hashed refresh tokens**: Pros: bounded exposure and revocable, with reuse detection. Cons: refresh state to store.

Password hashing: bcrypt vs **Argon2id**. Argon2id is memory-hard and is the current OWASP recommendation.

### D. CI/CD and rollback
- **Build per environment and deploy mutable tags (`latest`)**: Pros: simple. Cons: not reproducible, rollback is ambiguous.
- **Build once, immutable image tagged with the git SHA, promote the same image**: Pros: reproducible and rollback means redeploying a previous SHA. Cons: requires registry retention and discipline.
- Database rollback via down-migrations vs **backward-compatible (expand/contract) migrations**. Down-migrations risk data loss; expand/contract lets old and new code run against the same schema.

## Decision

1. **Modular monolith.** Each module (e.g. `auth`, `orgs`, `tickets`) contains `models.py`, `schemas.py`, `repository.py`, `service.py` and `router.py`. A module may call another module only through that module's `service` API, and never imports another module's models or repository. Routers call services only. Services own business rules and transactions. Repositories own queries.
2. **Tenant isolation.** Shared schema with a mandatory `org_id` on tenant-owned tables. Repositories are constructed with an org-scoped request context (resolved from the authenticated token and membership) and apply the `org_id` filter on every query. **PostgreSQL RLS is optional**: policies keyed on a per-transaction `app.org_id` setting are enabled for tenant tables as defense in depth, and may be turned on after the core modules land. Cross-tenant access tests are required for every tenant-owned endpoint.
3. **Tokens.** Passwords are hashed with Argon2id. Access tokens are short-lived JWTs (about 15 minutes) carrying user id and org claims. Refresh tokens are opaque random values, stored only as hashes, single-use and rotated on every refresh. Presenting an already-used refresh token revokes its whole token family. Logout revokes the family.
4. **CI/CD and rollback.** CI runs lint and tests, builds one Docker image tagged with the commit SHA (never `latest` for deploys), and promotes that same image through environments. Rollback means redeploying the previous SHA tag. Migrations (Alembic) must be backward-compatible: add first (expand), switch code, remove later (contract), so the previous image works against the current schema. Migrations run as a separate pre-deploy step.

## Consequences

- Module boundaries are conventions, so we enforce them in review and, where cheap, with an import-linter check in CI.
- Every tenant-owned table needs `org_id` and an index on it. Forgetting the scope in a repository is the main risk, mitigated by the scoped-repository base class, isolation tests and optional RLS. Enabling RLS later needs a migration and a connection-level setting for every request.
- Refresh-token storage adds a table and cleanup job. Access tokens cannot be revoked before expiry, which is accepted for a short TTL. Argon2 parameters need tuning for CPU and memory in deployment.
- Destructive schema changes take two releases. Rollback of data is not automatic: a bad data migration needs a forward fix.
- Registry must retain recent SHA images. Rollout steps: bootstrap the app skeleton, add the CI pipeline, then adopt the module and tenancy conventions in all feature tasks.

## Affected areas

- New: `docs/adr/`, the application package with one directory per module, `alembic/` migrations, CI workflow and Dockerfile (later tasks).
- Contracts: JWT claims (user id, org id, expiry), the refresh and logout endpoints, and the request-context dependency.
- Data: `org_id` on tenant tables, a refresh-token table (hash, family, used/revoked, expiry), optional RLS policies.
