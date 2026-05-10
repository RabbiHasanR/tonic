# Add Resolver — Add a Single Query or Mutation to an Existing Module

Usage: /add-resolver <module> <query|mutation> <name> <description>

Example: /add-resolver tasks query exportTasks Export all tasks as CSV
Example: /add-resolver tasks mutation archiveTask Archive a single task by id

Follow the Query / Mutation / Service patterns in `.claude/CLAUDE.md` exactly.

## Steps

1. Read `app/modules/{module}/queries.py`, `mutations.py`, `service.py`, `types.py`.

2. Add the resolver:
   - For `query`: add a `@strawberry.field` method to `{Name}sQuery` in `queries.py`
   - For `mutation`: add a `@strawberry.mutation` method to `{Name}sMutation` in `mutations.py`
   - First parameter is `self`, second is `info: Info`. Pull the session from `info.context.session` and pass it to the service method.

3. Add the corresponding service method in `service.py`.

4. Add new Strawberry types or inputs to `types.py` if the resolver needs them.

5. Confirm the resolver is wired end-to-end and try it in GraphiQL at `/graphql`.
