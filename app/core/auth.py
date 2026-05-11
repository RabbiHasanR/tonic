from strawberry.exceptions import GraphQLError
from strawberry.types import Info


def require_user(info: Info):
    """Return the authenticated user from context or raise an auth error."""
    user = info.context.user
    if user is None:
        raise GraphQLError("Authentication required")
    return user
