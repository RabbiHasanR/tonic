# GraphQL Caching — Learning & Decision Guide

Caching in GraphQL is fundamentally different from traditional REST APIs because GraphQL typically uses a single endpoint and `POST` requests, making standard URL-based caching ineffective. To optimize performance, developers use a multi-layered approach across the client and the server.

---

## 0. Quick Decision Matrix

Use this to pick the right layer for a given problem before reading the details.

| Need / Symptom | Use |
|---|---|
| Stop N+1 queries within one request | DataLoader |
| Expensive computation, rarely changes | Redis (long TTL) |
| Per-user personalized data | Redis (short TTL, user-scoped key) |
| Public, anonymous queries served globally | APQ / Persisted Queries + CDN |
| UI components stay in sync after a mutation | Client normalized cache |
| Same query repeated across many users | HTTP response cache (`Cache-Control`) |
| Data must feel fresh but expensive to compute | Stale-While-Revalidate (SWR) |

---

## 1. Client-Side Caching: The "Single Source of Truth"

Modern GraphQL clients (like Apollo or Relay) use **Normalized Caching**. Instead of saving the whole JSON result, they break it down into individual pieces, so every component sees the same value for the same entity.

### The Workflow: Normalization

1. **Fetch:** The client receives a nested JSON response.
2. **Identify:** The client looks for unique IDs, usually by combining `__typename` and `id` (e.g., `User:1`).
3. **Flatten:** The nested data is deconstructed into a flat lookup table.
4. **Reference:** Any nested objects are replaced with pointers to their unique IDs in the cache.

### Example: The "Deep Merge" Logic

If you fetch a user's **name** in Query A, and then fetch their **address** in Query B, the client merges them into one cache entry:

* **Query A:** `{ id: 1, name: "Alex" }` → stored in cache as `User:1`.
* **Query B:** `{ id: 1, address: "123 Main St" }` → when this response arrives, the client merges it into the existing `User:1` entry.
* **Result:** The cache holds `{ id: 1, name: "Alex", address: "123 Main St" }`. Any UI component reading `User:1` automatically stays in sync.

### Mutations & Cache Updates

Reading from the cache is only half the job — writes also need to update it. Common patterns:

* **Auto-merge:** If a mutation returns the updated entity (with `id` + `__typename`), the normalized cache updates automatically.
* **`refetchQueries`:** Re-run specific queries after a mutation (simple, but extra network).
* **Optimistic updates:** Write the expected result to the cache immediately, roll back if the server rejects.
* **Manual cache writes / `evict`:** For list mutations (create/delete), manually push or remove entries — the cache can't infer list membership from an entity update.

### Pitfalls

* **No stable `id`** → no normalization. Paginated lists, aggregates, and computed fields often need a custom key (`keyFields`).
* **Lists are not entities.** Adding a new item doesn't appear in a cached list automatically — you must update the list reference.

---

## 2. HTTP-Level Caching (and why GraphQL breaks it)

REST gets caching for free because each resource has a unique URL and uses `GET`. GraphQL usually sends `POST /graphql` with the query in the body — CDNs, browsers, and reverse proxies can't cache `POST`, and even if they could, every request hits the same URL.

Two ways to get HTTP caching back:

* **`Cache-Control` headers + `GET` queries** — small/safe queries can be sent as `GET` with the query in the URL. The server sets `Cache-Control: max-age=...` per response.
* **Field-level hints** — Apollo Server's `@cacheControl(maxAge: 60)` directive (or equivalent) lets each field declare its own freshness; the server computes the lowest TTL for the whole response.
* **`ETag` / `If-None-Match`** — server returns a hash; client gets `304 Not Modified` if unchanged. Saves bandwidth, not compute.

This is the foundation that makes APQ (below) useful.

---

## 3. Server-Side Caching: Protecting the Database

On the server, caching reduces load on your database (like PostgreSQL) and speeds up response times.

### Layer 1: Request-Scoped Caching (DataLoader)

Solves the **N+1 problem**, where fetching a list of items causes the server to make a new database call for every item's related data.

* **How it works:** `DataLoader` collects all requested IDs during a single request, batches them, and fetches them in one query (e.g., `SELECT * FROM users WHERE id IN (1, 2, 3...)`).
* **Scope:** This cache only lasts for the duration of one HTTP request.
* **Pitfall:** **Never reuse a DataLoader across requests** — you'll serve stale data to other users. Create a fresh instance per request (in `info.context`).

### Layer 2: Resolver-Level Caching (Redis)

For data that doesn't change often or is expensive to compute, use an external store like **Redis**.

* **Workflow:**
  1. The resolver checks Redis for a specific key (e.g., `user:1:stats`).
  2. If found (**Cache Hit**), return immediately.
  3. If not found (**Cache Miss**), perform the heavy work, save it to Redis with a **TTL**, and return.

* **Cache key design (critical):** A key must uniquely identify *who is asking* and *what they're asking for*. At minimum:

  ```text
  {operation}:{arg-hash}:{user_id_or_role}:{tenant_id}:{schema_version}
  ```

  **Forgetting the user/tenant in the key is the #1 cache bug in production — it leaks one user's data to another.**

* **Pitfalls:**
  * **Cache stampede:** When a hot key expires, hundreds of requests miss simultaneously and hammer the DB. Mitigate with locks, jittered TTLs, or SWR.
  * **Cache as infra dependency:** Redis going down should degrade, not break, your service.

### Layer 3: Edge Caching (Automatic Persisted Queries — APQ)

CDNs usually cannot cache `POST` requests. **APQ** lets you use `GET` requests instead.

* **Workflow:**
  1. The client creates a unique **hash** of the query.
  2. The client sends a `GET` request using that hash.
  3. If the server doesn't know the hash yet, the client sends the full query once to register it.
  4. The CDN sees a `GET` request and can cache the entire result at the "edge".

### APQ vs. Persisted Queries

| Aspect | APQ | Persisted Queries |
|---|---|---|
| When are queries registered | At runtime, on first miss | At build time, in an allowlist |
| Arbitrary queries allowed | Yes | **No** — server rejects unknown hashes |
| Security benefit | None | Blocks query-based DoS, schema introspection abuse |
| Best for | Public APIs | Locked-down first-party clients |

### `@defer` / `@stream`

These send partial responses incrementally. Response-level caching becomes impractical for these queries — cache at the resolver/Redis layer instead.

---

## 4. Cache Invalidation: When to Clear Data

The hardest part of caching. Common strategies:

* **TTL (Time-To-Live):** Data expires after a set time. Simple, but always serves *some* stale data.
* **Stale-While-Revalidate (SWR):** Serve the stale value immediately, refresh in the background. Best of both worlds for read-heavy data.
* **Tag-Based Invalidation:** Group entries by tag (e.g., `user:1`); when a User is updated, drop everything tagged `user:1`.
* **Event-Driven:** Database triggers, outbox pattern, or webhooks tell the cache to refresh when source data changes. Most accurate, most complex.
* **Subscriptions as invalidation signals:** GraphQL subscriptions generally bypass the cache themselves — but they're a great mechanism to *tell* clients to refetch or evict.

---

## 5. Observability — What to Measure

You cannot tune what you don't measure. Track at minimum:

* **Hit rate** per cache (target: >80% for hot paths)
* **Miss rate** and **miss latency** (a miss should be slow, not catastrophic)
* **Eviction rate** (high evictions → cache too small or TTL too long)
* **Key cardinality** (exploding keys → bad key design, e.g., timestamps in keys)
* **Stampede events** (concurrent misses on the same key)

Without these, TTL choices are guesses.

---

## 6. Example: Redis-Cached Resolver in This Project

Sketch for the Tonic stack (Strawberry + FastAPI + Redis). Add a thin wrapper in the service layer:

```python
import json
from redis.asyncio import Redis
from sqlmodel import Session

redis: Redis  # from app.core.cache

class UserStatsService:
    @staticmethod
    async def get_stats(session: Session, user_id: str, viewer_id: str) -> dict:
        key = f"user:{user_id}:stats:v1:viewer={viewer_id}"
        cached = await redis.get(key)
        if cached:
            return json.loads(cached)

        stats = _compute_expensive_stats(session, user_id)  # heavy query
        await redis.set(key, json.dumps(stats), ex=300)  # 5 min TTL
        return stats
```

Note the key includes the **viewer** — different users may see different stats for the same target user.

---

## TL;DR Decision Flow

1. **Same data fetched twice in one request?** → DataLoader.
2. **Same data fetched across requests, expensive to compute?** → Redis.
3. **Same query served to many anonymous users?** → APQ + CDN.
4. **UI inconsistency after mutations?** → Client normalized cache + proper mutation updates.
5. **Stale data showing up?** → Revisit cache key (missing user/tenant?) and invalidation strategy.
