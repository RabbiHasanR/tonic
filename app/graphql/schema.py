import strawberry
from graphql.validation import NoSchemaIntrospectionCustomRule
from strawberry.extensions import (
    AddValidationRules,
    MaxAliasesLimiter,
    MaxTokensLimiter,
    QueryDepthLimiter,
)
from strawberry.tools import merge_types

from app.core.config import settings
from app.graphql.rate_limit_ext import RateLimitExtension
from app.modules.comments.mutations import CommentsMutation
from app.modules.posts.mutations import PostsMutation
from app.modules.posts.queries import PostsQuery
from app.modules.users.mutations import UsersMutation
from app.modules.users.queries import UsersQuery


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
if settings.ENVIRONMENT == "production":
    extensions.append(AddValidationRules([NoSchemaIntrospectionCustomRule]))

schema = strawberry.Schema(query=Query, mutation=Mutation, extensions=extensions)
