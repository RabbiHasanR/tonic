import strawberry
from strawberry.types import Info

from app.core.security import create_access_token

from .service import UserService
from .types import AuthPayload, LoginInput, RegisterInput, User


@strawberry.type
class UsersMutation:
    @strawberry.mutation
    def register(self, info: Info, input: RegisterInput) -> AuthPayload:
        user = UserService.register(
            info.context.session,
            email=input.email,
            password=input.password,
            display_name=input.display_name,
        )
        return AuthPayload(token=create_access_token(str(user.id)), user=User.from_model(user))

    @strawberry.mutation
    def login(self, info: Info, input: LoginInput) -> AuthPayload:
        user = UserService.authenticate(info.context.session, input.email, input.password)
        return AuthPayload(token=create_access_token(str(user.id)), user=User.from_model(user))
