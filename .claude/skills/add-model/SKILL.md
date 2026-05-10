---
name: add-model
description: Create a SQLModel table class plus its Alembic migration. Trigger when the user asks to "add a model", "create a new SQLModel", "add a {Name} table", or otherwise wants a new database table for the project.
---

# Add Model — SQLModel + Migration

Create a SQLModel table class and generate its Alembic migration.

## Steps

1. Scan `app/modules/` to list existing module directories. Use AskUserQuestion to ask:

   - **Model name** — the class name in singular form (e.g. `Task`, `UserProfile`). Pre-fill from any name in the user's message.
   - **Module** — which module this model belongs to. Show discovered modules + an "Other (new module)" option.

2. Derive:
   - `MODEL_NAME` = PascalCase of the answer (e.g. `task` → `Task`)
   - `MODULE` = chosen module directory
   - `table_name` = snake_case plural (e.g. `tasks`)

3. Ask for fields (optional):
   > Define fields now? Format: `field_name:type` per line or comma-separated.
   > Supported: `str`, `int`, `float`, `bool`, `datetime`, `Optional[str]`, etc.

   Map each to the SQLModel column form (`Optional[str] = Field(default=None)`, `bool = Field(default=False)`, etc.).

4. Create `app/modules/{MODULE}/models.py`:

```python
from typing import Optional
from uuid import uuid4
from sqlmodel import SQLModel, Field
from datetime import datetime


class {MODEL_NAME}(SQLModel, table=True):
    __tablename__ = "{table_name}"

    id: str = Field(default_factory=lambda: uuid4().hex, primary_key=True)
    {fields}
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

5. Import the model in `alembic/env.py`:

```python
from app.modules.{MODULE}.models import {MODEL_NAME}  # noqa
```

6. Generate the migration:

```bash
docker compose exec app alembic revision --autogenerate -m "add_{table_name}_table"
```

7. Read the generated migration file and confirm `upgrade()` and `downgrade()` look correct.

8. Remind the user: `docker compose exec app alembic upgrade head` to apply.

## If the Migration Is Empty

- Is the model imported in `alembic/env.py`?
- Does the model class have `table=True`?

## Rules

- SQLModel class must have `table=True`
- Never edit a migration that has already been applied to production
- `downgrade()` must undo exactly what `upgrade()` does
