---
name: record-decision
description: Append an entry to DECISIONS.md when a project decision is made. Trigger when the user says "we decided", "let's use X", "switching to Y", "going with Z over W", introduces a new dependency, picks a library, sets a non-obvious convention, or otherwise makes a non-trivial choice. Skip mechanical scaffolding (new module, new resolver, bug fix).
---

# Record Decision

Append a new entry to `DECISIONS.md` using the format documented at the top of that file.

## Steps

1. Read `DECISIONS.md` to confirm the format and that no existing entry already covers this decision (if one does, update or replace it instead of duplicating).

2. Gather these from the conversation, asking the user only for what's missing:
   - **Title** — short, e.g. "Add Redis as the cache layer"
   - **Context** — what triggered the decision
   - **Decision** — what was chosen
   - **Alternatives considered** — what else was on the table
   - **Why this** — why the chosen option won
   - **Why not others** — concrete reasons each alternative was rejected
   - **Trade-offs accepted** — what was knowingly given up

3. Append the entry below the most recent one, dated today (`YYYY-MM-DD`).

4. If the decision adds or changes a dependency, also remind the user to update `requirements.txt` and (if relevant) the Dockerfile.
