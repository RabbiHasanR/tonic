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

## 2026-05-17 — Rate limiting via Redis-backed token bucket with query-complexity cost

**Context:** Query-shape limits (2026-05-16 entry below) reject malicious *individual* requests but say nothing about *throughput*. A client sending many small, valid queries (within depth/alias/page caps) can still overwhelm Postgres. Counting requests per minute is a poor proxy for actual load: a `{ ping }` and a `posts(first: 50) { comments(first: 50) { author { posts(first: 50) { ... } } } }` are both "one request" but cost wildly different things.
**Decision:** Per-client **token bucket** in Redis, where each request consumes `cost` tokens equal to its statically computed **query complexity score**.
- **Bucket params:** capacity `RATE_LIMIT_CAPACITY=1000`, refill `RATE_LIMIT_REFILL_PER_SECOND=50`. Allows bursts up to 1000 cost-units, sustained ~50/sec.
- **Hard cap:** `MAX_QUERY_COMPLEXITY=1000` rejects any *single* query exceeding the bucket capacity, regardless of bucket state (first request from a fresh client still can't run a 10k-cost query).
- **Cost model:** AST walk with graphql-core `TypeInfo`. List fields multiply child cost by `first`/`last`/`limit`/`pageSize` arg value (or `settings.MAX_PAGE_SIZE` if absent). Scalars cost 1. Mutation fields are flat `MUTATION_FLAT_COST=10`.
- **Client key:** `rl:u:{user_id}` for authed users, `rl:ip:{client_host}` for anonymous. Same bucket params for both for now.
- **Atomicity:** Lua script in Redis — `EVALSHA` runs read-refill-check-write as one atomic op. Falls back to `EVAL` on `NoScriptError` (Redis restart).
- **Fail-open:** any `RedisError` returns `(allowed=True)`. Availability beats strictness during a Redis outage — same policy as the entity cache.
- **Enforcement point:** Strawberry `RateLimitExtension` in `on_validate`, after parse + validate. Lets cheap structural rejections (depth/alias/token) happen first; complexity walk only runs on valid documents.

**Alternatives considered:**
- **Fixed window** — count requests per N-sec window in Redis.
- **Sliding window log** — sorted-set of timestamps per client.
- **Sliding window counter** — two adjacent windows, weighted average.
- **Leaky bucket as queue** — queue + fixed drain rate.
- **Request-count limiting (no complexity scoring)** — `INCR` per request, ignore query shape.
- **`WATCH`/`MULTI`/`EXEC` for atomicity** instead of Lua.
- **Per-process Python `threading.Lock`** instead of Redis.

**Why this:**
- Token bucket maps naturally onto variable per-request cost (consume `N` tokens, not just `+1`) and tolerates legitimate bursts (page-load fan-out) while enforcing a sustained-rate ceiling.
- Complexity scoring is the only way to make rate limiting meaningful for GraphQL — request count alone treats `{ ping }` and a fan-out bomb as equal.
- Lua is the standard atomic primitive in Redis and runs server-side in one round trip, no retry loop.
- `TypeInfo`-based AST walk gives accurate "is this a list" detection without hardcoding field names.
- Fail-open matches the existing cache contract and keeps the API up when Redis is down.

**Why not others:**
- **Fixed window** has a boundary-burst exploit (full budget at `:59`, again at `:00` → 2× the intended cap in 1 sec).
- **Sliding window log** is memory-heavy (one entry per request) and not worth the accuracy gain.
- **Sliding window counter** doesn't model burst credit and is awkward to combine with variable cost.
- **Leaky bucket as queue** queues requests instead of rejecting — we want immediate accept/reject for an HTTP API.
- **Request-count limiting** ignores actual load; one expensive query can DoS the DB while staying "under the limit."
- **`WATCH`/`MULTI`/`EXEC`** retries under contention and burns round trips; uglier and slower than Lua for the same correctness guarantee.
- **In-process lock** doesn't span uvicorn workers or containers — the limit would become per-worker, not per-client.

**Trade-offs accepted:**
- **Static cost estimate is approximate.** It assumes worst-case fan-out (`MAX_PAGE_SIZE` when no limit arg is provided) and doesn't know about resolver cost beyond list multiplication. We overestimate cheap queries slightly; better than underestimating expensive ones.
- **One bucket scheme for authed + anonymous.** A logged-in user gets the same allowance as a random IP. Per-role buckets (e.g. higher capacity for authed) deferred to a later phase.
- **No `X-Forwarded-For` parsing yet.** Behind a reverse proxy everyone shares the proxy's IP → single shared bucket → false positives. Project doesn't currently sit behind a proxy; add `TRUST_PROXY` toggle when it does.
- **Bucket state lives only in Redis.** If Redis flushes, all clients start with a full bucket — short-lived gap, considered acceptable.
- **Cost computed but not exposed.** No `X-RateLimit-Remaining` headers yet. Could be added later via response middleware reading bucket state.

---

## 2026-05-16 — Query-shape limits (depth, aliases, tokens, page size, body size)

**Context:** GraphQL exposes cyclic types (`Post.author → User.posts → [Post].comments → [Comment].author → …`) and id-keyed root fields (`post(id)`, `user(id)`) on a public endpoint. Without shape limits a single HTTP request can fan out into thousands of DB lookups via deep nesting, alias bombing, or oversized documents — classic GraphQL DoS vectors. Batch requests are not enabled (Strawberry's default), so that vector is already closed.
**Decision:** Layered defense-in-depth, each cheaper than the next, all driven by `settings`:

1. **HTTP body cap** — `MaxBodySizeMiddleware` rejects POSTs with `Content-Length > MAX_REQUEST_BYTES` (default 100 KB) with `413`.
2. **Token cap** — `MaxTokensLimiter(MAX_QUERY_TOKENS=1500)` Strawberry extension, kills oversized documents at lex.
3. **Depth cap** — `QueryDepthLimiter(MAX_QUERY_DEPTH=10)` extension, kills deep recursion through cyclic types.
4. **Alias cap** — `MaxAliasesLimiter(MAX_QUERY_ALIASES=15)` extension, kills alias-bomb id lookups.
5. **Page-size cap** — `MAX_PAGE_SIZE=50` enforced in `paginate()` and `offset_paginate()`; raises `GraphQLError` on `first`/`last`/`pageSize` over the cap.
6. **Introspection disabled in production** — `AddValidationRules([NoSchemaIntrospectionCustomRule])` is appended only when `settings.ENVIRONMENT == "production"`. GraphiQL still works in dev/local.

**Alternatives considered:** Per-field cost/complexity scoring (e.g. graphql-cost-analysis), no limits + rely on rate limiting only, hard-coded constants, disabling introspection unconditionally.
**Why this:** Each layer fails fast at the earliest possible stage (HTTP > lex > validate > execute), so bad requests cost the server almost nothing. Strawberry's built-in extensions are zero-maintenance vs hand-rolled cost scoring. Settings-driven means thresholds can be tuned in production without code changes.
**Why not query complexity / cost analysis:** Requires per-field cost annotations and ongoing maintenance as the schema grows. Depth + aliases + pagination cap covers ~95% of realistic abuse with no per-field bookkeeping. Keep cost analysis as a future option if a specific field proves expensive.
**Why not "rate limiting is enough":** A single in-budget request can still DoS the server if shape is unbounded. Shape limits and rate limits are complementary, not substitutes.
**Why not hard-coded constants:** Production may need to relax depth for a specific client; env-driven settings let ops tune without redeploy.
**Why introspection only in production:** Dev needs GraphiQL; production gains marginal security from blocking schema fingerprinting before crafted attacks.
**Why 100 KB body cap, not 5 MB:** A realistic GraphQL query document is rarely >20 KB. 100 KB is a comfortable ceiling that still kills 5 MB junk before it reaches the parser.
**Trade-offs accepted:** Error messages leak the limit value (e.g. `"page size too large, max 50"`) — knowing the limit doesn't help an attacker meaningfully and helps legit clients debug. No tests or metrics in this pass — limits are simple and exercised on every request. Rate limiting (per-IP / per-user) is a separate concern, not addressed here.

---

## 2026-05-16 — Cache-aside on single-entity reads (Phase 1)

**Context:** Resolver layer for `users`, `posts`, `comments` re-reads the same hot entities (a popular post, the author of every post in a feed) on every request. APQ caches query *documents* and DataLoaders batch within a request, but there is no cross-request data cache yet.
**Decision:** Adopt **cache-aside** (lazy loading) at the **service layer** for single-entity reads only. Touched methods: `PostService.get_post`, `UserService.get_user`, `CommentService.get_comment`. Storage: existing Redis (`settings.REDIS_URL`) using the sync `redis` client via a new `app/core/cache.py`. Values are JSON-encoded dicts with explicit per-module serializers. Keys: `post:{id}` / `user:{id}` / `comment:{id}`. TTLs: 300s for posts and comments, 600s for users. Invalidation: `create_*` populates the key, `update_*` and `delete_*` `cache_delete` it. Cache misses and Redis errors fail open (fall through to Postgres). Update/delete mutations re-read from DB (not via the cached `get_*`) so the SQLAlchemy `Session` always works with attached instances.
**Alternatives considered:** Read-through (cache library owns DB access), write-through (mutations write to cache + DB synchronously), write-behind (queue writes), resolver-layer caching, no caching at all.
**Why this:** Cache-aside is the safest default for a read-heavy GraphQL API. Resilient — Redis down still serves traffic. Maps naturally to GraphQL's per-field resolution. Service-layer placement means every code path that fetches an entity (root resolver, nested `Post.author`, mutation re-fetch) shares the same cache without changing DataLoader code. Explicit `cache_get/cache_set/cache_delete` calls keep invalidation visible at the mutation site rather than hidden inside a decorator.
**Why not read-through:** Would require a library that owns DB access; doesn't fit our SQLModel + static-method service pattern cleanly.
**Why not write-through:** Adds latency to every mutation for marginal benefit on a read-skewed workload, and most resolvers re-read the row right after mutating anyway.
**Why not write-behind:** Async write queues risk data loss on crash and add operational complexity disproportionate to the gain at this stage.
**Why not resolver-layer:** Would duplicate cache logic across queries that hit the same service method, and double-cache when a nested field and a root field resolve the same entity in one request.
**Why sync `redis` (not `redis.asyncio` like APQ):** Services are sync (SQLModel `Session` is sync). Making services async to use `redis.asyncio` would be a larger refactor with no real benefit — cache calls are sub-millisecond local network ops. APQ keeps the async client because it lives inside an ASGI middleware where async is natural.
**Why JSON, not pickle:** Inspectable via `redis-cli GET`, safe against deserialization bugs, language-agnostic if we ever read this from another service.
**Why explicit serializers, not `SQLModel.model_dump()`:** Reconstituted detached models with `model_validate` can subtly affect lazy attrs; an explicit shape is predictable and surfaces shape drift loudly when columns change.
**Why `update_*` deletes rather than re-populates:** A delete forces the next read to repopulate from authoritative DB state, avoiding cache drift if a column is added but the serializer isn't updated.
**Trade-offs accepted:** Phase 1 covers only single-entity reads — list queries (`posts(...)`, `users(...)`, `Post.comments`), negative caching, stampede protection, and stale-while-revalidate are deferred to Phase 2/3. No tests or metrics yet — log-level visibility only (`logger.warning` on Redis errors). Cached entities are detached SQLModel instances; mutation paths intentionally bypass the cache and re-read from DB to keep `session.add`/`session.delete` safe.

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

## 2026-05-13 — Relay cursor pagination for list resolvers (starting with `posts`)

**Context:** The `posts` resolver previously returned `[Post!]!` with a `limit` argument. We needed pagination that stays correct under concurrent inserts and scales to large datasets.
**Decision:** Adopt the Relay Connections spec — `posts(first, after)` returns `PostConnection { edges { cursor, node }, pageInfo, totalCount }`. Cursor is opaque base64 of `{created_at, id}` and the query uses tuple comparison `(created_at, id) < (cursor.created_at, cursor.id)` with sort `created_at DESC, id DESC`. Forward-only for now (`first`/`after`); no `last`/`before`. Hand-rolled per-module connection types in `posts/types.py` rather than a shared generic.
**Alternatives considered:** Offset pagination (`limit`/`offset`), page-based (`page`/`perPage`), forward+backward bi-directional Relay, shared generic `Connection[T]` via Strawberry generics.
**Why this:** Stable under inserts (no skipped/duplicated rows), constant-time at any depth via the `created_at` index, and matches what Apollo/Relay/urql clients already expect. The tuple cursor handles non-unique `created_at` via the `id` tie-breaker without needing a unique sort column.
**Why not offset/page:** `OFFSET N` reads and discards N rows on every request — catastrophic at depth — and a concurrent insert shifts every subsequent page by one row, causing duplicate/skipped items.
**Why not bi-directional:** Doubles the resolver surface (`last`/`before`, reverse query) for a use case we don't have yet (no chat-style scroll-back UI). Easy to add later.
**Why not shared generic Connection type:** Only one module needs it today. Premature abstraction; extract once a second module (comments/users) needs the same shape.
**Trade-offs accepted:** `totalCount` adds an extra `COUNT(*)` per request — acceptable at current scale, can be dropped or cached later. No composite `(created_at DESC, id DESC)` index yet; the existing single-column `created_at` index plus PK is adequate until row count grows substantially.

## 2026-05-13 — Extend `posts` connection to bi-directional pagination

**Context:** The `posts` connection was forward-only (`first`/`after`). `PageInfo.hasPreviousPage` was already in the schema (Relay shape), but clients had no way to walk backward, so the field was only ever a hint that `after` had been used.
**Decision:** Add `last`/`before` to the `posts` resolver. Backward queries flip the sort to ASC (`created_at ASC, id ASC`), use `(created_at, id) > cursor` to walk older→newer from `before`, fetch `last + 1` to derive `hasPreviousPage`, then reverse the slice so the response is still in `created_at DESC` order. Validate that `first`/`last` are mutually exclusive, and that `after` only combines with `first` and `before` only with `last`. Following Relay's convention: when paginating backward, `hasNextPage = before is not None`; when paginating forward, `hasPreviousPage = after is not None` — the spec only requires these be exact in the direction you're paginating.
**Alternatives considered:** Keep forward-only and treat `hasPreviousPage` as decorative; emulate backward by inverting the cursor on the client.
**Why this:** Reverses an explicit "forward-only for now" choice in the previous entry — the user asked for it, and the per-row cursors we already emit make backward pagination essentially free server-side. Symmetric API matches what Apollo/Relay/urql clients expect.
**Why not client-side emulation:** Pushes spec complexity onto every consumer and prevents the server from giving a correct `hasPreviousPage` count.
**Trade-offs accepted:** Resolver/service surface doubles (two branches, four args, four validation checks). The `hasNextPage`/`hasPreviousPage` in the *non-paginated* direction is a hint, not a count — consistent with the Relay spec but worth documenting if a client relies on it.

## 2026-05-14 — Automatic Persisted Queries (APQ) over GET for public reads

**Context:** The three truly public queries (`post(id)`, `posts(...)`, `user(id)`) are good HTTP-cache targets — same response for every caller — but real GraphQL queries blow past the ~2 KB GET URL limit, so we couldn't use GET. Authenticated queries (`me`, `users`) stay on POST regardless; they have no CDN-cacheable shape.
**Decision:** Adopt the Apollo APQ protocol. Clients send `extensions.persistedQuery.sha256Hash` instead of the full query; on first miss they retry with the query body and the server stores it. Implemented as an ASGI middleware (`app/graphql/apq/middleware.py`) — not a Strawberry `SchemaExtension` — because Strawberry's HTTP view rejects bodies without a `query` field before any extension runs. The same middleware also injects `Cache-Control` headers based on the resolved query's root field: `post`/`user` get `public, max-age=60, s-maxage=600`, `posts` first page gets `public, max-age=30, s-maxage=60`, everything else (including any response with `errors`) gets `no-store`.
**Alternatives considered:** Strawberry SchemaExtension (rejected — wrong layer), subclassing `strawberry.fastapi.GraphQLRouter` (more invasive than middleware), no APQ + use POST-only with Redis response cache.
**Why this:** Middleware sits in front of Strawberry unchanged, no schema-layer surgery; one place owns both APQ and cache-header policy, so the resolved query is reused. Apollo/urql clients support the protocol out of the box, so client-side cost is a config flag. Mutations and authenticated queries are unaffected.
**Why not Strawberry extension:** The HTTP view raises `MissingQueryError` before any `SchemaExtension` hook fires. There's no clean way to backfill the query from inside the schema executor.
**Why not custom router:** Subclassing `GraphQLRouter` requires reimplementing request parsing; the middleware approach is smaller and decoupled.
**Trade-offs accepted:** Response body is buffered once in the wrapped `send` so we can downgrade to `no-store` when `errors` is present — fine for typical GraphQL response sizes, would need re-evaluation if we ever stream responses. Root-field detection is a regex (`_ROOT_FIELD_RE`) rather than a real GraphQL parser; fine for our actual queries, but a query with `{ # weird comment\n post ... }` would slip past — acceptable today.

## 2026-05-14 — Redis as the APQ hash store

**Context:** APQ needs a `hash → query` map shared across all uvicorn workers and surviving restarts. The map is pure cache state, not application data.
**Decision:** Run Redis (`redis:7-alpine`) as a sibling service in docker-compose with AOF persistence. App connects via `settings.REDIS_URL` (default `redis://redis:6379/0`). Keys prefixed `apq:`, TTL 30 days. Use `redis.asyncio` so the async resolvers don't block.
**Alternatives considered:** In-memory Python dict, a `persisted_queries` Postgres table.
**Why this:** With multiple workers (current dev uses one `uvicorn --reload`; prod uses gunicorn workers), an in-memory dict would force each worker to relearn each query independently. Redis gives one shared map with TTL eviction and survives `docker compose restart app`. Keeps cache state physically separate from Postgres so application transactions never collide with cache writes.
**Why not in-memory:** Per-worker duplication of the first-request cost; lost on restart.
**Why not Postgres:** Every GraphQL request would incur a DB roundtrip just to resolve a hash; mixes cache state with application schema.
**Trade-offs accepted:** New container, new dependency (`redis>=5.0`). Worth it given Redis is the standard answer for this class of problem and we'll likely reuse it for response caching, rate limiting, and session denylists later.
**Future use:** Currently only the APQ hash store. Response-level caching and rate limiting may share this Redis instance later — that's expected and fine.

## 2026-05-13 — Page (offset) pagination for top-level `users` list

**Context:** The `users` resolver previously took only `limit` (half-pagination — no way to reach page 2). We need full pagination for an admin-style user list. Posts and comments already use Relay cursor pagination.
**Decision:** Use page-based (`page`/`page_size`) pagination for top-level admin-ish lists, returning a `UserPage { items, page_info: PageMeta }` shape. `PageMeta` carries `page`, `page_size`, `total_items`, `total_pages`, `has_next`, `has_prev`. Helper `offset_paginate(...)` lives in `app/graphql/pagination.py` next to the Relay helper. Gated by `require_user(info)`. Default page_size 20, capped 1–100. Sort `created_at DESC`.
**Alternatives considered:** Relay cursor (consistent with posts/comments); keep `limit`+add `offset`.
**Why this:** Admin/listing UIs benefit from "page 3 of 47" + total count, which Relay deliberately doesn't model. The `users` table is small and bounded (one row per human), so `OFFSET` cost and insert-shift concerns are negligible — concerns that drove the Relay choice for `posts`/`comments` don't apply here.
**Why not Relay everywhere:** Forces clients to fabricate page numbers from cursors and hides `total_pages`, which is exactly what an admin list wants to show.
**Why not just `limit`+`offset`:** Misses `total_items`/`total_pages` — the whole reason for switching.
**Trade-offs accepted:** Two pagination styles in the codebase (page for top-level admin lists, Relay for nested feed-like connections). Convention: nested feed-like connections → Relay; top-level admin/listing → page. Each call pays one `COUNT(*)`.
