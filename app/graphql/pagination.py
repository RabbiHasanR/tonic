import base64
import json
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

import strawberry
from sqlalchemy import tuple_
from sqlmodel import Session
from strawberry.exceptions import GraphQLError

Direction = Literal["asc", "desc"]


@strawberry.type
class PageInfo:
    has_next_page: bool
    has_previous_page: bool
    start_cursor: Optional[str] = None
    end_cursor: Optional[str] = None


def encode_cursor(created_at: datetime, row_id: UUID) -> str:
    payload = json.dumps({"c": created_at.isoformat(), "id": str(row_id)})
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        return datetime.fromisoformat(payload["c"]), UUID(payload["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise GraphQLError("Invalid cursor") from exc


def paginate(
    session: Session,
    base_stmt,
    count_stmt,
    sort_col,
    id_col,
    first: int | None,
    after: str | None,
    last: int | None,
    before: str | None,
    direction: Direction = "desc",
    default_limit: int = 20,
    max_limit: int = 100,
) -> tuple[list, bool, bool, int]:
    """Relay cursor pagination over a (sort_col, id_col) composite key.

    `direction` is the natural reading order for forward pagination (`first`):
    - "desc": newest first (e.g. feeds)
    - "asc":  oldest first (e.g. comment threads)
    """
    if first is not None and last is not None:
        raise GraphQLError("Pass either `first` or `last`, not both")
    if after is not None and before is not None:
        raise GraphQLError("Pass either `after` or `before`, not both")
    if last is not None and after is not None:
        raise GraphQLError("`after` can only be combined with `first`")
    if first is not None and before is not None:
        raise GraphQLError("`before` can only be combined with `last`")

    backward = last is not None or before is not None
    composite = tuple_(sort_col, id_col)

    if not backward:
        limit = max(1, min(first if first is not None else default_limit, max_limit))
        if direction == "desc":
            stmt = base_stmt.order_by(sort_col.desc(), id_col.desc())
            if after is not None:
                c_at, c_id = decode_cursor(after)
                stmt = stmt.where(composite < (c_at, c_id))
        else:
            stmt = base_stmt.order_by(sort_col.asc(), id_col.asc())
            if after is not None:
                c_at, c_id = decode_cursor(after)
                stmt = stmt.where(composite > (c_at, c_id))
        rows = list(session.exec(stmt.limit(limit + 1)).all())
        has_next_page = len(rows) > limit
        nodes = rows[:limit] if has_next_page else rows
        has_previous_page = after is not None
    else:
        limit = max(1, min(last if last is not None else default_limit, max_limit))
        if direction == "desc":
            stmt = base_stmt.order_by(sort_col.asc(), id_col.asc())
            if before is not None:
                c_at, c_id = decode_cursor(before)
                stmt = stmt.where(composite > (c_at, c_id))
        else:
            stmt = base_stmt.order_by(sort_col.desc(), id_col.desc())
            if before is not None:
                c_at, c_id = decode_cursor(before)
                stmt = stmt.where(composite < (c_at, c_id))
        rows = list(session.exec(stmt.limit(limit + 1)).all())
        has_previous_page = len(rows) > limit
        nodes = rows[:limit] if has_previous_page else rows
        nodes.reverse()
        has_next_page = before is not None

    total_count = int(session.exec(count_stmt).one())
    return nodes, has_next_page, has_previous_page, total_count
