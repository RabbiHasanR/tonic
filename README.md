# Tonic API

GraphQL API for the Tonic platform

## Tech Stack

- FastAPI + Strawberry GraphQL (single `/graphql` endpoint)
- PostgreSQL + SQLModel (ORM) + Alembic (migrations)
- Production-grade multistage Dockerfile + docker-compose

## Quickstart (Docker — primary path)

```bash
cp .env.example .env                    # adjust DB credentials if needed
docker compose up --build
docker compose exec app alembic upgrade head   # after first model is added
```

- GraphiQL playground: http://localhost:8000/graphql
- Health check: http://localhost:8000/health

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

## Project Docs

- **`ARCHITECTURE.md`** — how the project works and how components connect. Updated whenever structure changes.
- **`DECISIONS.md`** — append-only log of *why* each non-trivial choice was made.
- **`.claude/CLAUDE.md`** — architecture conventions, patterns, and development workflow.
