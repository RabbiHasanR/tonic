# Decisions

Append-only log of every non-trivial decision made on this project.
Each entry explains *why* a choice was made — and why alternatives were not.

## When to add an entry

- Adding or removing a dependency
- Choosing one library / tool over alternatives
- Introducing or changing an architectural pattern
- Picking an approach where a sensible alternative existed (e.g. JWT vs sessions)
- Setting a non-obvious convention (e.g. all timestamps stored as UTC)

## When NOT to add an entry

- Mechanical scaffolding (new module, new query/mutation, new model class)
- Bug fixes
- Renames, formatting, cleanup

## Entry format

```
## {YYYY-MM-DD} — {Short title}
**Context:** What triggered the decision.
**Decision:** What we chose.
**Alternatives considered:** What else was on the table.
**Why this:** Why the chosen option won.
**Why not others:** Concrete reasons each alternative was rejected.
**Trade-offs accepted:** What we knowingly gave up.
```

---

## 2026-05-10 — Use FastAPI as the web framework
**Context:** Choosing the Python web framework that hosts the GraphQL endpoint.
**Decision:** FastAPI.
**Alternatives considered:** Django, Flask, Starlette directly.
**Why this:** Native ASGI/async, excellent middleware story, pydantic-settings + pydantic-core integration, low overhead. Strawberry has first-class FastAPI integration via `GraphQLRouter`.
**Why not others:** Django is heavier and its sync-first ORM doesn't fit our async story; Flask lacks built-in async; Starlette is too low-level for typical needs.
**Trade-offs accepted:** Smaller built-in admin/auth story than Django — we add what we need.

## 2026-05-10 — Use GraphQL (not REST) as the API surface
**Context:** Choosing API style for the project.
**Decision:** GraphQL only — single `/graphql` endpoint.
**Alternatives considered:** REST (FastAPI's native style), gRPC, REST + GraphQL hybrid.
**Why this:** Clients fetch exactly the fields they need (no over/under-fetching); schema is the contract; introspection makes tooling and codegen trivial; mutations + subscriptions in one place.
**Why not REST:** With many related entities, REST endpoints multiply and clients end up making N+1 requests; we'd reinvent field selection via query params.
**Why not gRPC:** Web-client friction, requires extra proxy for browsers, less mature schema-first tooling than GraphQL.
**Why not hybrid:** Two API styles to maintain, two auth flows, doubled documentation surface.
**Trade-offs accepted:** Caching is harder than REST (no per-resource HTTP cache keys); rate-limiting requires query-cost analysis; ad-hoc tooling assumes REST.

## 2026-05-10 — Use Strawberry as the GraphQL library
**Context:** Choosing a Python GraphQL library.
**Decision:** strawberry-graphql with the [fastapi] extra.
**Alternatives considered:** Ariadne, Graphene, Tartiflette.
**Why this:** Code-first schema using Python dataclasses + type hints — same shape as our SQLModel/Pydantic models. Native FastAPI integration. Active maintenance. Async resolvers are first-class.
**Why not others:** Graphene has a class-heavy API and slower release cadence; Ariadne is schema-first which doubles up on type definitions; Tartiflette is sparsely maintained.
**Trade-offs accepted:** Schema is generated from Python types — to share it with non-Python clients, run a schema-export step.

## 2026-05-10 — Use PostgreSQL as the database
**Context:** Choosing the relational store.
**Decision:** PostgreSQL.
**Alternatives considered:** MySQL, SQLite, MongoDB.
**Why this:** Mature, strong consistency, rich JSONB support, excellent extension ecosystem (pgvector, PostGIS), proven at scale.
**Why not others:** MySQL has weaker JSON and constraint stories; SQLite doesn't fit multi-process production; MongoDB is non-relational and we want strong schemas + transactions.
**Trade-offs accepted:** Operational overhead vs SQLite — needs a managed service or self-host (handled by docker-compose locally).

## 2026-05-10 — Use SQLModel as the ORM
**Context:** Need an ORM that integrates with SQLAlchemy power and Pydantic types.
**Decision:** SQLModel.
**Alternatives considered:** Plain SQLAlchemy, Tortoise ORM, Peewee.
**Why this:** Built on SQLAlchemy core, so its full query power is still available. Pydantic-compatible model classes are easy to map into Strawberry types via small `from_model` helpers.
**Why not others:** Plain SQLAlchemy forces a separate Pydantic schema layer; Tortoise has a smaller ecosystem; Peewee is too minimal.
**Trade-offs accepted:** Smaller community than SQLAlchemy; some advanced SQLAlchemy patterns are awkward.

## 2026-05-10 — Use Alembic for schema migrations
**Context:** Need versioned schema changes.
**Decision:** Alembic.
**Alternatives considered:** Hand-written SQL migrations, third-party SQLModel-specific tools.
**Why this:** Industry standard for SQLAlchemy-based projects, autogenerate works with SQLModel, mature.
**Why not others:** Hand-written SQL is error-prone and lacks autogenerate.
**Trade-offs accepted:** Every model must be imported in `alembic/env.py` for autogenerate to detect it.

## 2026-05-10 — Modular schema split: `types.py` / `queries.py` / `mutations.py` per module
**Context:** Where to put GraphQL type definitions and resolvers.
**Decision:** Each `app/modules/{feature}/` directory owns its own `types.py`, `queries.py`, `mutations.py`. A central `app/graphql/schema.py` merges the per-module Query/Mutation classes via `strawberry.tools.merge_types`.
**Alternatives considered:** One giant `schema.py`; one `schema.py` per module that defines its own `strawberry.Schema`; co-locating types and resolvers in a single `graphql.py` per module.
**Why this:** Small files, clear ownership, modules can be reviewed independently. The merge happens in one place so adding a feature is a one-line edit to `schema.py`.
**Why not others:** A single big file becomes unreadable past a few features; per-module schemas can't share context easily; co-locating types and resolvers makes resolver files long.
**Trade-offs accepted:** Three files per module instead of one — but each stays small.

## 2026-05-10 — DB session passed via `info.context.session`
**Context:** How resolvers access the database.
**Decision:** `Context` (subclass of `BaseContext`) holds a per-request `Session`. Built by `get_context` which depends on `get_session`. Resolvers read it via `info.context.session` and pass it to service methods.
**Alternatives considered:** Module-level session, contextvars, querying the FastAPI dep system directly inside resolvers.
**Why this:** Same lifecycle guarantees as the FastAPI dependency system, no implicit globals, easy to override in tests via `app.dependency_overrides[get_session]`.
**Why not others:** Module-level state leaks across requests; contextvars are harder to test and reason about.
**Trade-offs accepted:** Resolvers must accept `info: Info` as their first argument.

## 2026-05-10 — Resolvers contain no business logic; services do the work
**Context:** Where domain logic lives.
**Decision:** Resolvers only call services and adapt return types. All business logic, DB access, and validation live in `service.py` as static methods on a `{Name}Service` class.
**Alternatives considered:** Logic in resolvers; class-based resolver views; a third "use case" layer.
**Why this:** Resolvers stay one-liners and easy to read; services are testable without spinning up Strawberry; the same services are reusable from CLI commands, scheduled jobs, or background workers.
**Why not others:** Logic in resolvers is hard to test; an extra layer is over-engineering for this project's size.
**Trade-offs accepted:** Two files per feature path.

## 2026-05-10 — Production Dockerfile uses multistage build with uv
**Context:** Building the production image.
**Decision:** Stage 1 (`builder`) uses `ghcr.io/astral-sh/uv:...-bookworm-slim`, creates a venv at `/opt/venv`, installs deps via `uv pip install -r requirements.txt` with a buildkit cache mount. Stage 2 (`runtime`) is `python:3.13-slim-bookworm`, copies only `/opt/venv` and the app, runs as a non-root `app` user, healthcheck via Python (no `curl` install).
**Alternatives considered:** Single-stage with pip; alpine base; distroless final stage; poetry instead of uv.
**Why this:** uv installs roughly 10× faster than pip, so cold builds are quick. Multistage keeps the runtime image free of build tools and pip caches → smaller, fewer CVEs. `slim-bookworm` is glibc-based so wheels Just Work (no musl compatibility headaches like alpine).
**Why not alpine:** `psycopg2-binary` and many wheels have known musl issues; install often falls back to compiling from source which makes the image bigger and slower to build.
**Why not distroless:** Harder to debug — no shell, no apt. We can revisit when the project is more mature.
**Why not pip:** Slower cold builds, no built-in lock-file resolver of the same quality as uv's.
**Trade-offs accepted:** Pinned uv major version means occasional bumps when uv ships breaking changes.

## 2026-05-11 — Drop host port binding for Postgres in docker-compose
**Context:** Only the `app` service ever connects to Postgres, and it does so over the docker bridge network (`postgres:5432`). Exposing 5432 on the host caused conflicts with any local Postgres the developer was running and provided no benefit beyond ad-hoc `psql`.
**Decision:** Removed `ports: ["${DB_PORT}:5432"]` from the `postgres` service.
**Alternatives considered:** Keep the binding, change to `5433:5432`, expose only on a private interface.
**Why this:** Defaults to "works on every machine" — no port collisions with host Postgres. The container is still reachable via `docker compose exec postgres psql ...` when needed.
**Why not others:** A non-standard host port (5433) is one more thing to remember; private interface bindings vary by OS.
**Trade-offs accepted:** Connecting from a GUI tool on the host now requires `docker compose port postgres 5432` or a temporary `--publish` override.

## 2026-05-11 — JWT auth with Argon2id password hashing
**Context:** Phase 1 needs email/password authentication and stateless tokens.
**Decision:** Argon2id (via `argon2-cffi`) for password hashing; HS256 JWTs (via `PyJWT`) for access tokens. JWT carries only `sub` (user id), `iat`, `exp`. Token lifetime configurable via `ACCESS_TOKEN_EXPIRE_MINUTES` (default 60). No refresh tokens in Phase 1 (explicitly out of scope).
**Alternatives considered:** bcrypt + PyJWT; passlib (deprecating); python-jose; opaque server-side session tokens.
**Why this:** Argon2id is the OWASP-recommended password hash (memory-hard, resistant to GPU attacks); `argon2-cffi` is the canonical Python binding. PyJWT is the smallest, best-maintained JWT library — no dependency on the abandoned `python-jose`. Stateless JWTs avoid a session store while we're still single-tenant.
**Why not bcrypt:** Slower to tune for modern hardware; vulnerable to GPU-accelerated cracking compared to Argon2id.
**Why not python-jose:** Has not had a meaningful release in years; PyJWT is actively maintained and has a tighter API.
**Why not server-side sessions:** Would require a session store (Redis or DB) before we need it; revocation is not a Phase 1 requirement.
**Trade-offs accepted:** Token revocation requires either a denylist or short token TTLs — fine for Phase 1 since refresh tokens / logout-everywhere are explicitly out of scope.

## 2026-05-11 — UUID primary keys for all Phase 1 entities
**Context:** Choosing a primary key strategy for `users`, `posts`, `comments`.
**Decision:** All PKs are `uuid.UUID` columns (PostgreSQL native `uuid` type), generated client-side via `uuid.uuid4`.
**Alternatives considered:** Auto-increment `bigint`, ULID, UUIDv7.
**Why this:** Globally unique (safe to merge/replicate later), opaque to clients (no enumeration of how many posts exist), client-generatable (no round-trip to DB before inserts). Postgres has a native `uuid` type — no varchar abuse.
**Why not bigint:** Leaks counts; complicates future multi-region or sharded deployments.
**Why not ULID / UUIDv7:** Better sort order, but no stdlib support yet; not worth a dependency at this stage.
**Trade-offs accepted:** UUIDs are 16 bytes vs 8 for bigint, and random UUIDs hurt B-tree locality. Acceptable at Phase 1 traffic; revisit if write throughput becomes a constraint.

## 2026-05-10 — docker-compose runs the production image with dev-friendly overrides
**Context:** How local development happens.
**Decision:** A single `docker-compose.yml` builds and runs the production Dockerfile, then overrides the `command:` to `uvicorn ... --reload` and volume-mounts `./app` and `./alembic` for hot reload. Postgres runs as a sibling service with a healthcheck and `depends_on: condition: service_healthy`.
**Alternatives considered:** Separate `Dockerfile.dev`; two compose files (`compose.yml` + `compose.override.yml`); no compose at all.
**Why this:** One image, one compose file — the user runs `docker compose up --build` and has a working app + DB. Mixes dev and prod surface slightly, but the prod image is unmodified — only the runtime command and source mounts change.
**Why not separate Dockerfile.dev:** Two images to maintain; harder to ensure dev parity with prod.
**Why not split compose files:** Extra cognitive load for a small project; the override pattern shines once compose grows beyond 3-4 services.
**Trade-offs accepted:** The dev compose runs `uvicorn --reload`, which is single-process — good enough for local development; production uses gunicorn workers via the Dockerfile CMD.
