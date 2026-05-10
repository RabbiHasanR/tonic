from typing import Annotated
from fastapi import Depends
from sqlmodel import Session
from strawberry.fastapi import BaseContext
from app.core.database import get_session


class Context(BaseContext):
    """Per-request GraphQL context. Resolvers access session via `info.context.session`."""

    def __init__(self, session: Session):
        super().__init__()
        self.session = session


async def get_context(
    session: Annotated[Session, Depends(get_session)],
) -> Context:
    return Context(session=session)
