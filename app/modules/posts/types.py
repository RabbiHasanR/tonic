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
    def author(
        self, info: Info
    ) -> Annotated["User", strawberry.lazy("app.modules.users.types")]:
        from app.modules.users.service import UserService
        from app.modules.users.types import User

        row = UserService.get_user(info.context.session, self.author_id)
        return User.from_model(row)

    @strawberry.field
    def comments(
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

        nodes, has_next_page, has_previous_page, total_count = (
            CommentService.list_by_post_connection(
                info.context.session,
                str(self.id),
                first=first,
                after=after,
                last=last,
                before=before,
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
            total_count=total_count,
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
    total_count: int
