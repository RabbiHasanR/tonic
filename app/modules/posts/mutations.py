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
        info.context.loaders.invalidate_author_posts(str(row.author_id))
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
        # Title/body changed; cached connection holds the old object. Count unchanged.
        info.context.loaders.posts_by_author.clear_all()
        return Post.from_model(row)

    @strawberry.mutation
    def delete_post(self, info: Info, id: strawberry.ID) -> bool:
        user = require_user(info)
        post_id = str(id)
        author_id = PostService.delete_post(
            info.context.session, post_id=post_id, actor_id=user.id
        )
        loaders = info.context.loaders
        loaders.invalidate_author_posts(author_id)
        loaders.invalidate_post_comments(post_id)
        return True
