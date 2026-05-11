import strawberry
from strawberry.types import Info

from app.core.auth import require_user

from .service import PostService
from .types import Post, PostCreateInput, PostUpdateInput


@strawberry.type
class PostsMutation:
    @strawberry.mutation
    def create_post(self, info: Info, input: PostCreateInput) -> Post:
        user = require_user(info)
        row = PostService.create_post(
            info.context.session, author_id=user.id, title=input.title, body=input.body
        )
        return Post.from_model(row)

    @strawberry.mutation
    def update_post(self, info: Info, input: PostUpdateInput) -> Post:
        user = require_user(info)
        row = PostService.update_post(
            info.context.session,
            post_id=str(input.id),
            actor_id=user.id,
            title=input.title,
            body=input.body,
        )
        return Post.from_model(row)

    @strawberry.mutation
    def delete_post(self, info: Info, id: strawberry.ID) -> bool:
        user = require_user(info)
        PostService.delete_post(info.context.session, post_id=str(id), actor_id=user.id)
        return True
