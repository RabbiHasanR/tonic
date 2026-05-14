# Architecture

How Tonic API is built and how its components connect.

This document is updated every time the project's structure or component
connections change — new module, new external integration, new layer.

---

## Overview

GraphQL API for the Tonic platform

A small **GraphQL** server. Single `/graphql` endpoint backed by Strawberry, hosted by FastAPI.
Each feature module owns its own GraphQL types and resolvers; a central schema file merges
them. Resolvers contain no business logic — they call into module services.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Web framework | FastAPI |
| GraphQL library | strawberry-graphql[fastapi] |
| Database | PostgreSQL |
| Cache / APQ store | Redis |
| ORM | SQLModel |
| Migrations | Alembic |
| Settings | pydantic-settings |
| Container | multistage Docker (uv builder + python:3.13-slim-bookworm runtime) |
| Local orchestration | docker-compose |

See `DECISIONS.md` for *why* each of these was chosen.

---

## Folder Layout

```
app/
├── core/
│   ├── config.py           # Settings (loaded from .env via pydantic-settings)
│   └── database.py         # SQLAlchemy engine + get_session() dependency
├── graphql/
│   ├── schema.py           # Merges per-module Query/Mutation into the root schema
│   ├── context.py          # Per-request GraphQL context (holds Session)
│   └── router.py           # Strawberry GraphQLRouter mounted at /graphql
├── modules/                # One folder per domain feature
│   └── {feature}/
│       ├── types.py        # @strawberry.type / @strawberry.input definitions
│       ├── queries.py      # @strawberry.type Query with @strawberry.field resolvers
│       ├── mutations.py    # @strawberry.type Mutation with @strawberry.mutation resolvers
│       ├── service.py      # Business logic, DB ops via injected Session
│       └── models.py       # SQLModel table classes (if the feature owns DB tables)
├── utils/                  # Cross-cutting helpers (currently empty)
└── main.py                 # App entry: middleware, GraphQL mount, /health

alembic/
├── env.py                  # Wired to settings.DATABASE_URL + SQLModel.metadata
└── versions/               # Generated migration files

Dockerfile                  # Multistage production image
docker-compose.yml          # postgres + app (dev hot-reload)
.dockerignore               # Excludes everything not needed in the image
```

---

## Component Map

```
┌─────────────────────┐
│  Client (HTTP POST  │
│  to /graphql)       │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Middleware stack    │  TrustedHost → CORS → GZip → GraphQLAPQ
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ GraphQLRouter       │  /graphql (POST queries+mutations, GET GraphiQL in dev)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Strawberry Schema   │  Merged Query / Mutation across all modules
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐       ┌─────────────────────┐
│ Module resolver     │ ────▶ │ Module service      │
│ (queries.py /       │       │ (static methods)    │
│  mutations.py)      │       └──────────┬──────────┘
└──────────┬──────────┘                  │
           │                             ▼
           │                  ┌─────────────────────┐
           │                  │ SQLModel ORM        │
           │                  │ (info.context       │
           │                  │  .session)          │
           │                  └──────────┬──────────┘
           │                             │
           │                             ▼
           │                  ┌─────────────────────┐
           │                  │   PostgreSQL        │
           │                  └─────────────────────┘
           │
           ▼
┌─────────────────────┐
│ GraphQL response    │  Serialized by Strawberry
│ (data / errors)     │
└─────────────────────┘
```

---

## Request Flow

1. Client sends a GraphQL request to `/graphql` — POST with a JSON body for
   mutations and most queries, or GET with `query`/`variables`/`extensions`
   query params for public reads using APQ.
2. Middleware stack runs **outer → inner**: TrustedHost → CORS → GZip →
   GraphQLAPQ. The APQ layer resolves any `persistedQuery` hash via Redis
   (returning `PersistedQueryNotFound` on miss), then on the response side
   injects a `Cache-Control` header derived from the resolved query's root
   field (`public, max-age=…` for `post`/`user`/`posts` first page;
   `no-store` for everything else and any response carrying `errors`).
3. `GraphQLRouter` parses the request and runs `get_context(...)`, which depends on `get_session()` to produce a fresh `Session`.
4. Strawberry resolves the operation: each `@strawberry.field` / `@strawberry.mutation` runs its resolver with `info.context.session` available.
5. The resolver calls a service method (`{Name}Service.{action}(session, ...)`).
6. The service does DB work via SQLModel (`session.add`, `session.exec(select(...))`, `session.get`) and returns ORM objects (or raises `Exception` on error — Strawberry surfaces it as a GraphQL `errors[]` entry).
7. The resolver maps ORM objects to Strawberry types (`Item.from_model(...)`) and returns them.
8. Strawberry serializes the response; FastAPI sends it back through the middleware stack.

---

## Database

- **Engine:** Single SQLAlchemy `create_engine(...)` with `pool_pre_ping=True`.
- **Sessions:** `get_session()` yields a fresh `Session` per request.
- **Schema management:** Alembic. After model changes: `docker compose exec app alembic revision --autogenerate -m "..."` then `docker compose exec app alembic upgrade head`.
- **Model registration:** Every SQLModel class with `table=True` must be imported in `alembic/env.py`.

---

## Configuration

All config flows through `app.core.config.settings` (pydantic-settings `BaseSettings`), loaded from `.env`. **Never read `os.environ` directly.** When running via docker-compose, `DB_SERVER=postgres` (the service name); locally, `DB_SERVER=localhost`.

---

## Container Architecture

- **Builder stage:** `ghcr.io/astral-sh/uv:...-bookworm-slim` creates `/opt/venv` and runs `uv pip install -r requirements.txt`.
- **Runtime stage:** `python:3.13-slim-bookworm`, non-root `app` user, copies only `/opt/venv` and source. No build tools, no pip cache, no apt cache.
- **Healthcheck:** Python `urllib.request` against `/health` — no `curl` install needed.
- **Default CMD:** `gunicorn` with uvicorn workers (production). The compose file overrides with `uvicorn --reload` for dev.

---

## Modules

### `users` — accounts and authentication

- **Tables:** `users` (id uuid PK, email unique, password_hash, display_name, created_at, updated_at).
- **GraphQL types:** `User`, `AuthPayload`, `RegisterInput`, `LoginInput`.
- **Root queries:** `me: User`, `user(id: ID!): User!`.
- **Root mutations:** `register(input): AuthPayload!`, `login(input): AuthPayload!`.
- **Service:** `UserService` (register / authenticate / get_user).
- **Nested fields:** `User.posts` resolves via `PostService.list_by_author`.

### `posts` — blog posts

- **Tables:** `posts` (id uuid PK, author_id FK → users, title, body markdown, created_at indexed for newest-first, updated_at).
- **GraphQL types:** `Post`, `PostCreateInput`, `PostUpdateInput`.
- **Root queries:** `posts(limit: Int = 20): [Post!]!`, `post(id: ID!): Post!`.
- **Root mutations:** `createPost(input): Post!`, `updatePost(input): Post!`, `deletePost(id: ID!): Boolean!` (author-only for update/delete).
- **Service:** `PostService` (list / list_by_author / get / create / update / delete).
- **Nested fields:** `Post.author` → `User`, `Post.comments` → `[Comment]`.

### `comments` — discussion threads under posts

- **Tables:** `comments` (id uuid PK, post_id FK → posts ON DELETE CASCADE, author_id FK → users, body, created_at indexed, updated_at).
- **GraphQL types:** `Comment`, `CommentCreateInput`.
- **Root queries:** none — comments are read via `Post.comments`.
- **Root mutations:** `createComment(input): Comment!`, `deleteComment(id: ID!): Boolean!` (author-only delete).
- **Service:** `CommentService` (list_by_post / get / create / delete).
- **Nested fields:** `Comment.author` → `User`.

---

## Authentication

- Email + password, Argon2id hashing (`app/core/security.py` via `argon2-cffi`).
- Stateless **HS256 JWTs** (PyJWT). Payload: `sub` = user id, `iat`, `exp`. Lifetime via `ACCESS_TOKEN_EXPIRE_MINUTES`.
- `app/graphql/context.py` reads `Authorization: Bearer <token>`, validates it, loads the user, and exposes it as `info.context.user` (Optional).
- Resolvers that require auth call `app.core.auth.require_user(info)`, which raises a `GraphQLError("Authentication required")` if no user is loaded.
- Author-only checks live in the service layer (`PostService.update_post`, `delete_post`, `CommentService.delete_comment`).

---

## External Integrations

### Redis — APQ hash store

- **Service:** `redis:7-alpine` in `docker-compose.yml`, AOF persistence on a
  named `redis_data` volume, healthchecked via `redis-cli ping`.
- **Connection:** `app.graphql.apq.store.APQStore` uses `redis.asyncio` and
  reads `settings.REDIS_URL` (default `redis://redis:6379/0`).
- **Sole current use:** Maps `sha256(query) → query string` for Automatic
  Persisted Queries. Keys prefixed `apq:`, TTL 30 days.
- **Why it's here:** Multiple uvicorn workers share one store; survives app
  container restarts. See `DECISIONS.md` (2026-05-14 entries) for the full
  rationale.

_(no other external integrations yet — log here when adding S3, message
queues, third-party APIs, etc.)_

---

## Background Workers / Async Jobs

_(none yet — log here when adding Celery, RQ, ARQ, or similar)_
