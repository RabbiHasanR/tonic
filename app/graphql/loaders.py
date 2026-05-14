"""Per-request DataLoaders used by GraphQL resolvers to batch N+1 SQL.

Each `make_*` factory captures the request `Session` and returns a fresh
`DataLoader`. Loaders MUST NOT be reused across requests — they cache results
within their lifetime and would otherwise leak stale data between users.

Wiring: `app.graphql.context.get_context` constructs a `Loaders` container
per request and attaches it to the `Context`.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from sqlmodel import Session
from strawberry.dataloader import DataLoader

from app.modules.comments.service import CommentService
from app.modules.posts.service import PostService
from app.modules.users.models import User
from app.modules.users.service import UserService


# --- User by id -------------------------------------------------------------

def make_user_by_id_loader(session: Session) -> DataLoader:
    async def load(keys: list[str]) -> list[Optional[User]]:
        by_id = UserService.get_users_by_ids(session, list(keys))
        return [by_id.get(k) for k in keys]

    return DataLoader(load_fn=load)


# --- Posts by author (window-function batched) ------------------------------
# Key shape: (author_id, limit). Grouped by `limit` so each distinct page size
# in a tick becomes one SQL query. Returns (nodes, has_next_page).

def make_posts_by_author_loader(session: Session) -> DataLoader:
    async def load(
        keys: list[tuple[str, int]],
    ) -> list[tuple[list, bool]]:
        groups: dict[int, list[str]] = defaultdict(list)
        for author_id, limit in keys:
            groups[limit].append(author_id)
        merged: dict[tuple[str, int], tuple[list, bool]] = {}
        for limit, ids in groups.items():
            batch = PostService.batch_first_page_by_authors(session, ids, limit)
            for aid, value in batch.items():
                merged[(aid, limit)] = value
        return [merged.get(k, ([], False)) for k in keys]

    return DataLoader(load_fn=load)


# --- Comments by post (window-function batched) -----------------------------

def make_comments_by_post_loader(session: Session) -> DataLoader:
    async def load(
        keys: list[tuple[str, int]],
    ) -> list[tuple[list, bool]]:
        groups: dict[int, list[str]] = defaultdict(list)
        for post_id, limit in keys:
            groups[limit].append(post_id)
        merged: dict[tuple[str, int], tuple[list, bool]] = {}
        for limit, ids in groups.items():
            batch = CommentService.batch_first_page_by_posts(session, ids, limit)
            for pid, value in batch.items():
                merged[(pid, limit)] = value
        return [merged.get(k, ([], False)) for k in keys]

    return DataLoader(load_fn=load)


# --- Counts (option 5: batched GROUP BY) ------------------------------------

def make_post_count_by_author_loader(session: Session) -> DataLoader:
    async def load(keys: list[str]) -> list[int]:
        counts = PostService.count_by_authors(session, list(keys))
        return [counts.get(k, 0) for k in keys]

    return DataLoader(load_fn=load)


def make_comment_count_by_post_loader(session: Session) -> DataLoader:
    async def load(keys: list[str]) -> list[int]:
        counts = CommentService.count_by_posts(session, list(keys))
        return [counts.get(k, 0) for k in keys]

    return DataLoader(load_fn=load)


# --- Container --------------------------------------------------------------

@dataclass
class Loaders:
    user_by_id: DataLoader
    posts_by_author: DataLoader
    comments_by_post: DataLoader
    post_count_by_author: DataLoader
    comment_count_by_post: DataLoader

    @classmethod
    def for_session(cls, session: Session) -> "Loaders":
        return cls(
            user_by_id=make_user_by_id_loader(session),
            posts_by_author=make_posts_by_author_loader(session),
            comments_by_post=make_comments_by_post_loader(session),
            post_count_by_author=make_post_count_by_author_loader(session),
            comment_count_by_post=make_comment_count_by_post_loader(session),
        )

    def invalidate_post_comments(self, post_id: str) -> None:
        # comments_by_post is keyed by (post_id, limit); we don't track which
        # limits are cached, so drop the whole connection cache.
        self.comments_by_post.clear_all()
        _safe_clear(self.comment_count_by_post, post_id)

    def invalidate_user(self, user_id: str) -> None:
        _safe_clear(self.user_by_id, user_id)

    def invalidate_author_posts(self, author_id: str) -> None:
        self.posts_by_author.clear_all()
        _safe_clear(self.post_count_by_author, author_id)


def _safe_clear(loader: DataLoader, key) -> None:
    # strawberry's DataLoader.clear raises KeyError when the key isn't cached
    # (unlike the JS reference impl). Make it a no-op so invalidation is safe
    # to call even when the loader was never touched in this request.
    try:
        loader.clear(key)
    except KeyError:
        pass
