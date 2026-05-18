# Tonic API

A **GraphQL API** built with FastAPI and Strawberry. It shows how to build a
real backend with good performance, strong security, and a clean structure —
not just a basic CRUD app.

What's inside: full CRUD, DataLoader to fix N+1, Redis caching, persisted
queries (APQ), cursor pagination, query depth/complexity limits, rate
limiting with a leaky bucket, and JWT auth.

![Python](https://img.shields.io/badge/python-3.13-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688)
![Strawberry](https://img.shields.io/badge/GraphQL-Strawberry-ff6b9d)
![Postgres](https://img.shields.io/badge/PostgreSQL-16-336791)
![Redis](https://img.shields.io/badge/Redis-7-DC382D)
![Docker](https://img.shields.io/badge/Docker-multistage-2496ED)

---

## Features

### Core

- Full CRUD across 3 modules: `users`, `posts`, `comments`
- Each module has its own `types`, `queries`, `mutations`, `service`, `models`
- Resolvers stay thin — all logic lives in the service layer
- GraphiQL playground at `/graphql`

### Performance

- **DataLoader** — batches nested field loads so you don't hit N+1 queries
  → [app/graphql/loaders.py](app/graphql/loaders.py)
- **Redis cache** — single-entity reads (`post:{id}`, `user:{id}`,
  `comment:{id}`) check Redis first, fall back to Postgres on miss
  → [app/core/cache.py](app/core/cache.py)
- **APQ (Automatic Persisted Queries)** — client sends a short hash instead
  of the full query, and safe reads get `Cache-Control` headers for CDN
  caching → [app/graphql/apq/](app/graphql/apq/)
- **Cursor pagination** — opaque cursors, stable order, no slow offset
  scans → [app/graphql/pagination.py](app/graphql/pagination.py)

### Security

- **Depth, alias, and token limits** — block bad queries before they run
  → [app/graphql/rate_limit_ext.py](app/graphql/rate_limit_ext.py)
- **Complexity scoring** — each query gets a cost based on its shape and
  page size → [app/graphql/complexity.py](app/graphql/complexity.py)
- **Leaky-bucket rate limit** — cost is charged to a Redis token bucket
  per user (or per IP for guests), using an atomic Lua script
  → [app/graphql/rate_limit.py](app/graphql/rate_limit.py)
- **JWT auth** (HS256) + **Argon2id** password hashing
  → [app/core/auth.py](app/core/auth.py), [app/core/security.py](app/core/security.py)
- Author-only checks on update/delete, sit inside services
- Input validation (email format, foreign-key existence checks)
- Max body size check before parsing; TrustedHost + CORS configured

### Operations

- Multistage Docker build (small final image, non-root user)
- `docker-compose` runs Postgres + Redis + app together
- Health check at `/health`
- Stateless app — easy to scale; all shared state in Postgres/Redis
- Cache failures don't crash the API — they just fall back to the DB

---

## Architecture

One endpoint: `/graphql`. Each module adds its own `Query` and `Mutation`
classes and they get merged in [app/graphql/schema.py](app/graphql/schema.py).
Every request gets a fresh DB session on `info.context`.

```text
Client → Middleware (BodySize → CORS → GZip → APQ)
       → GraphQL Router → Schema
       → Extensions (Depth/Alias/Token limits → Complexity rate limit)
       → Resolver → Service → SQLModel → Postgres
                              └→ Redis (cache + APQ + rate buckets)
```

Full version: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Data Model

Three tables, all UUID primary keys.

| Table | What it holds |
| --- | --- |
| `users` | email (unique), password hash, display name, timestamps |
| `posts` | author FK, title, markdown body, indexed `created_at` |
| `comments` | post FK (cascade delete), author FK, body, indexed `created_at` |

```text
users  1 ── N  posts  1 ── N  comments
  │                              ▲
  └────────── author ────────────┘
```

Migrations live in [alembic/versions/](alembic/versions/).

---

## Tech Stack

| Layer | Tech |
| --- | --- |
| Web | FastAPI |
| GraphQL | strawberry-graphql |
| Database | PostgreSQL 16 |
| Cache / APQ / rate limit | Redis 7 |
| ORM / Migration | SQLModel + Alembic |
| Auth | PyJWT + argon2-cffi |
| Container | Multistage Docker + docker-compose |

See [DECISIONS.md](DECISIONS.md) for *why* each piece was chosen.

---

## Quickstart (Docker — primary path)

```bash
cp .env.example .env                    # adjust DB credentials if needed
docker compose up --build
docker compose exec app alembic upgrade head   # after first model is added
```

- GraphiQL playground: <http://localhost:8000/graphql>
- Health check: <http://localhost:8000/health>

The app service mounts `./app` and `./alembic` so code edits hot-reload via uvicorn.
Postgres data persists in the named volume `postgres_data`.

## Quickstart (local Python — optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Point DB_SERVER=localhost in .env, run a local postgres
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Project Layout

```text
app/
├── core/       # config, database, auth, security, cache
├── graphql/    # schema, context, router, loaders, pagination,
│               # complexity, rate_limit, apq/
├── modules/    # users/, posts/, comments/
└── main.py     # FastAPI app: middleware, /graphql, /health
alembic/        # migrations
tests/          # pytest suite
```

---

## Testing

```bash
docker compose exec app pytest -v
```

---

## More Docs

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — how every piece connects, request flow, modules
- **[DECISIONS.md](DECISIONS.md)** — *why* each choice was made
- **[.claude/CLAUDE.md](.claude/CLAUDE.md)** — conventions for contributors
