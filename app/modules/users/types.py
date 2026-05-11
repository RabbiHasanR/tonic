from datetime import datetime
from typing import TYPE_CHECKING, Annotated

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from app.modules.posts.types import Post


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
        self, info: Info
    ) -> list[Annotated["Post", strawberry.lazy("app.modules.posts.types")]]:
        from app.modules.posts.service import PostService
        from app.modules.posts.types import Post

        rows = PostService.list_by_author(info.context.session, str(self.id))
        return [Post.from_model(r) for r in rows]


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
