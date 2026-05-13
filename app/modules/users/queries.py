from typing import Optional

import strawberry
from strawberry.types import Info

from app.core.auth import require_user

from .service import UserService
from .types import User, UserPage


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

    @strawberry.field
    def users(self, info: Info, page: int = 1, page_size: int = 20) -> UserPage:
        require_user(info)
        rows, meta = UserService.list_users_page(
            info.context.session, page=page, page_size=page_size
        )
        return UserPage(items=[User.from_model(r) for r in rows], page_info=meta)
        
