from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import aliased
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from app.graphql.pagination import encode_cursor, paginate

from .models import Post


class PostService:
    @staticmethod
    def list_posts_connection(
        session: Session,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        with_count: bool = False,
    ) -> tuple[list[Post], bool, bool, int]:
        return paginate(
            session,
            base_stmt=select(Post),
            count_stmt=select(func.count()).select_from(Post),
            sort_col=Post.created_at,
            id_col=Post.id,
            first=first,
            after=after,
            last=last,
            before=before,
            direction="desc",
            with_count=with_count,
        )

    @staticmethod
    def list_by_author_connection(
        session: Session,
        author_id: str,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
        with_count: bool = False,
    ) -> tuple[list[Post], bool, bool, int]:
        try:
            aid = UUID(author_id)
        except ValueError:
            return [], False, False, 0
        return paginate(
            session,
            base_stmt=select(Post).where(Post.author_id == aid),
            count_stmt=select(func.count())
            .select_from(Post)
            .where(Post.author_id == aid),
            sort_col=Post.created_at,
            id_col=Post.id,
            first=first,
            after=after,
            last=last,
            before=before,
            direction="desc",
            with_count=with_count,
        )

    @staticmethod
    def encode_cursor(post: Post) -> str:
        return encode_cursor(post.created_at, post.id)

    @staticmethod
    def batch_first_page_by_authors(
        session: Session,
        author_ids: list[str],
        limit: int,
    ) -> dict[str, tuple[list[Post], bool]]:
        """Return first `limit` posts per author in a single window-function query.

        Used only when the caller did not pass `after`/`before`/`last` — those
        cursor cases bypass the batch loader and use `list_by_author_connection`.
        Order matches the per-parent query: created_at DESC, id DESC.
        Returns {author_id_str: (nodes, has_next_page)}.
        """
        valid: list[UUID] = []
        for raw in author_ids:
            try:
                valid.append(UUID(raw))
            except ValueError:
                continue
        result: dict[str, tuple[list[Post], bool]] = {
            str(aid): ([], False) for aid in valid
        }
        if not valid:
            return result

        rn = func.row_number().over(
            partition_by=Post.author_id,
            order_by=(Post.created_at.desc(), Post.id.desc()),
        ).label("rn")
        subq = (
            select(Post, rn).where(Post.author_id.in_(valid)).subquery()
        )
        PostAlias = aliased(Post, subq)
        stmt = select(PostAlias).where(subq.c.rn <= limit + 1)
        rows = session.exec(stmt).all()

        grouped: dict[str, list[Post]] = {str(aid): [] for aid in valid}
        for post in rows:
            grouped.setdefault(str(post.author_id), []).append(post)

        for aid_str, posts in grouped.items():
            posts.sort(key=lambda p: (p.created_at, p.id), reverse=True)
            has_next = len(posts) > limit
            result[aid_str] = (posts[:limit] if has_next else posts, has_next)
        return result

    @staticmethod
    def count_by_authors(
        session: Session, author_ids: list[str]
    ) -> dict[str, int]:
        """Batched GROUP BY count for the `User.posts.totalCount` lazy field."""
        valid: list[UUID] = []
        for raw in author_ids:
            try:
                valid.append(UUID(raw))
            except ValueError:
                continue
        result = {str(aid): 0 for aid in valid}
        if not valid:
            return result
        rows = session.exec(
            select(Post.author_id, func.count())
            .where(Post.author_id.in_(valid))
            .group_by(Post.author_id)
        ).all()
        for aid, n in rows:
            result[str(aid)] = int(n)
        return result

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
    def delete_post(session: Session, post_id: str, actor_id: UUID) -> str:
        post = PostService.get_post(session, post_id)
        if post.author_id != actor_id:
            raise GraphQLError("Not authorized to delete this post")
        author_id = str(post.author_id)
        session.delete(post)
        session.commit()
        return author_id
