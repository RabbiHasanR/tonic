from datetime import datetime
from typing import TYPE_CHECKING, Annotated

import strawberry
from strawberry.types import Info

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
    def author(
        self, info: Info
    ) -> Annotated["User", strawberry.lazy("app.modules.users.types")]:
        from app.modules.users.service import UserService
        from app.modules.users.types import User

        row = UserService.get_user(info.context.session, self.author_id)
        return User.from_model(row)


@strawberry.input
class CommentCreateInput:
    post_id: strawberry.ID
    body: str
