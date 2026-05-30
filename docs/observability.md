# Observability — How GraphQL Tracing Works in Tonic

This doc explains, end-to-end, **what happens between the moment a GraphQL request lands on the server and the moment a trace shows up in the Jaeger UI**. It also explains *why* each piece exists, so when something breaks (or you want to extend it) you can reason about it instead of guessing.

The setup is OpenTelemetry-based and lives in [app/core/observability.py](../app/core/observability.py) plus the collector/Jaeger services in [docker-compose.yml](../docker-compose.yml).

---

## 0. Quick Mental Model

A **trace** is the full story of one request. A **span** is one chapter of that story (a function call, a DB query, a cache hit). Spans nest — a parent span contains child spans — and together they form a tree.

```text
Trace = "POST /graphql, getPostWithComments query"
│
├─ Span: HTTP POST /graphql                    (200ms)
│  └─ Span: GraphQL Operation: getPostWithComments
│     ├─ Span: resolver Post.author
│     │  └─ Span: SELECT * FROM users WHERE id = $1     (3ms)
│     ├─ Span: resolver Post.comments
│     │  ├─ Span: GET redis "post:abc:comments:first10"  (1ms, miss)
│     │  └─ Span: SELECT * FROM comments WHERE ...       (15ms)
│     └─ Span: resolver Comment.author (batched)
│        └─ Span: SELECT * FROM users WHERE id IN (...)  (4ms)
```

That tree is what you see in Jaeger. The whole point of OpenTelemetry is to produce that tree automatically and ship it somewhere you can look at it.

---

## 1. Why OpenTelemetry (Not Just `print` or APM)

Three traditional approaches and what they miss:

| Approach | What it gives you | What it misses |
|---|---|---|
| `print` / log lines | "Got here, took 200ms" | No request correlation, no nested structure, no cross-service propagation |
| Vendor APM agent (Datadog, NewRelic) | Auto-instrumented spans | Vendor lock-in, expensive at scale, one tool per signal |
| Prometheus only | Great metrics dashboards | Aggregate-only — can't answer "*why* was *this* request slow?" |

**OpenTelemetry** is a vendor-neutral instrumentation API + SDK + wire protocol (OTLP) governed by the CNCF. You instrument once, then point the exporter at whichever backend you want: Jaeger, Tempo, Honeycomb, Grafana Cloud, Datadog, etc. Switching backends is one env var.

In this project we use OTel for **traces** in Phase 1. Metrics and structured logs are deferred to Phase 2/3.

---

## 2. The Pieces and How They Connect

```text
┌─────────────────────────────────────────────────────────────────┐
│                       Tonic API container                       │
│                                                                 │
│   FastAPI ─── Strawberry ─── SQLAlchemy ─── Redis client        │
│      │            │              │              │               │
│      └────────────┴──────────────┴──────────────┘               │
│                          │                                      │
│                  OpenTelemetry SDK                              │
│                (TracerProvider + Batch                          │
│                 SpanProcessor + OTLP                            │
│                  gRPC Exporter)                                 │
│                          │                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           │ OTLP/gRPC :4317
                           ▼
              ┌────────────────────────┐
              │  otel-collector        │
              │  (receive → batch →    │
              │   export)              │
              └────────────────────────┘
                           │ OTLP/gRPC :4317
                           ▼
              ┌────────────────────────┐
              │  jaeger (all-in-one)   │
              │  storage + UI :16686   │
              └────────────────────────┘
                           │
                           ▼
                 You, in a browser
```

Five distinct responsibilities:

1. **Instrumentation libraries** wrap the frameworks (FastAPI, SQLAlchemy, Redis, Strawberry) and create spans automatically.
2. **The SDK** owns the tracer provider, sampling decision, and span lifecycle.
3. **The OTLP exporter** serializes spans and sends them over gRPC to the collector.
4. **The OTel Collector** is a separate process that batches/processes/forwards spans. In Phase 1 it just forwards to Jaeger, but it's where you'd later add tail-based sampling, redaction, fan-out to multiple backends, etc.
5. **Jaeger** stores spans and provides the UI.

The collector sits in the middle so the app never talks directly to the storage backend. Swap Jaeger for Tempo tomorrow — only the collector config changes, the app stays the same.

---

## 3. What Happens When a GraphQL Request Arrives

Walking through a real request — `query getPost($id: ID!) { post(id: $id) { title author { displayName } } }`:

### Step 1 — TCP/HTTP edge

The request hits Uvicorn → FastAPI. The `FastAPIInstrumentor` (initialized in [app/core/observability.py](../app/core/observability.py)) has wrapped the ASGI app, so before any handler runs:

- A **root span** is created: `POST /graphql`.
- A unique `trace_id` (128-bit) and `span_id` (64-bit) are generated.
- The sampler is consulted. With `OTEL_TRACES_SAMPLER_ARG=1.0` it always says "record this".
- If the request had a `traceparent` header (from another upstream service), the SDK adopts that trace_id instead — this is how distributed tracing chains services together (W3C Trace Context propagation).

`/health` is explicitly excluded so kubelet probes don't drown the trace store.

### Step 2 — Middleware chain

Body-size check → CORS → GZip → APQ middleware all run *inside* the root span. They don't create their own spans by default (low value, would clutter the trace) but they share the active span context, so anything they log carries the trace ID.

### Step 3 — Strawberry takes over

The GraphQL router parses the request, looks up the operation, and starts executing. The **Strawberry `OpenTelemetryExtension`** (added to the schema's extensions list) hooks into the lifecycle:

- `on_operation` — opens a span named `GraphQL Operation: getPost`. Attributes include `graphql.operation.name`, `graphql.operation.type`, and the (scrubbed) variables.
- `on_validate` / `on_parse` — short spans around schema validation and query parsing.
- `on_execute` — opens a span around the resolver execution phase.

Every resolver call gets its own child span: `GraphQL Resolver: Post.title`, `GraphQL Resolver: Post.author`, etc. This is what makes "which field was slow?" answerable.

### Step 4 — Resolver hits the service layer

The resolver calls `PostService.get_post(session, id)`. The service may:

- **Check Redis first** — the `RedisInstrumentor` has monkey-patched the `redis` client. The `GET post:{id}` call is wrapped in a span: `GET` with attributes like `db.system="redis"`, `db.statement="GET post:abc"`. On a hit, this span is ~1ms and the resolver returns.
- **Fall through to Postgres** — the `SQLAlchemyInstrumentor` is attached to the engine. Every `session.exec(...)` produces a span: `SELECT posts` with `db.system="postgresql"`, `db.statement="SELECT ..."` (parameter values are NOT included — those bind separately and never reach span attributes). Duration is the actual wall-clock for the round trip.

### Step 5 — DataLoader batches

When the resolver for `Post.author` runs, it goes through `UserLoader`. DataLoader collects all `author_id`s requested during this request, then issues one `SELECT * FROM users WHERE id IN (...)`. That single SQL call gets one span — you can see in Jaeger that 50 author resolutions caused exactly one DB hit, not 50. This is how N+1 problems become visible: a missing DataLoader shows up as a fan of 50 sibling `SELECT users WHERE id = X` spans instead of one batched span.

### Step 6 — Response is built and returned

Strawberry serializes the response. The execute span closes, the operation span closes, the HTTP span closes. At each close, the SDK records the span's end time, status, and any attributes set during its lifetime.

### Step 7 — Spans leave the process

Spans are NOT sent one-by-one (that would crush the network). Instead:

- Each span goes into the **`BatchSpanProcessor`** queue (in-memory, bounded).
- A background thread flushes the queue every ~1s, or when it reaches ~512 spans, whichever first.
- The flush calls the **`OTLPSpanExporter`**, which serializes the batch as protobuf and sends it over gRPC to `otel-collector:4317`.

If the collector is unreachable, the exporter drops the batch (after retries) and logs a warning. **The user-facing request never fails because of an export problem** — observability must never break the app.

### Step 8 — Collector hop

The collector receives the batch on its OTLP receiver, runs it through the `batch` processor (just regroups), and pushes it to its `otlp/jaeger` exporter, which sends it to `jaeger:4317`.

### Step 9 — Jaeger stores and indexes

Jaeger's all-in-one image runs an in-memory store (fine for dev, not for prod). It indexes the trace by service name, operation, and tags, then makes it queryable.

### Step 10 — You open the UI

`http://localhost:16686` → pick service `tonic-api` → operation `POST /graphql` → see traces. Click one → see the full span tree, durations, attributes, errors. Click a span → see its attributes (`graphql.operation.name`, `db.statement`, etc.).

---

## 4. PII Scrubbing — Why and How

GraphQL inputs sometimes carry secrets. The `register` and `login` mutations both accept a plaintext `password` field. Without protection, Strawberry's tracing extension would dump the entire `input` object as a span attribute, and **plaintext passwords would land in Jaeger**, then probably in backups, log aggregators, screenshots in Slack, etc.

To prevent this, [app/graphql/schema.py](../app/graphql/schema.py) passes a custom `arg_filter` to `OpenTelemetryExtension`:

```python
_SENSITIVE_KEYS = {"password", "current_password", "new_password", "token", "secret"}

def _scrub(value):
    if hasattr(value, "__dataclass_fields__"):
        return {
            f: ("[REDACTED]" if f.lower() in _SENSITIVE_KEYS else _scrub(getattr(value, f)))
            for f in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if str(k).lower() in _SENSITIVE_KEYS else _scrub(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value
```

Key points:

- **Recursive.** Strawberry inputs are dataclasses; `register(input: RegisterInput)` has the password *inside* `input`. A shallow filter wouldn't catch it.
- **Key-based, not value-based.** We don't try to detect "this string looks like a password" — too brittle. We redact anything *named* like a credential.
- **Allowlist by name** — adding a new sensitive field name later just means adding to `_SENSITIVE_KEYS`.

Other PII risks already covered by defaults:

- **HTTP headers** — FastAPIInstrumentor doesn't capture headers unless `OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST` is set. We don't set it. Authorization tokens never enter spans.
- **SQL bind parameters** — SQLAlchemyInstrumentor captures `db.statement` (the SQL with `$1`, `$2` placeholders) but never the bind values. Passwords passed to `INSERT INTO users` don't appear.

---

## 5. Sampling — Recording vs Always-On

`OTEL_TRACES_SAMPLER_ARG` controls what fraction of traces get recorded. The sampler is `ParentBased(TraceIdRatioBased(arg))`:

- **`TraceIdRatioBased(arg)`** — for a new (root) trace, hash the trace_id and keep `arg * 2^64` worth of values. With `arg=0.1`, exactly 10% of traces are kept; the rest are silently dropped before they ever hit the exporter.
- **`ParentBased`** — wrap that with "if an incoming `traceparent` header says this trace was already sampled upstream, respect that decision." This is how a sampled trace stays whole across services — you don't want 10% of service A's spans and 10% of service B's spans in the same trace.

For local dev: `1.0` (sample everything — we want to see things).
For prod: `0.05`–`0.2` is typical. Pair with tail-based sampling in the collector to ensure errors are always kept.

---

## 6. Trace-Log Correlation

`LoggingInstrumentor().instrument()` patches the stdlib logger so every `LogRecord` automatically carries the current `trace_id` and `span_id`. If you eventually adopt structured JSON logging and ship logs to Loki/Elasticsearch, you can click a Jaeger trace → see the log lines from that exact request.

In Phase 1 we wire the instrumentor but don't enforce a JSON log format yet, so this is mostly latent capability.

---

## 7. Reading the Jaeger UI

A practical debugging recipe — "this query feels slow":

1. Open `http://localhost:16686`.
2. Service: `tonic-api`. Operation: `POST /graphql` (or filter by tag `graphql.operation.name=getPostWithComments`).
3. Click "Find Traces". Sort by duration descending.
4. Open the slowest trace. Expand the span tree.
5. Look for the widest dark bar — that's where the time went.
6. Click that span. Inspect attributes.

Things you'll often see:

- **One fat `SELECT`** — your query needs an index, a JOIN, or pagination.
- **A fan of small `SELECT`s with the same shape** — N+1, your DataLoader isn't engaging.
- **A long gap between spans** — Python-side work (serialization, business logic). Not visible without custom spans.
- **A red span** — error. Status code and `exception.message` attribute tell you what.

---

## 8. Failure Modes

| Symptom | Likely cause | Where to look |
|---|---|---|
| No traces in Jaeger | `OTEL_ENABLED=false`, or collector not reachable | `docker compose logs otel-collector` |
| Some traces missing | Sampler arg too low | `OTEL_TRACES_SAMPLER_ARG=1.0` for debugging |
| Spans show but no SQL spans | SQLAlchemyInstrumentor didn't attach to the engine | Check that `init_observability(app, engine)` runs once at startup |
| Spans show but no Redis spans | Cache code created its client *before* `RedisInstrumentor().instrument()` ran | Confirm observability init runs before any cache call |
| Passwords visible in span attrs | A sensitive field name not in `_SENSITIVE_KEYS` | Extend the set in [schema.py](../app/graphql/schema.py) |
| App is slow when collector is down | Should NOT happen — exporter is async + bounded | Check exporter logs; the queue drops on overflow |

---

## 9. What's Deferred

Phase 1 is **traces only**. Three things are explicitly out of scope:

- **Custom GraphQL metrics** — complexity-cost histogram, rate-limit/auth counter, etc. Phase 2.
- **Structured JSON logging** — the LoggingInstrumentor is wired, but until the log format becomes structured JSON, trace ↔ log click-through isn't really useful. Phase 2.
- **Production backend choice** — local Jaeger is fine for development. Picking Tempo / Honeycomb / Grafana Cloud / Datadog is a Phase 3 decision and a DECISIONS.md entry when locked in.

---

## 10. TL;DR

- One env var (`OTEL_ENABLED=true`) turns on full distributed tracing.
- Auto-instrumentation gives you HTTP, GraphQL operation, resolver, SQL, and Redis spans for free.
- A Strawberry `arg_filter` strips passwords from spans before they leave the process.
- Spans batch in memory, ship via OTLP/gRPC to a collector, which forwards to Jaeger.
- Jaeger UI at `http://localhost:16686` lets you click into one slow request and see exactly which DB query / cache miss / resolver ate the time.
- The whole pipeline is vendor-neutral — Jaeger is one OTLP endpoint among many.
