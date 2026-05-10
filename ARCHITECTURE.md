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
│ Middleware stack    │  TrustedHost → CORS → GZip
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

1. Client POSTs a GraphQL document to `/graphql`.
2. Middleware stack runs **outer → inner**: TrustedHost → CORS → GZip.
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

_(none yet — each `add-module` invocation appends an entry here)_

---

## External Integrations

_(none yet — log here when adding Redis, S3, message queues, third-party APIs, etc.)_

---

## Background Workers / Async Jobs

_(none yet — log here when adding Celery, RQ, ARQ, or similar)_
