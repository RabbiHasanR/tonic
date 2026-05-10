# Tonic — Development Roadmap

> A multi-tenant community platform built with FastAPI + Strawberry GraphQL + PostgreSQL.
> Every space has its own gathering place — fully isolated users, posts, and conversations.

This document is the long-term plan. It is intentionally phased so each stage ships a working, useful product. Cut features, never quality.

---

## Stack

- **Language:** Python 3.12+
- **Web framework:** FastAPI
- **GraphQL:** Strawberry (code-first), via `strawberry.fastapi.GraphQLRouter`
- **Database:** PostgreSQL 16
- **ORM:** SQLAlchemy 2.x (async)
- **Migrations:** Alembic
- **Auth:** JWT (access tokens), argon2 password hashing
- **Cache / pub-sub (later phases):** Redis
- **Containerization:** Docker + Docker Compose
- **Testing:** pytest + pytest-asyncio
- **Observability (later phases):** OpenTelemetry, Prometheus, Grafana, Loki

---

## Guiding principles

1. **Ship each phase before starting the next.** No half-finished phases.
2. **Cut scope, never quality.** A small thing done well > a big thing done poorly.
3. **Justify every dependency.** Document the *why* in `DECISIONS.md`.
4. **Let problems appear before solving them.** N+1 in Phase 1 motivates DataLoader in Phase 2.
5. **Domain-organized code, not layer-organized.** `users/`, `posts/`, `comments/` — not `models/`, `resolvers/`.
6. **Postgres from day one.** No SQLite, even for dev. Future phases need real Postgres features.
7. **UUIDs for IDs.** Sequential IDs leak tenant information once multi-tenancy lands.
8. **Every model has `created_at` and `updated_at` (timezone-aware UTC) from day one.**

---

## Phase 1 — Core foundation (MVP)

> **Goal:** A working single-tenant blog with users, posts, comments — running over GraphQL.
> **Timeline:** 2–3 weekends of focused work.
> **Definition of done:** A fresh `docker compose up` brings up a server you can sign up on, log into, and post on, with a passing test suite.

### Entities

- **User** — `id (uuid)`, `email`, `password_hash`, `display_name`, `created_at`, `updated_at`
- **Post** — `id`, `author_id`, `title`, `body (markdown)`, `created_at`, `updated_at`
- **Comment** — `id`, `post_id`, `author_id`, `body`, `created_at`, `updated_at`

### Queries

- `me` — current authenticated user
- `posts(limit: Int = 20)` — newest posts first
- `post(id: ID!)` — single post with author and comments
- `user(id: ID!)` — user profile with their posts

### Mutations

- `register(email, password, displayName)` → user + token
- `login(email, password)` → token
- `createPost(title, body)` → post
- `updatePost(id, title, body)` → post (author only)
- `deletePost(id)` → boolean (author only)
- `createComment(postId, body)` → comment
- `deleteComment(id)` → boolean (author only)

### Authentication

- Email + password registration
- Argon2 password hashing
- JWT access token in `Authorization: Bearer <token>` header
- FastAPI dependency validates JWT, loads user, injects into Strawberry context
- Resolvers read `info.context.user` for auth checks

### Infrastructure

- `Dockerfile` — production-ready Python image
- `docker-compose.yml` — app + Postgres
- Alembic migrations from day one
- `.env.example` with all required env vars
- GitHub Actions CI: lint (ruff), type-check (mypy), tests (pytest)

### Project structure

```
tonic/
  app/
    users/
      models.py
      types.py
      resolvers.py
      service.py
    posts/
      ...
    comments/
      ...
    core/
      db.py
      config.py
      auth.py
      context.py
    schema.py
    main.py
  alembic/
  tests/
    integration/
    unit/
  docker-compose.yml
  Dockerfile
  pyproject.toml
  README.md
  DECISIONS.md
  ROADMAP.md
```

### Documentation deliverables

- `README.md` — what it is, how to run in 60 seconds, current phase
- `DECISIONS.md` — initial entries: Strawberry vs alternatives, code-first vs schema-first, UUID vs sequential IDs, single JWT vs refresh tokens
- Example queries in `README.md` or a `examples.graphql` file

### Explicitly out of scope for Phase 1

- Workspaces / tenancy (Phase 2)
- DataLoader (Phase 2 — let N+1 happen first to motivate it)
- Cursor pagination (Phase 2)
- Roles & permissions beyond "is the author" (Phase 3)
- Subscriptions, file uploads, search (Phase 4)
- Email verification, password reset, OAuth (later)
- Rate limiting, query complexity (Phase 5)

### Phase 1 done checklist

- [ ] Sign up via mutation works
- [ ] Login returns a valid JWT
- [ ] Authenticated user can create/update/delete their own posts
- [ ] Comments can be created and deleted
- [ ] Single GraphQL query fetches a post with its author and comments
- [ ] Alembic migrations apply cleanly on a fresh DB
- [ ] `docker compose up` works on a clean machine
- [ ] At least 10 integration tests pass via pytest
- [ ] CI pipeline green on every push
- [ ] README is accurate and a stranger could run the project
- [ ] DECISIONS.md has at least 4 entries

---

## Phase 2 — Solving the real problems

> **Goal:** Introduce multi-tenancy and the GraphQL patterns that separate tutorials from production.
> **Timeline:** 3–4 weekends.
> **Definition of done:** Multiple isolated workspaces, no cross-tenant leakage, paginated lists, no N+1 queries on common operations.

### Multi-tenancy

- New entity: **Workspace** — `id`, `slug`, `name`, `created_at`
- New entity: **Membership** — `user_id`, `workspace_id`, `joined_at`
- Posts and comments belong to a workspace
- Users can be members of many workspaces
- Workspace context resolved from request (header `X-Workspace-Slug` or part of the auth token)
- Postgres Row Level Security policies on workspaced tables (defensive; resolver-level enforcement is primary)
- Every workspaced query and mutation enforces "current user is a member of this workspace"

### DataLoader

- Introduce DataLoader for `Post.author`, `Comment.author`, `User.posts`
- Document the before/after with a benchmark in the commit message and in `DECISIONS.md`
- Per-request DataLoader instances attached to GraphQL context

### Cursor-based pagination (Relay-style)

- `posts(first: Int, after: String): PostConnection`
- `Connection`, `Edge`, `PageInfo` types
- Composite cursors over `(created_at, id)` for stable ordering
- Same pattern applied to comments and (later) all list fields

### Field-level authorization

- Drafts: `Post.body` returns null for non-authors when `Post.status = DRAFT`
- `User.email` only visible to the user themselves
- Workspace-scoped fields hidden when user is not a member

### Input validation & error handling

- Pydantic-style validation on all mutation inputs
- Structured GraphQL errors with stable error codes
- Distinguish user errors (validation, auth) from server errors

### Phase 2 done checklist

- [ ] User can create a workspace and invite themselves into it
- [ ] User can be a member of multiple workspaces
- [ ] Cross-workspace data access returns null/forbidden, even via clever queries
- [ ] DataLoader prevents N+1 on author lookups; benchmark shows the improvement
- [ ] All list queries support cursor pagination with `PageInfo`
- [ ] Drafts are invisible to non-authors
- [ ] All mutations validate input with clear error messages
- [ ] Test suite covers tenant isolation explicitly
- [ ] DECISIONS.md updated with: tenancy model, DataLoader rationale, cursor pagination design

---

## Phase 3 — Engineering depth

> **Goal:** Production-grade non-functional concerns. This is where the project starts looking like a real company's backend.
> **Timeline:** 3–5 weekends.
> **Definition of done:** Roles, audit logs, observability, and abuse prevention all working and documented.

### Roles & permissions per workspace

- Roles: `OWNER`, `ADMIN`, `MEMBER`, `GUEST`
- Permission matrix documented in `PERMISSIONS.md`
- Role checks expressed declaratively where possible (decorators or a permission module)
- Mutations gated by role: only admins can remove members, only owners can delete the workspace, etc.

### Invitations

- `inviteUser(workspaceId, email, role)` — generates a signed invite token
- Email-less flow for now: invite link is returned in the mutation response (real email in Phase 4)
- Invitee accepts via `acceptInvite(token)`
- Expiring invites (default 7 days)

### Audit logs

- New entity: **AuditEvent** — `id`, `workspace_id`, `actor_id`, `action`, `target_type`, `target_id`, `metadata (jsonb)`, `created_at`
- Logged actions: member added/removed, role changed, post deleted, workspace settings updated
- Queryable via `auditEvents(workspaceId, first, after)` — admins only

### Observability

- Structured JSON logging with correlation IDs (request ID propagated through context)
- OpenTelemetry tracing — per-resolver spans, not just per-request
- Prometheus metrics: request count, latency histogram, error count, GraphQL operation counts by name
- Grafana dashboard committed to repo (`observability/dashboards/`)
- Loki for log aggregation in docker-compose

### Query safety

- Query depth limit (default 10)
- Query complexity analysis with per-field cost weights
- Aliased query detection to prevent batched abuse
- Introspection disabled in production

### Soft delete & versioning (selected entities)

- Posts get soft delete (`deleted_at`)
- Comments get soft delete
- Notes/posts could carry a simple version history (optional in this phase)

### Phase 3 done checklist

- [ ] Four roles fully implemented with permission matrix
- [ ] Invitation flow works end-to-end (without real email yet)
- [ ] Audit log records every sensitive action
- [ ] Traces visible in Jaeger/Tempo with per-resolver spans
- [ ] Prometheus scraping works; Grafana dashboard renders
- [ ] Logs are structured JSON with correlation IDs
- [ ] Depth and complexity limits reject abusive queries
- [ ] Soft delete works without breaking foreign-key relationships
- [ ] DECISIONS.md updated with: permission model, observability stack, query safety thresholds

---

## Phase 4 — Advanced features

> **Goal:** Real-time features, search, file uploads. The features users actually feel.
> **Timeline:** 4–6 weekends.
> **Definition of done:** Real-time notifications work across multiple clients, full-text search returns relevant results, and users can upload images.

### GraphQL Subscriptions

- WebSocket transport via Strawberry's subscription support
- `commentAdded(postId)` — new comments stream to viewers
- `notificationReceived` — per-user notification stream
- Redis pub/sub backplane so subscriptions work across multiple app instances
- Sticky session / connection routing documented

### Notifications

- New entity: **Notification** — `id`, `recipient_id`, `kind`, `payload (jsonb)`, `read_at`, `created_at`
- Triggered by: comment on your post, mention, invite received, role change
- Mutations: `markNotificationRead`, `markAllNotificationsRead`
- Subscription delivers new notifications in real time

### Mentions

- `@username` in post body or comment body parses out mentions
- Mentioned users get a notification
- Cross-workspace mentions are forbidden

### Full-text search

- Postgres `tsvector` columns on posts and comments
- GIN index on the search vector
- `search(workspaceId, query, first, after): SearchConnection` with mixed result types (post / comment / user)
- Highlighting in results

### File uploads

- `graphql-multipart-request-spec` for uploads
- Avatars on User, cover images on Post, attachments on Comment
- S3-compatible storage (MinIO in docker-compose for local dev)
- Presigned URLs for downloads
- File type validation, size limits, virus scan hook (stub for now)

### Email integration

- Real emails for invites, notifications digest (daily/weekly)
- Provider-agnostic interface; default implementation logs to stdout in dev
- Background worker for sending (using a simple async task queue or RQ/Celery)

### Phase 4 done checklist

- [ ] Two browser tabs see each other's new comments live
- [ ] Subscriptions survive server restart with proper reconnection
- [ ] Notifications arrive within 1 second of the triggering event
- [ ] Mentions create notifications for mentioned users
- [ ] Full-text search returns ranked results across post/comment/user
- [ ] Image upload + display works with thumbnails
- [ ] Real invitation emails send (in a staging env or via a fake SMTP)
- [ ] DECISIONS.md updated with: subscription transport choice, search ranking strategy, file storage decisions

---

## Phase 5 — Scaling stories

> **Goal:** Demonstrate the project can scale — per-tenant rate limits, plan tiers, observability per tenant, and architectural patterns that anticipate real load.
> **Timeline:** Open-ended; this is where you go as deep as you want.
> **Definition of done:** Per-tenant resource governance works, dashboards show per-tenant health, and the architecture documentation explains how it would scale to 10k workspaces.

### Per-tenant rate limiting

- Token-bucket rate limits keyed by `(workspace_id, user_id)`
- Redis-backed counters
- Different limits for different operations (mutations stricter than queries)
- 429 responses with proper `Retry-After` headers

### Plan tiers & feature flags

- New entity: **Plan** — Free / Pro / Enterprise
- Workspaces have a `plan_id`
- Per-plan limits: max members, max posts/month, max query complexity, max file storage
- Feature flags toggleable per workspace (e.g., `audit_log_retention_days`)

### Per-tenant observability

- All metrics tagged with `workspace_id`
- Per-tenant Grafana dashboard (templated)
- Per-tenant log queries in Loki via `workspace_id` label
- Per-tenant trace queries

### Persisted queries / APQ

- Automatic Persisted Queries support
- Hash-based query allowlist for production
- Reduces request payload size and prevents arbitrary query execution from public clients

### Read replicas & query routing

- Async replica connections for read-heavy queries
- Resolver-level routing (mutations → primary, queries → replica)
- Documented consistency trade-offs

### Schema federation (optional)

- Split into multiple GraphQL services (e.g., `users` service + `content` service)
- Federation gateway in front
- Document why and when this would actually be worth doing

### Background jobs

- Move slow work off the request path: search indexing, audit log writes, notification fan-out
- Worker fleet documented in `ARCHITECTURE.md`
- Idempotency for retried jobs

### Architecture documentation

- `ARCHITECTURE.md` describing:
  - Component diagram
  - Data flow for key operations
  - Failure modes and mitigations
  - Capacity assumptions and limits
  - "How would this handle 10k workspaces / 1M users / 100 req/s" section

### Phase 5 done checklist

- [ ] Per-tenant rate limits enforced and observable
- [ ] Plan limits enforced (e.g., free plan caps members at 5)
- [ ] Per-tenant Grafana dashboard works
- [ ] Persisted queries enabled in production mode
- [ ] At least one heavy operation moved to a background worker
- [ ] `ARCHITECTURE.md` reads like a real design doc
- [ ] DECISIONS.md updated with: rate-limit algorithm, plan-enforcement strategy, federation evaluation

---

## Long-term ideas (post-Phase 5)

Things to consider only if the project keeps being interesting:

- **Mobile clients** — iOS/Android consuming the same GraphQL schema, demonstrating the multi-client value prop
- **Public read-only API** — opt-in public workspaces queryable by anonymous users, with strict query limits
- **Webhooks** — outbound events for workspace integrations
- **Custom domains per workspace** — `acme.tonic.app`
- **End-to-end encryption** for private posts (hard problem, interesting to think through)
- **Event sourcing** for audit log — rebuild state from events
- **OpenTelemetry exporters** to Honeycomb / Datadog for a "real" observability story
- **Multi-region deployment** with documented consistency trade-offs

---

## Documentation files in the repo

Maintain these alongside code. They are not optional.

| File | Purpose | Updated when |
|------|---------|--------------|
| `README.md` | What this is, how to run | Every phase |
| `ROADMAP.md` | This file — phased plan | When phases shift |
| `DECISIONS.md` | Architectural decision records | Every meaningful decision |
| `PERMISSIONS.md` | Role/permission matrix | Phase 3 onward |
| `ARCHITECTURE.md` | System design and capacity | Phase 5 |
| `CONTRIBUTING.md` | How to develop locally | Phase 2 |
| `CHANGELOG.md` | Notable changes per version | Every release tag |

---

## Anti-goals

Things this project will deliberately *not* do, to stay focused:

- No frontend in this repo (a separate companion repo if needed)
- No payments / billing — plans exist as data, not as Stripe integrations
- No mobile apps in this repo
- No AI features — the platform is content/community, not AI-generated content
- No "kitchen sink" — every feature must justify its existence in `DECISIONS.md`

---

*Built as a learning + showcase project for senior backend engineering. Each phase ships something real and useful.*