from datetime import datetime
from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from app.core.cache import cache_delete, cache_get, cache_set
from app.core.security import hash_password, verify_password
from app.graphql.pagination import PageMeta, offset_paginate

from .models import User

USER_CACHE_TTL = 600


def _user_cache_key(user_id: str) -> str:
    return f"user:{user_id}"


def _serialize_user(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "password_hash": u.password_hash,
        "display_name": u.display_name,
        "created_at": u.created_at.isoformat(),
        "updated_at": u.updated_at.isoformat() if u.updated_at else None,
    }


def _deserialize_user(d: dict) -> User:
    return User(
        id=UUID(d["id"]),
        email=d["email"],
        password_hash=d["password_hash"],
        display_name=d["display_name"],
        created_at=datetime.fromisoformat(d["created_at"]),
        updated_at=datetime.fromisoformat(d["updated_at"]) if d["updated_at"] else None,
    )


class UserService:
    @staticmethod
    def register(session: Session, email: str, password: str, display_name: str) -> User:
        email = email.strip().lower()
        if not email or "@" not in email:
            raise GraphQLError("Invalid email")
        if len(password) < 8:
            raise GraphQLError("Password must be at least 8 characters")
        if not display_name.strip():
            raise GraphQLError("Display name is required")

        existing = session.exec(select(User).where(User.email == email)).first()
        if existing is not None:
            raise GraphQLError("Email already registered")

        user = User(
            email=email,
            password_hash=hash_password(password),
            display_name=display_name.strip(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        cache_set(
            _user_cache_key(str(user.id)), _serialize_user(user), ttl=USER_CACHE_TTL
        )
        return user

    @staticmethod
    def authenticate(session: Session, email: str, password: str) -> User:
        email = email.strip().lower()
        user = session.exec(select(User).where(User.email == email)).first()
        if user is None or not verify_password(password, user.password_hash):
            raise GraphQLError("Invalid email or password")
        return user

    @staticmethod
    def update_profile(
        session: Session, user: User, display_name: str | None
    ) -> User:
        if display_name is not None:
            if not display_name.strip():
                raise GraphQLError("Display name cannot be empty")
            user.display_name = display_name.strip()
        session.add(user)
        session.commit()
        session.refresh(user)
        cache_delete(_user_cache_key(str(user.id)))
        return user

    @staticmethod
    def get_user(session: Session, user_id: str) -> User:
        try:
            uid = UUID(user_id)
        except ValueError as exc:
            raise GraphQLError("User not found") from exc

        cached = cache_get(_user_cache_key(user_id))
        if cached is not None:
            return _deserialize_user(cached)

        user = session.get(User, uid)
        if user is None:
            raise GraphQLError("User not found")

        cache_set(_user_cache_key(user_id), _serialize_user(user), ttl=USER_CACHE_TTL)
        return user

    @staticmethod
    def get_users_by_ids(session: Session, user_ids: list[str]) -> dict[str, User]:
        """Batch fetch. Returns map of str(id) -> User. Invalid ids silently dropped."""
        valid: list[UUID] = []
        for raw in user_ids:
            try:
                valid.append(UUID(raw))
            except ValueError:
                continue
        if not valid:
            return {}
        rows = session.exec(select(User).where(User.id.in_(valid))).all()
        return {str(r.id): r for r in rows}


    @staticmethod
    def list_users_page(
        session: Session, page: int = 1, page_size: int = 20
    ) -> tuple[list[User], PageMeta]:
        base_stmt = select(User).order_by(User.created_at.desc())
        count_stmt = select(func.count()).select_from(User)
        return offset_paginate(session, base_stmt, count_stmt, page, page_size)