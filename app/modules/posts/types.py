from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

import strawberry
from strawberry.types import Info

from app.graphql.pagination import PageInfo

if TYPE_CHECKING:
    from app.modules.comments.types import CommentConnection
    from app.modules.users.types import User


@strawberry.type
class Post:
    id: strawberry.ID
    title: str
    body: str
    created_at: datetime
    updated_at: datetime
    author_id: strawberry.Private[str]

    @classmethod
    def from_model(cls, m) -> "Post":
        return cls(
            id=strawberry.ID(str(m.id)),
            title=m.title,
            body=m.body,
            created_at=m.created_at,
            updated_at=m.updated_at,
            author_id=str(m.author_id),
        )

    @strawberry.field
    async def author(
        self, info: Info
    ) -> Annotated["User", strawberry.lazy("app.modules.users.types")]:
        from strawberry.exceptions import GraphQLError

        from app.modules.users.types import User

        row = await info.context.loaders.user_by_id.load(self.author_id)
        if row is None:
            raise GraphQLError("Author not found")
        return User.from_model(row)

    @strawberry.field
    async def comments(
        self,
        info: Info,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> Annotated[
        "CommentConnection", strawberry.lazy("app.modules.comments.types")
    ]:
        from app.modules.comments.service import CommentService
        from app.modules.comments.types import (
            Comment,
            CommentConnection,
            CommentEdge,
        )

        post_id = str(self.id)
        can_batch = after is None and before is None and last is None
        if can_batch:
            limit = max(1, min(first if first is not None else 20, 100))
            nodes, has_next_page = await info.context.loaders.comments_by_post.load(
                (post_id, limit)
            )
            has_previous_page = False
        else:
            nodes, has_next_page, has_previous_page, _ = (
                CommentService.list_by_post_connection(
                    info.context.session,
                    post_id,
                    first=first,
                    after=after,
                    last=last,
                    before=before,
                    with_count=False,
                )
            )
        edges = [
            CommentEdge(
                cursor=CommentService.encode_cursor(row),
                node=Comment.from_model(row),
            )
            for row in nodes
        ]
        return CommentConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_next_page,
                has_previous_page=has_previous_page,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            _count_kind="by_post",
            _count_key=post_id,
        )


@strawberry.input
class PostCreateInput:
    title: str
    body: str


@strawberry.input
class PostUpdateInput:
    id: strawberry.ID
    title: Optional[str] = None
    body: Optional[str] = None


@strawberry.type
class PostEdge:
    cursor: str
    node: Post


@strawberry.type
class PostConnection:
    edges: list[PostEdge]
    page_info: PageInfo
    # Internal: how `total_count` should be resolved when selected.
    # kind="root" → COUNT(*) over all posts.
    # kind="by_author" → batched via post_count_by_author loader; key=author_id.
    _count_kind: strawberry.Private[str] = "root"
    _count_key: strawberry.Private[Optional[str]] = None

    @strawberry.field
    async def total_count(self, info: Info) -> int:
        from sqlalchemy import func
        from sqlmodel import select as sm_select

        if self._count_kind == "by_author" and self._count_key is not None:
            return await info.context.loaders.post_count_by_author.load(
                self._count_key
            )
        from .models import Post as PostModel

        return int(
            info.context.session.exec(
                sm_select(func.count()).select_from(PostModel)
            ).one()
        )
