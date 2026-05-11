from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Comment(SQLModel, table=True):
    __tablename__ = "comments"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    post_id: UUID = Field(
        sa_column=Column(
            PG_UUID(as_uuid=True),
            ForeignKey("posts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    author_id: UUID = Field(foreign_key="users.id", index=True, nullable=False)
    body: str
    created_at: datetime = Field(default_factory=_utcnow, nullable=False, index=True)
    updated_at: datetime = Field(
        default_factory=_utcnow,
        nullable=False,
        sa_column_kwargs={"onupdate": _utcnow},
    )
