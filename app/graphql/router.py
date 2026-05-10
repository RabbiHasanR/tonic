from strawberry.fastapi import GraphQLRouter
from app.core.config import settings
from .context import get_context
from .schema import schema


graphql_router = GraphQLRouter(
    schema,
    context_getter=get_context,
    graphql_ide="graphiql" if settings.ENVIRONMENT != "production" else None,
)
