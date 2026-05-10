---
name: update-architecture
description: Update ARCHITECTURE.md when the project's structure or component connections change. Trigger when adding/removing modules or services, adding external integrations (Redis, S3, queue, third-party API), changing how components communicate, or adding new layers (workers, caches, gateways).
---

# Update Architecture

Update the relevant section of `ARCHITECTURE.md` so it always reflects the current shape of the project.

## Steps

1. Read `ARCHITECTURE.md` and identify which section(s) are affected:
   - New module → `Modules` section
   - New external service (Redis, S3, third-party API) → `External Integrations`
   - New worker / cache / queue → `Background Workers / Async Jobs` or a new section
   - Folder layout change → `Folder Layout`
   - Request flow change → `Request Flow` and `Component Map`

2. Update the affected section. Keep it tight — one or two lines per module/integration; full diagrams only when the request flow itself changes.

3. If the change reflects a non-trivial decision, also invoke the `record-decision` skill.
