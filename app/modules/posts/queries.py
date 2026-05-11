import strawberry
from strawberry.types import Info

from .service import PostService
from .types import Post


@strawberry.type
class PostsQuery:
    @strawberry.field
    def posts(self, info: Info, limit: int = 20) -> list[Post]:
        rows = PostService.list_posts(info.context.session, limit=limit)
        return [Post.from_model(r) for r in rows]

    @strawberry.field
    def post(self, info: Info, id: strawberry.ID) -> Post:
        row = PostService.get_post(info.context.session, str(id))
        return Post.from_model(row)
