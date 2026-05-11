import strawberry
from strawberry.types import Info

from app.core.auth import require_user

from .service import CommentService
from .types import Comment, CommentCreateInput


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
        return Comment.from_model(row)

    @strawberry.mutation
    def delete_comment(self, info: Info, id: strawberry.ID) -> bool:
        user = require_user(info)
        CommentService.delete_comment(
            info.context.session, comment_id=str(id), actor_id=user.id
        )
        return True
