# Check Conventions

Review a file against the project's architecture conventions.

Usage: /check-conventions [file_path?]

Example: /check-conventions app/modules/tasks/queries.py

## Steps

1. If a file path is given, use it. Otherwise, identify the most recently modified `.py` file under `app/`.

2. Delegate to the `@convention-reviewer` agent with the target file path.
