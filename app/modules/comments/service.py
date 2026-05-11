from uuid import UUID

from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from app.modules.posts.service import PostService

from .models import Comment


class CommentService:
    @staticmethod
    def list_by_post(session: Session, post_id: str) -> list[Comment]:
        try:
            pid = UUID(post_id)
        except ValueError:
            return []
        stmt = select(Comment).where(Comment.post_id == pid).order_by(Comment.created_at.asc())
        return list(session.exec(stmt).all())

    @staticmethod
    def get_comment(session: Session, comment_id: str) -> Comment:
        try:
            cid = UUID(comment_id)
        except ValueError as exc:
            raise GraphQLError("Comment not found") from exc
        comment = session.get(Comment, cid)
        if comment is None:
            raise GraphQLError("Comment not found")
        return comment

    @staticmethod
    def create_comment(
        session: Session, author_id: UUID, post_id: str, body: str
    ) -> Comment:
        if not body.strip():
            raise GraphQLError("Comment body is required")
        # Validate post exists (raises GraphQLError if not)
        post = PostService.get_post(session, post_id)
        comment = Comment(post_id=post.id, author_id=author_id, body=body.strip())
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return comment

    @staticmethod
    def delete_comment(session: Session, comment_id: str, actor_id: UUID) -> None:
        comment = CommentService.get_comment(session, comment_id)
        if comment.author_id != actor_id:
            raise GraphQLError("Not authorized to delete this comment")
        session.delete(comment)
        session.commit()
