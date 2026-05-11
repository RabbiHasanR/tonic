from uuid import UUID

from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from .models import Post


class PostService:
    @staticmethod
    def list_posts(session: Session, limit: int = 20) -> list[Post]:
        limit = max(1, min(limit, 100))
        stmt = select(Post).order_by(Post.created_at.desc()).limit(limit)
        return list(session.exec(stmt).all())

    @staticmethod
    def list_by_author(session: Session, author_id: str) -> list[Post]:
        try:
            aid = UUID(author_id)
        except ValueError:
            return []
        stmt = select(Post).where(Post.author_id == aid).order_by(Post.created_at.desc())
        return list(session.exec(stmt).all())

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
