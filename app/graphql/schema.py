import strawberry
from strawberry.tools import merge_types

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

schema = strawberry.Schema(query=Query, mutation=Mutation)
