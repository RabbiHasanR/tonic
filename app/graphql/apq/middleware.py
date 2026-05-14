"""ASGI middleware: Automatic Persisted Queries + Cache-Control.

Why this lives at the ASGI layer (not as a Strawberry SchemaExtension):
Strawberry's HTTP view rejects requests whose body has no `query` field
*before* any schema extension runs. APQ's whole point is to send hash-only
requests, so the interception must happen above Strawberry.

Two responsibilities, kept in one middleware so the resolved query is shared:

1. APQ:
   - GET with `extensions.persistedQuery.sha256Hash` and no `query` → look up
     the query in Redis. Miss → return the standard `PersistedQueryNotFound`
     error. Hit → inject `query` into the URL.
   - POST with hash and no query → same lookup, inject into body.
   - POST with hash AND query → verify `sha256(query) == hash` (prevents
     poisoning), store, then pass through.

2. Cache-Control: detect the root field of the resolved query and set
   `Cache-Control` on the response. Public reads (`post`, `user`, `posts`)
   are cacheable; everything else is `no-store`. If the response carries any
   `errors`, override to `no-store` (so transient errors don't get pinned).

Mutations on GET are already refused by Strawberry — we don't re-enforce.
"""

import hashlib
import json
import re
from typing import Optional
from urllib.parse import urlencode

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.graphql.apq.store import apq_store

GRAPHQL_PATH = "/graphql"

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB — GraphQL queries are tiny; cap to prevent OOM.

PERSISTED_QUERY_NOT_FOUND = {
    "errors": [
        {
            "message": "PersistedQueryNotFound",
            "extensions": {"code": "PERSISTED_QUERY_NOT_FOUND"},
        }
    ]
}

# Root field name -> Cache-Control header for cacheable public reads.
# `posts` is cached only on the first page (no `after` cursor); deeper pages
# are downgraded to no-store at response time.
_CACHE_POLICY: dict[str, bytes] = {
    "post": b"public, max-age=60, s-maxage=600",
    "user": b"public, max-age=60, s-maxage=600",
    "posts": b"public, max-age=30, s-maxage=60",
}

_NO_STORE = b"no-store"

# Find the first identifier inside the operation's top-level selection set.
# Works for: `query GetPost($id:ID!) { post(id:$id) { ... } }` -> "post"
# and for the shorthand: `{ post(id: "x") { ... } }` -> "post".
_ROOT_FIELD_RE = re.compile(r"\{\s*([A-Za-z_]\w*)")

# Match operations that start with `query` or shorthand `{`. Anything else
# (mutation, subscription) gets `no-store` regardless of root field name.
_QUERY_OP_RE = re.compile(r"^\s*(?:#[^\n]*\n\s*)*(?:query\b|\{)")


class _BodyTooLarge(Exception):
    pass


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _extract_hash(extensions: object) -> Optional[str]:
    if not isinstance(extensions, dict):
        return None
    pq = extensions.get("persistedQuery")
    if not isinstance(pq, dict):
        return None
    h = pq.get("sha256Hash")
    return h if isinstance(h, str) else None


def _root_field(query: str) -> Optional[str]:
    m = _ROOT_FIELD_RE.search(query)
    return m.group(1) if m else None


class GraphQLAPQMiddleware:
    """APQ resolution + Cache-Control injection for the `/graphql` endpoint."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(GRAPHQL_PATH):
            await self.app(scope, receive, send)
            return

        method = scope.get("method")
        if method == "GET":
            await self._handle_get(scope, receive, send)
        elif method == "POST":
            await self._handle_post(scope, receive, send)
        else:
            await self.app(scope, receive, send)

    # ---------- GET ----------

    async def _handle_get(self, scope: Scope, receive: Receive, send: Send) -> None:
        params = self._parse_query_params(scope.get("query_string", b""))
        ext_raw = params.get("extensions")
        extensions: object = None
        if ext_raw:
            try:
                extensions = json.loads(ext_raw)
            except json.JSONDecodeError:
                await self._send_json(send, {"errors": [{"message": "Invalid extensions JSON"}]}, 400)
                return

        hash_ = _extract_hash(extensions)
        query = params.get("query")

        if hash_ and not query:
            stored = await apq_store.get(hash_)
            if not stored:
                await self._send_json(send, PERSISTED_QUERY_NOT_FOUND, 200)
                return
            query = stored
            params["query"] = stored
            new_scope = dict(scope)
            new_scope["query_string"] = urlencode(params).encode("utf-8")
            scope = new_scope

        variables = self._safe_json(params.get("variables"))
        await self._serve_with_cache(scope, receive, send, query, variables)

    # ---------- POST ----------

    async def _handle_post(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._content_length_exceeds(scope, MAX_BODY_BYTES):
            await self._send_json(send, {"errors": [{"message": "Request body too large"}]}, 413)
            return
        try:
            body = await self._read_body(receive, MAX_BODY_BYTES)
        except _BodyTooLarge:
            await self._send_json(send, {"errors": [{"message": "Request body too large"}]}, 413)
            return
        payload = self._safe_json(body.decode("utf-8") if body else "")
        if not isinstance(payload, dict):
            await self._replay(scope, body, send, query=None, variables=None)
            return

        extensions = payload.get("extensions")
        hash_ = _extract_hash(extensions)
        query = payload.get("query") if isinstance(payload.get("query"), str) else None
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else None

        if hash_ and query:
            # Register path — verify before storing to prevent cache poisoning.
            if _hash_query(query) != hash_:
                await self._send_json(send, {"errors": [{"message": "Persisted query hash mismatch"}]}, 400)
                return
            await apq_store.set(hash_, query)
            await self._replay(scope, body, send, query=query, variables=variables)
            return

        if hash_ and not query:
            # Lookup path.
            stored = await apq_store.get(hash_)
            if not stored:
                await self._send_json(send, PERSISTED_QUERY_NOT_FOUND, 200)
                return
            payload["query"] = stored
            new_body = json.dumps(payload).encode("utf-8")
            await self._replay(scope, new_body, send, query=stored, variables=variables)
            return

        # No APQ involvement — pass through as-is.
        await self._replay(scope, body, send, query=query, variables=variables)

    # ---------- Plumbing ----------

    async def _serve_with_cache(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        query: Optional[str],
        variables: Optional[dict],
    ) -> None:
        wrapped = self._wrap_send_with_cache(send, query, variables)
        await self.app(scope, receive, wrapped)

    async def _replay(
        self,
        scope: Scope,
        body: bytes,
        send: Send,
        query: Optional[str],
        variables: Optional[dict],
    ) -> None:
        sent = False

        async def receive() -> Message:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        # Update Content-Length on the scope headers to match the replayed body.
        new_scope = dict(scope)
        new_scope["headers"] = self._with_content_length(scope.get("headers", []), len(body))

        wrapped = self._wrap_send_with_cache(send, query, variables)
        await self.app(new_scope, receive, wrapped)

    def _wrap_send_with_cache(
        self,
        send: Send,
        query: Optional[str],
        variables: Optional[dict],
    ) -> Send:
        # Buffer the response body so we can inspect for `errors` before sending.
        cache_header = self._policy_for(query, variables)
        start_message: Optional[Message] = None
        body_chunks: list[bytes] = []

        async def wrapped(message: Message) -> None:
            nonlocal start_message
            mtype = message["type"]
            if mtype == "http.response.start":
                start_message = message
                return
            if mtype == "http.response.body":
                body_chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                # Final chunk — decide cache header now.
                full = b"".join(body_chunks)
                header_value = self._final_cache_value(cache_header, full)
                headers = self._set_header(
                    (start_message or {}).get("headers", []),
                    b"cache-control",
                    header_value,
                )
                final_start = dict(start_message or {"type": "http.response.start", "status": 200})
                final_start["headers"] = headers
                await send(final_start)
                await send({"type": "http.response.body", "body": full, "more_body": False})
                return
            # Anything else (e.g. trailers) — pass through.
            await send(message)

        return wrapped

    @staticmethod
    def _policy_for(query: Optional[str], variables: Optional[dict]) -> bytes:
        if not query:
            return _NO_STORE
        if not _QUERY_OP_RE.match(query):
            return _NO_STORE
        field = _root_field(query)
        if field is None:
            return _NO_STORE
        policy = _CACHE_POLICY.get(field)
        if policy is None:
            return _NO_STORE
        # `posts` is only cacheable for the first page (no `after` cursor).
        if field == "posts" and variables and variables.get("after"):
            return _NO_STORE
        return policy

    @staticmethod
    def _final_cache_value(planned: bytes, body: bytes) -> bytes:
        if planned == _NO_STORE:
            return _NO_STORE
        # If the response carries any errors, override to no-store.
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return _NO_STORE
        if isinstance(parsed, dict) and parsed.get("errors"):
            return _NO_STORE
        return planned

    @staticmethod
    async def _read_body(receive: Receive, max_bytes: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        more = True
        while more:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > max_bytes:
                raise _BodyTooLarge()
            chunks.append(chunk)
            more = message.get("more_body", False)
        return b"".join(chunks)

    @staticmethod
    def _content_length_exceeds(scope: Scope, max_bytes: int) -> bool:
        for k, v in scope.get("headers", []):
            if k.lower() == b"content-length":
                try:
                    return int(v) > max_bytes
                except (ValueError, TypeError):
                    return False
        return False

    @staticmethod
    def _parse_query_params(qs: bytes) -> dict[str, str]:
        from urllib.parse import parse_qsl

        return {k: v for k, v in parse_qsl(qs.decode("utf-8"), keep_blank_values=True)}

    @staticmethod
    def _safe_json(raw: Optional[str]) -> object:
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _with_content_length(headers: list[tuple[bytes, bytes]], length: int) -> list[tuple[bytes, bytes]]:
        out = [(k, v) for k, v in headers if k.lower() != b"content-length"]
        out.append((b"content-length", str(length).encode()))
        return out

    @staticmethod
    def _set_header(headers: list[tuple[bytes, bytes]], name: bytes, value: bytes) -> list[tuple[bytes, bytes]]:
        lname = name.lower()
        out = [(k, v) for k, v in headers if k.lower() != lname]
        out.append((name, value))
        return out

    @staticmethod
    async def _send_json(send: Send, payload: dict, status: int) -> None:
        body = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})
