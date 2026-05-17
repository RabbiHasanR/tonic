from typing import Annotated, Optional
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlmodel import Session
from strawberry.fastapi import BaseContext

from app.core.database import get_session
from app.core.security import decode_access_token
from app.graphql.loaders import Loaders
from app.modules.users.models import User


class Context(BaseContext):
    """Per-request GraphQL context. Resolvers access session via `info.context.session`,
    the authenticated user via `info.context.user`, and per-request DataLoaders
    via `info.context.loaders`. `client_key` identifies the caller for rate
    limiting: `u:{user_id}` if authed, else `ip:{client_ip}`."""

    def __init__(
        self,
        session: Session,
        user: Optional[User] = None,
        client_key: str = "ip:unknown",
    ):
        super().__init__()
        self.session = session
        self.user = user
        self.client_key = client_key
        self.loaders = Loaders.for_session(session)


def _resolve_user(request: Request, session: Session) -> Optional[User]:
    auth = request.headers.get("Authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return session.get(User, UUID(sub))
    except ValueError:
        return None


def _client_key(request: Request, user: Optional[User]) -> str:
    if user is not None:
        return f"u:{user.id}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"


async def get_context(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Context:
    user = _resolve_user(request, session)
    return Context(
        session=session,
        user=user,
        client_key=_client_key(request, user),
    )
