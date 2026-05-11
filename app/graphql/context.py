from typing import Annotated, Optional
from uuid import UUID

import jwt
from fastapi import Depends, Request
from sqlmodel import Session
from strawberry.fastapi import BaseContext

from app.core.database import get_session
from app.core.security import decode_access_token
from app.modules.users.models import User


class Context(BaseContext):
    """Per-request GraphQL context. Resolvers access session via `info.context.session`
    and the authenticated user (if any) via `info.context.user`."""

    def __init__(self, session: Session, user: Optional[User] = None):
        super().__init__()
        self.session = session
        self.user = user


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


async def get_context(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> Context:
    return Context(session=session, user=_resolve_user(request, session))
