import strawberry
from strawberry.types import Info

from app.core.auth import require_user

from .service import CommentService
from .types import Comment, CommentCreateInput, CommentUpdateInput


@strawberry.type
class CommentsMutation:
    @strawberry.mutation
    def create_comment(self, info: Info, input: CommentCreateInput) -> Comment:
        user = require_user(info)
        row = CommentService.create_comment(
            info.context.session,
            author_id=user.id,
            post_id=str(input.post_id),
            body=input.body,
        )
        info.context.loaders.invalidate_post_comments(str(row.post_id))
        return Comment.from_model(row)

    @strawberry.mutation
    def update_comment(self, info: Info, input: CommentUpdateInput) -> Comment:
        user = require_user(info)
        row = CommentService.update_comment(
            info.context.session,
            comment_id=str(input.id),
            actor_id=user.id,
            body=input.body,
        )
        # Body changed; drop the connection cache so re-reads see fresh text.
        # Count is unaffected by an update.
        info.context.loaders.comments_by_post.clear_all()
        return Comment.from_model(row)

    @strawberry.mutation
    def delete_comment(self, info: Info, id: strawberry.ID) -> bool:
        user = require_user(info)
        post_id = CommentService.delete_comment(
            info.context.session, comment_id=str(id), actor_id=user.id
        )
        info.context.loaders.invalidate_post_comments(post_id)
        return True
