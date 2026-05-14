from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import aliased
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from app.graphql.pagination import encode_cursor, paginate
from app.modules.posts.service import PostService

from .models import Comment


class CommentService:
    @staticmethod
    def list_by_post_connection(
        session: Session,
        post_id: str,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        with_count: bool = False,
    ) -> tuple[list[Comment], bool, bool, int]:
        try:
            pid = UUID(post_id)
        except ValueError:
            return [], False, False, 0
        return paginate(
            session,
            base_stmt=select(Comment).where(Comment.post_id == pid),
            count_stmt=select(func.count())
            .select_from(Comment)
            .where(Comment.post_id == pid),
            sort_col=Comment.created_at,
            id_col=Comment.id,
            first=first,
            after=after,
            last=last,
            before=before,
            direction="asc",
            with_count=with_count,
        )

    @staticmethod
    def encode_cursor(comment: Comment) -> str:
        return encode_cursor(comment.created_at, comment.id)

    @staticmethod
    def batch_first_page_by_posts(
        session: Session,
        post_ids: list[str],
        limit: int,
    ) -> dict[str, tuple[list[Comment], bool]]:
        """First `limit` comments per post in one window-function query.

        Order matches the per-parent query: created_at ASC, id ASC.
        Used only when no cursor (`after`/`before`/`last`) is passed.
        """
        valid: list[UUID] = []
        for raw in post_ids:
            try:
                valid.append(UUID(raw))
            except ValueError:
                continue
        result: dict[str, tuple[list[Comment], bool]] = {
            str(pid): ([], False) for pid in valid
        }
        if not valid:
            return result

        rn = func.row_number().over(
            partition_by=Comment.post_id,
            order_by=(Comment.created_at.asc(), Comment.id.asc()),
        ).label("rn")
        subq = (
            select(Comment, rn).where(Comment.post_id.in_(valid)).subquery()
        )
        CommentAlias = aliased(Comment, subq)
        stmt = select(CommentAlias).where(subq.c.rn <= limit + 1)
        rows = session.exec(stmt).all()

        grouped: dict[str, list[Comment]] = {str(pid): [] for pid in valid}
        for c in rows:
            grouped.setdefault(str(c.post_id), []).append(c)

        for pid_str, comments in grouped.items():
            comments.sort(key=lambda c: (c.created_at, c.id))
            has_next = len(comments) > limit
            result[pid_str] = (comments[:limit] if has_next else comments, has_next)
        return result

    @staticmethod
    def count_by_posts(
        session: Session, post_ids: list[str]
    ) -> dict[str, int]:
        """Batched GROUP BY count for the `Post.comments.totalCount` lazy field."""
        valid: list[UUID] = []
        for raw in post_ids:
            try:
                valid.append(UUID(raw))
            except ValueError:
                continue
        result = {str(pid): 0 for pid in valid}
        if not valid:
            return result
        rows = session.exec(
            select(Comment.post_id, func.count())
            .where(Comment.post_id.in_(valid))
            .group_by(Comment.post_id)
        ).all()
        for pid, n in rows:
            result[str(pid)] = int(n)
        return result

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
    def update_comment(
        session: Session, comment_id: str, actor_id: UUID, body: str
    ) -> Comment:
        comment = CommentService.get_comment(session, comment_id)
        if comment.author_id != actor_id:
            raise GraphQLError("Not authorized to update this comment")
        if not body.strip():
            raise GraphQLError("Comment body is required")
        comment.body = body.strip()
        session.add(comment)
        session.commit()
        session.refresh(comment)
        return comment

    @staticmethod
    def delete_comment(session: Session, comment_id: str, actor_id: UUID) -> str:
        comment = CommentService.get_comment(session, comment_id)
        if comment.author_id != actor_id:
            raise GraphQLError("Not authorized to delete this comment")
        post_id = str(comment.post_id)
        session.delete(comment)
        session.commit()
        return post_id
