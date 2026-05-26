import strawberry
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import (
    AddValidationRules,
    MaxAliasesLimiter,
    MaxTokensLimiter,
    QueryDepthLimiter,
)
from strawberry.extensions.tracing import OpenTelemetryExtension
from strawberry.tools import merge_types

from app.core.config import settings
from app.graphql.rate_limit_ext import RateLimitExtension
from app.modules.comments.mutations import CommentsMutation
from app.modules.posts.mutations import PostsMutation
from app.modules.posts.queries import PostsQuery
from app.modules.users.mutations import UsersMutation
from app.modules.users.queries import UsersQuery

# Why: Strawberry's tracing extension dumps resolver kwargs as span attributes.
# Mutations like register/login carry plaintext passwords inside their input
# objects, so anything matching these keys (at any depth) is redacted before
# it leaves the process.
_SENSITIVE_KEYS = {"password", "current_password", "new_password", "token", "secret"}


def _scrub(value):
    if hasattr(value, "__dataclass_fields__"):
        return {
            f: ("[REDACTED]" if f.lower() in _SENSITIVE_KEYS else _scrub(getattr(value, f)))
            for f in value.__dataclass_fields__
        }
    if isinstance(value, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in _SENSITIVE_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _scrub_sensitive_args(kwargs: dict, info) -> dict:
    return {k: _scrub(v) for k, v in kwargs.items()}


@strawberry.type
class _RootQuery:
    @strawberry.field
    def ping(self) -> str:
        return "pong"


Query = merge_types("Query", (_RootQuery, UsersQuery, PostsQuery))
Mutation = merge_types("Mutation", (UsersMutation, PostsMutation, CommentsMutation))

extensions = [
    QueryDepthLimiter(max_depth=settings.MAX_QUERY_DEPTH),
    MaxAliasesLimiter(max_alias_count=settings.MAX_QUERY_ALIASES),
    MaxTokensLimiter(max_token_count=settings.MAX_QUERY_TOKENS),
    RateLimitExtension,
]
if settings.OTEL_ENABLED:
    extensions.append(OpenTelemetryExtension(arg_filter=_scrub_sensitive_args))
if settings.ENVIRONMENT == "production":
    extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

schema = strawberry.Schema(query=Query, mutation=Mutation, extensions=extensions)
