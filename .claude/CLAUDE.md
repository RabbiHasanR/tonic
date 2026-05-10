# CLAUDE.md — Tonic API

GraphQL API for the Tonic platform

GraphQL server: FastAPI hosts a single `/graphql` endpoint backed by Strawberry. SQLModel
ORM + Alembic for the data layer. No REST endpoints, no response wrappers, no custom
exception handlers — resolvers return Strawberry types directly and exceptions surface
as GraphQL `errors[]`.

---

## Tech Stack

| Layer | Technology |
| --- | --- |
| Framework | FastAPI |
| GraphQL | strawberry-graphql[fastapi] |
| Database | PostgreSQL |
| ORM / Migrations | SQLModel + Alembic |
| Settings | pydantic-settings |
| Container | multistage Docker + docker-compose |

---

## Critical Rules

1. **All DB access via `info.context.session`** in resolvers; pass it to the service.
2. **Use SQLModel ORM**, not raw SQL. Last resort: `session.exec(text("..."))` from `sqlalchemy`.
3. **Never use `os.environ`.** All config via `from app.core.config import settings`.
4. **Never put logic in a resolver.** Resolvers call services and map types — that's it.
5. **Resolvers raise standard exceptions** for errors; Strawberry surfaces them in `errors[]`. Use `strawberry.exceptions.GraphQLError` for client-facing messages.
6. **Each module owns three GraphQL files**: `types.py`, `queries.py`, `mutations.py`. Plus `service.py` and (if it owns tables) `models.py`.
7. **Register module Query/Mutation in `app/graphql/schema.py`** via `merge_types`. Forgetting this means the resolver never gets called.
8. **Never include `password` in any GraphQL type.** Strawberry types are publicly exposed via introspection.
9. **Use `strawberry.ID` for primary key fields** in types — not `str`. Inputs use `str` or `strawberry.ID` depending on whether the value is meaningful as an ID.
10. **Always commit explicitly** in services. After `session.add(...)`, call `session.commit()` and `session.refresh(obj)` if the resolver needs the populated row back.
11. **Append to `DECISIONS.md` whenever a non-trivial decision is made.** Triggers: adding/removing a dependency, choosing one library/tool over alternatives, introducing or changing an architectural pattern, picking an approach where a sensible alternative existed, setting a non-obvious convention. Do NOT log: mechanical scaffolding (new module / resolver / model), bug fixes, renames, cleanup. Use the `record-decision` skill or write the entry directly using the format at the top of `DECISIONS.md`.
12. **Update `ARCHITECTURE.md` whenever the project's structure or component connections change.** Triggers: adding/removing a module or service, adding an external integration, changing how components communicate, adding a new layer (worker, cache, gateway). Use the `update-architecture` skill or edit the relevant section directly.

---

## Type Pattern (`types.py`)

```python
import strawberry
from typing import Optional


@strawberry.type
class Item:
    id: strawberry.ID
    title: str
    description: Optional[str] = None

    @classmethod
    def from_model(cls, m) -> "Item":
        return cls(id=strawberry.ID(m.id), title=m.title, description=m.description)


@strawberry.input
class ItemCreateInput:
    title: str
    description: Optional[str] = None


@strawberry.input
class ItemUpdateInput:
    id: strawberry.ID
    title: Optional[str] = None
    description: Optional[str] = None
```

## Query Pattern (`queries.py`)

```python
import strawberry
from strawberry.types import Info
from .service import ItemService
from .types import Item


@strawberry.type
class ItemsQuery:
    @strawberry.field
    def items(self, info: Info) -> list[Item]:
        rows = ItemService.list_items(info.context.session)
        return [Item.from_model(r) for r in rows]

    @strawberry.field
    def item(self, info: Info, id: strawberry.ID) -> Item:
        row = ItemService.get_item(info.context.session, str(id))
        return Item.from_model(row)
```

## Mutation Pattern (`mutations.py`)

```python
import strawberry
from strawberry.types import Info
from .service import ItemService
from .types import Item, ItemCreateInput, ItemUpdateInput


@strawberry.type
class ItemsMutation:
    @strawberry.mutation
    def create_item(self, info: Info, input: ItemCreateInput) -> Item:
        row = ItemService.create_item(info.context.session, input)
        return Item.from_model(row)

    @strawberry.mutation
    def update_item(self, info: Info, input: ItemUpdateInput) -> Item:
        row = ItemService.update_item(info.context.session, str(input.id), input)
        return Item.from_model(row)

    @strawberry.mutation
    def delete_item(self, info: Info, id: strawberry.ID) -> bool:
        ItemService.delete_item(info.context.session, str(id))
        return True
```

## Service Pattern (`service.py`)

```python
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError
from .models import Item


class ItemService:
    @staticmethod
    def create_item(session: Session, payload) -> Item:
        item = Item(title=payload.title, description=payload.description)
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    @staticmethod
    def list_items(session: Session, skip: int = 0, limit: int = 50) -> list[Item]:
        return session.exec(select(Item).offset(skip).limit(limit)).all()

    @staticmethod
    def get_item(session: Session, item_id: str) -> Item:
        item = session.get(Item, item_id)
        if not item:
            raise GraphQLError("Item not found")
        return item

    @staticmethod
    def update_item(session: Session, item_id: str, payload) -> Item:
        item = ItemService.get_item(session, item_id)
        if payload.title is not None:
            item.title = payload.title
        if payload.description is not None:
            item.description = payload.description
        session.add(item)
        session.commit()
        session.refresh(item)
        return item

    @staticmethod
    def delete_item(session: Session, item_id: str) -> None:
        item = ItemService.get_item(session, item_id)
        session.delete(item)
        session.commit()
```

## Schema Wiring (`app/graphql/schema.py`)

When you add a module's query/mutation classes, merge them in:

```python
import strawberry
from strawberry.tools import merge_types
from app.modules.items.queries import ItemsQuery
from app.modules.items.mutations import ItemsMutation


@strawberry.type
class _RootQuery:
    @strawberry.field
    def ping(self) -> str: return "pong"


@strawberry.type
class _RootMutation:
    @strawberry.field
    def _placeholder(self) -> str: return "ok"


Query = merge_types("Query", (_RootQuery, ItemsQuery))
Mutation = merge_types("Mutation", (_RootMutation, ItemsMutation))

schema = strawberry.Schema(query=Query, mutation=Mutation)
```

---

## Adding a New Feature

**Skills (auto-trigger on natural language):**

- "add a `{feature}` module" / "scaffold a feature module" → `add-module` skill
- "add a `{Name}` model" / "create a SQLModel" → `add-model` skill
- "plan the `{feature}` feature" → `plan-feature` skill
- "we decided to use X" / "switching to Y" → `record-decision` skill
- "added a Redis layer" / "new module just landed" → `update-architecture` skill

**Slash commands (explicit invocation):**

- `/add-resolver {module} {query|mutation} {name} {description}` — add a single resolver
- `/check-conventions [file]` — review against this CLAUDE.md

**Manually:**

1. Create `app/modules/{feature}/types.py`, `queries.py`, `mutations.py`, `service.py`, and `models.py` (if needed)
2. Register Query and Mutation in `app/graphql/schema.py` via `merge_types`
3. If models added: import into `alembic/env.py`, then `docker compose exec app alembic revision --autogenerate -m "..."` then `alembic upgrade head`
4. Test via the GraphiQL playground at `/graphql`

---

## Commands

```bash
# Build + start the whole stack (postgres + app)
docker compose up --build

# Apply migrations
docker compose exec app alembic upgrade head

# New migration
docker compose exec app alembic revision --autogenerate -m "description"

# Tail logs
docker compose logs -f app

# Tear down (keep volume)
docker compose down

# Tear down + delete postgres volume
docker compose down -v

# Run tests inside the container
docker compose exec app pytest -v
```

## Skills (auto-triggered)

| Skill | Trigger phrases | What it does |
| --- | --- | --- |
| `add-module` | "add a tasks module" | Full module skeleton (types/queries/mutations/service) + schema merge |
| `add-model` | "add a Task model" | SQLModel class + Alembic migration |
| `plan-feature` | "plan the auth feature" | Brainstorm + blueprint via `@feature-planner` |
| `record-decision` | "we decided to use X" | Append a new entry to DECISIONS.md |
| `update-architecture` | "new Redis layer added" | Update the relevant section of ARCHITECTURE.md |

## Slash Commands

| Command | Example | What It Does |
| --- | --- | --- |
| `/add-resolver` | `/add-resolver tasks query exportTasks Export tasks as CSV` | Add a single query or mutation to an existing module |
| `/check-conventions` | `/check-conventions app/modules/tasks/queries.py` | Check file for violations |

## Agents

| Agent | Purpose |
| --- | --- |
| `@feature-planner` | Brainstorm + blueprint new features (read-only) |
| `@project-extender` | File-by-file implementation plan from PROJECT_BLUEPRINT.json |
| `@convention-reviewer` | Report convention violations with line numbers |
