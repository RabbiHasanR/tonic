"""Static GraphQL query complexity estimator.

Walks the parsed AST with `TypeInfo` so we know each field's return type
(scalar / object / list). List fields multiply child cost by their
requested size — `first` / `last` / `limit` / `pageSize` — falling back
to `settings.MAX_PAGE_SIZE` when no size argument is provided.

Mutations get a flat per-field cost (`settings.MUTATION_FLAT_COST`) —
writes rarely nest deeply enough for multiplicative scoring to matter.

The score is then fed to the rate limiter as the request's "cost".
"""

from typing import Any

from graphql import (
    DocumentNode,
    FieldNode,
    FragmentDefinitionNode,
    FragmentSpreadNode,
    GraphQLList,
    GraphQLNonNull,
    GraphQLSchema,
    InlineFragmentNode,
    OperationDefinitionNode,
    OperationType,
    SelectionSetNode,
    TypeInfo,
    get_named_type,
)

from app.core.config import settings

_SIZE_ARG_NAMES = ("first", "last", "limit", "page_size", "pageSize")


def _is_list_type(t: Any) -> bool:
    """True if the type (after unwrapping NonNull) is a List."""
    if t is None:
        return False
    if isinstance(t, GraphQLNonNull):
        t = t.of_type
    return isinstance(t, GraphQLList)


def _resolve_size_arg(field: FieldNode, variables: dict) -> int | None:
    """Return the requested list size from a recognized arg, or None."""
    for arg in field.arguments or []:
        if arg.name.value not in _SIZE_ARG_NAMES:
            continue
        val = arg.value
        if val.kind == "int_value":
            try:
                return int(val.value)
            except ValueError:
                return None
        if val.kind == "variable":
            v = variables.get(val.name.value)
            if isinstance(v, int):
                return v
    return None


def _walk_selection_set(
    selection_set: SelectionSetNode,
    type_info: TypeInfo,
    fragments: dict[str, FragmentDefinitionNode],
    variables: dict,
) -> int:
    total = 0
    for sel in selection_set.selections:
        if isinstance(sel, FieldNode):
            type_info.enter(sel)
            try:
                field_type = type_info.get_type()
                explicit_size = _resolve_size_arg(sel, variables)
                # A field is "sized" if it has a recognized pagination arg
                # (covers Relay connections whose return type is not a list)
                # OR its return type is a GraphQLList.
                is_sized = explicit_size is not None or _is_list_type(field_type)
                if is_sized:
                    size = explicit_size or settings.MAX_PAGE_SIZE
                    child = (
                        _walk_selection_set(
                            sel.selection_set, type_info, fragments, variables
                        )
                        if sel.selection_set
                        else 1
                    )
                    total += size * max(1, child)
                else:
                    if sel.selection_set:
                        total += 1 + _walk_selection_set(
                            sel.selection_set, type_info, fragments, variables
                        )
                    else:
                        total += 1
            finally:
                type_info.leave(sel)
        elif isinstance(sel, InlineFragmentNode):
            type_info.enter(sel)
            try:
                if sel.selection_set:
                    total += _walk_selection_set(
                        sel.selection_set, type_info, fragments, variables
                    )
            finally:
                type_info.leave(sel)
        elif isinstance(sel, FragmentSpreadNode):
            frag = fragments.get(sel.name.value)
            if frag is None:
                continue
            type_info.enter(frag)
            try:
                total += _walk_selection_set(
                    frag.selection_set, type_info, fragments, variables
                )
            finally:
                type_info.leave(frag)
    return total


def estimate_complexity(
    schema: GraphQLSchema,
    document: DocumentNode,
    variables: dict | None,
    operation_name: str | None,
) -> int:
    """Compute the cost score for the given operation.

    Returns 0 if the operation cannot be found (let validation surface the
    real error — don't bill the client for our inability to locate it).
    """
    variables = variables or {}

    operation: OperationDefinitionNode | None = None
    fragments: dict[str, FragmentDefinitionNode] = {}
    for defn in document.definitions:
        if isinstance(defn, OperationDefinitionNode):
            if operation_name is None or (
                defn.name and defn.name.value == operation_name
            ):
                operation = defn
                if operation_name is None:
                    pass  # take the first/only one when not specified
        elif isinstance(defn, FragmentDefinitionNode):
            fragments[defn.name.value] = defn

    if operation is None:
        return 0

    if operation.operation == OperationType.MUTATION:
        # Flat cost per top-level mutation field. Nested object/list selections
        # in the response payload are not multiplied — mutation cost dominates.
        n = len(operation.selection_set.selections)
        return max(1, n) * settings.MUTATION_FLAT_COST

    type_info = TypeInfo(schema)
    # Prime TypeInfo with the operation so `get_type()` is valid on enter(field).
    type_info.enter(operation)
    try:
        return _walk_selection_set(
            operation.selection_set, type_info, fragments, variables
        )
    finally:
        type_info.leave(operation)


def get_named_type_name(t: Any) -> str | None:
    """Small helper for callers that want a debug-friendly type name."""
    nt = get_named_type(t) if t else None
    return nt.name if nt else None
