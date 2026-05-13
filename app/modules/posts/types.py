from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from app.modules.comments.types import Comment
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
        self, info: Info
    ) -> list[Annotated["Comment", strawberry.lazy("app.modules.comments.types")]]:
        from app.modules.comments.service import CommentService
        from app.modules.comments.types import Comment

        rows = CommentService.list_by_post(info.context.session, str(self.id))
        return [Comment.from_model(r) for r in rows]


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
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str] = None
    end_cursor: Optional[str] = None


@strawberry.type
class PostEdge:
    cursor: str
    node: Post


@strawberry.type
class PostConnection:
    edges: list[PostEdge]
    page_info: PageInfo
    total_count: int
