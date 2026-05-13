from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Optional

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from app.modules.posts.types import PostConnection


@strawberry.type
class User:
    id: strawberry.ID
    email: str
    display_name: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, m) -> "User":
        return cls(
            id=strawberry.ID(str(m.id)),
            email=m.email,
            display_name=m.display_name,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    @strawberry.field
    def posts(
        self,
        info: Info,
        first: Optional[int] = None,
        after: Optional[str] = None,
        last: Optional[int] = None,
        before: Optional[str] = None,
    ) -> Annotated["PostConnection", strawberry.lazy("app.modules.posts.types")]:
        from app.graphql.pagination import PageInfo
        from app.modules.posts.service import PostService
        from app.modules.posts.types import Post, PostConnection, PostEdge

        nodes, has_next_page, has_previous_page, total_count = (
            PostService.list_by_author_connection(
                info.context.session,
                author_id=str(self.id),
                first=first,
                after=after,
                last=last,
                before=before,
            )
        )
        edges = [
            PostEdge(cursor=PostService.encode_cursor(row), node=Post.from_model(row))
            for row in nodes
        ]
        return PostConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_next_page,
                has_previous_page=has_previous_page,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            total_count=total_count,
        )


@strawberry.type
class UserPage:
    items: list[User]
    page_info: "PageMeta"


from app.graphql.pagination import PageMeta  # noqa: E402


@strawberry.type
class AuthPayload:
    token: str
    user: User


@strawberry.input
class RegisterInput:
    email: str
    password: str
    display_name: str


@strawberry.input
class LoginInput:
    email: str
    password: str


@strawberry.input
class UpdateProfileInput:
    display_name: Optional[str] = None
