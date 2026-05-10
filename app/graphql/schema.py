import strawberry

# Module Query/Mutation classes are merged in here as features are added.
# Until the first module exists, the schema needs at least one field on Query.
#
# Example after adding modules:
#
#     from strawberry.tools import merge_types
#     from app.modules.users.queries import UsersQuery
#     from app.modules.users.mutations import UsersMutation
#     Query = merge_types("Query", (_RootQuery, UsersQuery))
#     Mutation = merge_types("Mutation", (_RootMutation, UsersMutation))


@strawberry.type
class _RootQuery:
    @strawberry.field
    def ping(self) -> str:
        return "pong"


@strawberry.type
class _RootMutation:
    @strawberry.field
    def _placeholder(self) -> str:
        return "ok"


Query = _RootQuery
Mutation = _RootMutation

schema = strawberry.Schema(query=Query, mutation=Mutation)
