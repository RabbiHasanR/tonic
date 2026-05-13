from uuid import UUID

from sqlalchemy import func
from sqlmodel import Session, select
from strawberry.exceptions import GraphQLError

from app.core.security import hash_password, verify_password
from app.graphql.pagination import PageMeta, offset_paginate

from .models import User


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
        return user

    @staticmethod
    def get_user(session: Session, user_id: str) -> User:
        try:
            uid = UUID(user_id)
        except ValueError as exc:
            raise GraphQLError("User not found") from exc
        user = session.get(User, uid)
        if user is None:
            raise GraphQLError("User not found")
        return user
    

    @staticmethod
    def list_users_page(
        session: Session, page: int = 1, page_size: int = 20
    ) -> tuple[list[User], PageMeta]:
        base_stmt = select(User).order_by(User.created_at.desc())
        count_stmt = select(func.count()).select_from(User)
        return offset_paginate(session, base_stmt, count_stmt, page, page_size)