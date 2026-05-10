---
name: add-module
description: Scaffold a complete GraphQL feature module — types.py, queries.py, mutations.py, service.py — and register its Query/Mutation in app/graphql/schema.py. Trigger when the user asks to "add a module", "scaffold a feature module", "create a new module called X", or similar phrasing for spinning up a fresh feature.
---

# Add Module — GraphQL Feature Module

Create a complete feature module from scratch following the patterns in `.claude/CLAUDE.md`.

## Steps

1. If the user did not provide a module name, ask for one with AskUserQuestion.

2. Create:
   - `app/modules/{name}/__init__.py` — empty
   - `app/modules/{name}/types.py` — `{Name}` (output type, with `from_model`), `{Name}CreateInput`, `{Name}UpdateInput`
   - `app/modules/{name}/queries.py` — `{Name}sQuery` with `{name}s` (list) and `{name}` (by id) fields
   - `app/modules/{name}/mutations.py` — `{Name}sMutation` with `create_{name}`, `update_{name}`, `delete_{name}`
   - `app/modules/{name}/service.py` — `{Name}Service` with one static method per resolver

3. Edit `app/graphql/schema.py`:
   - Import the module's Query and Mutation classes
   - Add them to the `merge_types(...)` tuples for `Query` and `Mutation`

4. Confirm all files exist and the schema includes the new module.

5. Append a line to the **Modules** section of `ARCHITECTURE.md` describing the new module's purpose.

6. Remind the user:
   - New DB tables: ask the assistant to "add a `{Name}` model" (triggers `add-model` skill), then `docker compose exec app alembic upgrade head`
   - Exercise the resolvers in the GraphiQL playground at `/graphql`
