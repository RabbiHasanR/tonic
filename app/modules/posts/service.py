import base64
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, tuple_
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from .models import Post


def _encode_cursor(created_at: datetime, post_id: UUID) -> str:
    payload = json.dumps({"c": created_at.isoformat(), "id": str(post_id)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return datetime.fromisoformat(payload["c"]), UUID(payload["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise GraphQLError("Invalid cursor") from exc


def _paginate_posts(
    session: Session,
    base_stmt,
    count_stmt,
    first: int | None,
    after: str | None,
    last: int | None,
    before: str | None,
) -> tuple[list[Post], bool, bool, int]:
    if first is not None and last is not None:
        raise GraphQLError("Pass either `first` or `last`, not both")
    if after is not None and before is not None:
        raise GraphQLError("Pass either `after` or `before`, not both")
    if last is not None and after is not None:
        raise GraphQLError("`after` can only be combined with `first`")
    if first is not None and before is not None:
        raise GraphQLError("`before` can only be combined with `last`")

    backward = last is not None or before is not None

    if backward:
        limit = max(1, min(last if last is not None else 20, 100))
        stmt = base_stmt.order_by(Post.created_at.asc(), Post.id.asc())
        if before is not None:
            c_at, c_id = _decode_cursor(before)
            stmt = stmt.where(tuple_(Post.created_at, Post.id) > (c_at, c_id))
        rows = list(session.exec(stmt.limit(limit + 1)).all())
        has_previous_page = len(rows) > limit
        nodes = rows[:limit] if has_previous_page else rows
        nodes.reverse()
        has_next_page = before is not None
    else:
        limit = max(1, min(first if first is not None else 20, 100))
        stmt = base_stmt.order_by(Post.created_at.desc(), Post.id.desc())
        if after is not None:
            c_at, c_id = _decode_cursor(after)
            stmt = stmt.where(tuple_(Post.created_at, Post.id) < (c_at, c_id))
        rows = list(session.exec(stmt.limit(limit + 1)).all())
        has_next_page = len(rows) > limit
        nodes = rows[:limit] if has_next_page else rows
        has_previous_page = after is not None

    total_count = int(session.exec(count_stmt).one())
    return nodes, has_next_page, has_previous_page, total_count


class PostService:
    @staticmethod
    def list_posts_connection(
        session: Session,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> tuple[list[Post], bool, bool, int]:
        return _paginate_posts(
            session,
            base_stmt=select(Post),
            count_stmt=select(func.count()).select_from(Post),
            first=first,
            after=after,
            last=last,
            before=before,
        )

    @staticmethod
    def list_by_author_connection(
        session: Session,
        author_id: str,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> tuple[list[Post], bool, bool, int]:
        try:
            aid = UUID(author_id)
        except ValueError:
            return [], False, False, 0
        return _paginate_posts(
            session,
            base_stmt=select(Post).where(Post.author_id == aid),
            count_stmt=select(func.count())
            .select_from(Post)
            .where(Post.author_id == aid),
            first=first,
            after=after,
            last=last,
            before=before,
        )

    @staticmethod
    def encode_cursor(post: Post) -> str:
        return _encode_cursor(post.created_at, post.id)

    @staticmethod
    def get_post(session: Session, post_id: str) -> Post:
        try:
            pid = UUID(post_id)
        except ValueError as exc:
            raise GraphQLError("Post not found") from exc
        post = session.get(Post, pid)
        if post is None:
            raise GraphQLError("Post not found")
        return post

    @staticmethod
    def create_post(session: Session, author_id: UUID, title: str, body: str) -> Post:
        if not title.strip():
            raise GraphQLError("Title is required")
        if not body.strip():
            raise GraphQLError("Body is required")
        post = Post(author_id=author_id, title=title.strip(), body=body)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post

    @staticmethod
    def update_post(
        session: Session,
        post_id: str,
        actor_id: UUID,
        title: str | None,
        body: str | None,
    ) -> Post:
        post = PostService.get_post(session, post_id)
        if post.author_id != actor_id:
            raise GraphQLError("Not authorized to update this post")
        if title is not None:
            if not title.strip():
                raise GraphQLError("Title cannot be empty")
            post.title = title.strip()
        if body is not None:
            if not body.strip():
                raise GraphQLError("Body cannot be empty")
            post.body = body
        session.add(post)
        session.commit()
        session.refresh(post)
        return post

    @staticmethod
    def delete_post(session: Session, post_id: str, actor_id: UUID) -> None:
        post = PostService.get_post(session, post_id)
        if post.author_id != actor_id:
            raise GraphQLError("Not authorized to delete this post")
        session.delete(post)
        session.commit()
