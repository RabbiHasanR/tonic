import strawberry
from strawberry.types import Info

from .service import PostService
from .types import PageInfo, Post, PostConnection, PostEdge


@strawberry.type
class PostsQuery:
    @strawberry.field
    def posts(
        self,
        info: Info,
        first: int | None = None,
        after: str | None = None,
        last: int | None = None,
        before: str | None = None,
    ) -> PostConnection:
        nodes, has_next_page, has_previous_page, total_count = (
            PostService.list_posts_connection(
                info.context.session,
                first=first,
                after=after,
                last=last,
                before=before,
            )
        )
        edges = [
            PostEdge(cursor=PostService.encode_cursor(row), node=Post.from_model(row))
            for row in nodes
        ]
        return PostConnection(
            edges=edges,
            page_info=PageInfo(
                has_next_page=has_next_page,
                has_previous_page=has_previous_page,
                start_cursor=edges[0].cursor if edges else None,
                end_cursor=edges[-1].cursor if edges else None,
            ),
            total_count=total_count,
        )

    @strawberry.field
    def post(self, info: Info, id: strawberry.ID) -> Post:
        row = PostService.get_post(info.context.session, str(id))
        return Post.from_model(row)
