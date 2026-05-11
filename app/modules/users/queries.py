from typing import Optional

import strawberry
from strawberry.types import Info

from .service import UserService
from .types import User


@strawberry.type
class UsersQuery:
    @strawberry.field
    def me(self, info: Info) -> Optional[User]:
        u = info.context.user
        return User.from_model(u) if u is not None else None

    @strawberry.field
    def user(self, info: Info, id: strawberry.ID) -> User:
        row = UserService.get_user(info.context.session, str(id))
        return User.from_model(row)
