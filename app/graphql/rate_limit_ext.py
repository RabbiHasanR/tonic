"""Strawberry extension: compute query cost, enforce hard cap + token bucket.

Runs in `on_validate` — after parse/validate, before execute. By then we
have the parsed `graphql_document`, the resolved `variables`, the
`operation_name`, and `context.client_key`. We compute the complexity
score once and use it for both checks:

1. If score > `MAX_QUERY_COMPLEXITY`: reject outright (would-be expensive
   single request — bucket state doesn't matter).
2. Otherwise charge `score` tokens into `rl:{client_key}` via the
   Redis-backed token bucket. Overflow → reject with retry hint.

Disabled when `settings.RATE_LIMIT_ENABLED` is false (early return).
"""

from strawberry.exceptions import GraphQLError
from strawberry.extensions import SchemaExtension

from app.core.config import settings
from app.graphql.complexity import estimate_complexity
from app.graphql.rate_limit import bucket


class RateLimitExtension(SchemaExtension):
    def on_validate(self):
        if not settings.RATE_LIMIT_ENABLED:
            yield
            return

        ec = self.execution_context
        # Run validation first — only score a parseable, valid document.
        yield
        if ec.pre_execution_errors:
            return
        if ec.graphql_document is None:
            return

        # Lazy import to avoid the schema ↔ extension circular import.
        from app.graphql.schema import schema as strawberry_schema

        try:
            cost = estimate_complexity(
                strawberry_schema._schema,
                ec.graphql_document,
                ec.variables,
                ec.operation_name,
            )
        except Exception:
            # Estimator bug must not break the API — bill 1 and move on.
            cost = 1

        if cost > settings.MAX_QUERY_COMPLEXITY:
            raise GraphQLError(
                f"Query too complex: {cost} > {settings.MAX_QUERY_COMPLEXITY}"
            )

        client_key = getattr(ec.context, "client_key", "ip:unknown")
        allowed, retry = bucket.check(f"rl:{client_key}", cost)
        if not allowed:
            raise GraphQLError(
                f"Rate limit exceeded (cost {cost}). Retry in {retry:.2f}s"
            )
