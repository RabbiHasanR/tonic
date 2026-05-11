# Tonic — Phase 1 Plan

> **Goal:** A working single-tenant blog with users, posts, comments — running over GraphQL.
> **Definition of done:** A fresh `docker compose up` brings up a server you can sign up on, log into, and post on.

---

## Entities

- **User** — `id (uuid)`, `email`, `password_hash`, `display_name`, `created_at`, `updated_at`
- **Post** — `id`, `author_id`, `title`, `body (markdown)`, `created_at`, `updated_at`
- **Comment** — `id`, `post_id`, `author_id`, `body`, `created_at`, `updated_at`

---

## Queries

- `me` — current authenticated user
- `posts(limit: Int = 20)` — newest posts first
- `post(id: ID!)` — single post with author and comments
- `user(id: ID!)` — user profile with their posts

---

## Mutations

- `register(email, password, displayName)` → user + token
- `login(email, password)` → token
- `createPost(title, body)` → post
- `updatePost(id, title, body)` → post (author only)
- `deletePost(id)` → boolean (author only)
- `createComment(postId, body)` → comment
- `deleteComment(id)` → boolean (author only)

---

## Authentication

- Email + password registration
- Argon2 password hashing
- JWT access token in `Authorization: Bearer <token>` header
- FastAPI dependency validates JWT, loads user, injects into Strawberry context
- Resolvers read `info.context.user` for auth checks

---

## Explicitly out of scope for Phase 1

Do not build these in Phase 1, even if asked. They belong to later phases.

- Workspaces, memberships, or any form of multi-tenancy
- DataLoader (let N+1 appear naturally — it motivates Phase 2)
- Cursor-based / Relay-style pagination (only simple `limit` argument)
- Roles or permissions beyond "is the author?"
- Subscriptions (WebSockets)
- File uploads
- Search (full-text or otherwise)
- Email verification, password reset, OAuth, magic links
- Refresh tokens
- Rate limiting
- Query depth or complexity limits
- Audit logs
- OpenTelemetry, Prometheus, Grafana
- Soft delete
- Notifications, mentions, likes, follows, tags
- Frontend / UI

---

## Notes for AI assistants

- **Stay in scope.** If asked to add a feature not in this document, ask whether it belongs in Phase 2+ and update `ROADMAP.md` accordingly rather than adding it now.
- **Prefer composition over abstraction.** Phase 1 has 3 entities. Do not build generic CRUD factories or abstract base resolvers. Concrete code is easier to evolve.
- **Commit often with clear messages.** One feature per commit where possible.
- **Update `DECISIONS.md`** when you make a non-obvious choice that isn't already specified in this document.
- **Do not change the locked tech stack** without explicit user approval.