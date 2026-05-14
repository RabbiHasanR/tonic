from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

import strawberry
from strawberry.types import Info

from app.graphql.pagination import PageInfo

if TYPE_CHECKING:
    from app.modules.users.types import User


@strawberry.type
class Comment:
    id: strawberry.ID
    body: str
    created_at: datetime
    updated_at: datetime
    author_id: strawberry.Private[str]
    post_id: strawberry.Private[str]

    @classmethod
    def from_model(cls, m) -> "Comment":
        return cls(
            id=strawberry.ID(str(m.id)),
            body=m.body,
            created_at=m.created_at,
            updated_at=m.updated_at,
            author_id=str(m.author_id),
            post_id=str(m.post_id),
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


@strawberry.input
class CommentCreateInput:
    post_id: strawberry.ID
    body: str


@strawberry.input
class CommentUpdateInput:
    id: strawberry.ID
    body: str


@strawberry.type
class CommentEdge:
    cursor: str
    node: Comment


@strawberry.type
class CommentConnection:
    edges: list[CommentEdge]
    page_info: PageInfo
    # Lazy totalCount. kind="by_post" routes through the batched count loader.
    _count_kind: strawberry.Private[str] = "by_post"
    _count_key: strawberry.Private[Optional[str]] = None

    @strawberry.field
    async def total_count(self, info: Info) -> int:
        if self._count_kind == "by_post" and self._count_key is not None:
            return await info.context.loaders.comment_count_by_post.load(
                self._count_key
            )
        return 0
