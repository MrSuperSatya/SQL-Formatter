"""Normalize names and resolve table aliases within their query scopes."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlparse import lexer, tokens as T

from ._syntax import _APPLY, _DML_KEYS, _FROM_ENDERS, _SETS, _TABLE_NAME_PRECEDERS
from ._tokens import (
    _Group, _Node, _Token, _first, _flatten, _is_comment, _is_distinct_from,
    _is_semicolon, _key,
)


@dataclass
class _Binding:
    alias: _Token | None
    replace: bool = False
    implicit_schema: bool = False


@dataclass
class _Table:
    path: list[_Token]
    alias: _Token | None
    generate: bool = False
    opaque: bool = False


@dataclass
class _Scope:
    items: list[_Node]
    parent: _Scope | None
    preserve_qualifiers: bool = False
    tables: list[_Table] = field(default_factory=list)
    bindings: dict[tuple[str, ...], _Binding] = field(default_factory=dict)

    @property
    def root(self) -> _Scope:
        scope = self
        while scope.parent is not None:
            scope = scope.parent
        return scope


def _name_key(token: _Token) -> str:
    value = token.raw
    if token.is_quoted or token.kind in T.Literal.String.Single:
        value = value[1:-1]
    return value.upper()


def _query_scopes(items: list[_Node], parent: _Scope | None = None) -> list[_Scope]:
    """Separate statements, set operands, and nested queries."""
    scopes: list[_Scope] = []
    operands: list[_Scope] = []
    start = 0
    for index in range(len(items) + 1):
        if index < len(items) and not (
            _is_semicolon(items[index]) or _key(items[index]) in _SETS
        ):
            continue
        if start < index:
            scope = _Scope(items[start:index], parent)
            operands.append(scope)
            scopes.append(scope)
            scopes.extend(_child_scopes(scope.items, scope))
        if index == len(items) or _is_semicolon(items[index]):
            if len(operands) > 1 and _has_qualified_order(operands[-1].items):
                # Compound ORDER BY may refer to any operand's original names.
                # Keep those qualifications instead of choosing a branch's alias.
                for operand in operands:
                    operand.preserve_qualifiers = True
            operands = []
        start = index + 1
    return scopes


def _child_scopes(items: list[_Node], parent: _Scope | None) -> list[_Scope]:
    scopes: list[_Scope] = []
    in_cte = _key(_first(items)) == "WITH"
    for node in items:
        if _key(node) in _DML_KEYS:
            in_cte = False
        if isinstance(node, _Group):
            # CTE definitions can correlate with the enclosing query, but cannot
            # see FROM aliases belonging to the query that consumes the CTE.
            enclosing = parent.parent if in_cte and parent is not None else parent
            if node.is_query:
                scopes.extend(_query_scopes(node.items, enclosing))
            else:
                scopes.extend(_child_scopes(node.items, enclosing))
    return scopes


def _has_qualified_order(items: list[_Node]) -> bool:
    for index, node in enumerate(items):
        if _key(node) == "ORDER BY":
            return any(token.is_punct(".") for token in _flatten(items[index + 1:]))
    return False


def _scope_tokens(items: list[_Node]) -> list[_Token]:
    """Include expression groups while leaving nested query contents to their scope."""
    tokens: list[_Token] = []
    for node in items:
        if isinstance(node, _Token):
            if not _is_comment(node):
                tokens.append(node)
        else:
            tokens.append(node.opening)
            if not node.is_query:
                tokens.extend(_scope_tokens(node.items))
            tokens.append(node.closing)
    return tokens


def _alias_after(items: list[_Node], index: int) -> _Token | None:
    if index < len(items) and _key(items[index]) == "AS":
        index += 1
    if index < len(items):
        node = items[index]
        if isinstance(node, _Token) and (
            node.is_name or node.kind in T.Literal.String.Single
        ):
            node.alias = True
            return node
    return None


def _find_tables(items: list[_Node]) -> list[_Table]:
    nodes = [node for node in items if not _is_comment(node)]
    tables: list[_Table] = []
    in_from = selectable = expecting = False
    last_keyword = ""
    index = 0
    while index < len(nodes):
        node = nodes[index]
        key = _key(node)
        if _is_distinct_from(nodes, index):
            index += 1
            continue
        if key in {"FROM", "UPDATE", "INTO"} or key.endswith("JOIN") or key in _APPLY:
            in_from = expecting = True
            selectable = key not in {"UPDATE", "INTO"} and last_keyword != "DELETE"
        elif in_from and key in {"ON", "USING"}:
            # A join condition ends this table source, but a subsequent comma
            # still introduces another source in the same FROM list.
            expecting = False
        elif key in _FROM_ENDERS:
            in_from = expecting = False
        elif in_from and isinstance(node, _Token) and node.is_punct(","):
            expecting = True
        elif expecting and isinstance(node, _Group):
            tables.append(_Table(
                [], _alias_after(nodes, index + 1), opaque=not node.is_query
            ))
            expecting = False
        elif expecting and isinstance(node, _Token) and node.is_name:
            path = [node]
            index += 1
            while (
                index + 1 < len(nodes)
                and isinstance(nodes[index], _Token)
                and nodes[index].is_punct(".")
                and isinstance(nodes[index + 1], _Token)
                and nodes[index + 1].is_name
            ):
                path.append(nodes[index + 1])
                index += 2
            call = index < len(nodes) and isinstance(nodes[index], _Group)
            if call:
                index += 1
            alias = _alias_after(nodes, index)
            # Quoted table names keep their spelling and existing qualification.
            # Unknown keyword suffixes may be dialect-specific table hints.
            suffix = nodes[index] if index < len(nodes) else None
            safe_suffix = suffix is None or not _key(suffix) or _key(suffix) in (
                _FROM_ENDERS | {"FOR", "FOR UPDATE", "FOR SHARE"}
            ) or "JOIN" in _key(suffix)
            tables.append(_Table(
                path, alias,
                generate=selectable and not call and alias is None
                and not any(part.is_quoted for part in path) and safe_suffix,
            ))
            expecting = False
            continue
        if key:
            last_keyword = key
        index += 1
    return tables


def _unique_alias(table: str, taken: set[str]) -> str:
    base = "".join(part[0] for part in table.split("_") if part) or "T"
    alias, number = base, 0
    while alias in taken or next(iter(lexer.tokenize(alias)))[0] in T.Keyword:
        number += 1
        alias = f"{base}{number}"
    taken.add(alias)
    return alias.lower()


def _bind_tables(scopes: list[_Scope]) -> dict[int, _Token]:
    taken = {
        _name_key(table.alias)
        for scope in scopes for table in scope.tables if table.alias is not None
    }
    generated: dict[tuple[str, ...], str] = {}
    insertions: dict[int, _Token] = {}
    for scope in scopes:
        used: set[str] = set()
        for table in scope.tables:
            path = tuple(_name_key(part) for part in table.path)
            if table.generate:
                alias = generated.get(path)
                if alias is None or alias in used:
                    alias = _unique_alias(table.path[-1].raw.upper(), taken)
                    generated.setdefault(path, alias)
                used.add(alias)
                table.alias = _Token(T.Name, alias, " ", alias=True)
                insertions[id(table.path[-1])] = table.alias
            if table.alias is not None:
                scope.bindings[(_name_key(table.alias),)] = _Binding(table.alias)
            if path and (table.alias is None or table.generate):
                binding = _Binding(table.alias, table.generate, len(path) == 1)
                scope.bindings[path] = binding
                scope.bindings[(path[-1],)] = binding
    return insertions


def _resolve(scope: _Scope, parts: list[_Token]) -> tuple[_Binding, int] | None:
    qualifier = tuple(_name_key(part) for part in parts[:-1])
    scopes: list[_Scope] = []
    current: _Scope | None = scope
    while current is not None:
        scopes.append(current)
        current = current.parent

    # A complete schema.table match in an enclosing query takes precedence over
    # a local table with the same last name or an alias named after the schema.
    for current in scopes:
        binding = current.bindings.get(qualifier)
        if binding is not None:
            return binding, len(qualifier)
    for current in scopes:
        # An unqualified FROM table may still be referenced as schema.table.column.
        binding = current.bindings.get((qualifier[-1],))
        if binding is not None and binding.implicit_schema:
            return binding, len(qualifier)
    # Retain support for qualified fields such as alias.column.field.
    for size in range(len(qualifier) - 1, 0, -1):
        for current in scopes:
            binding = current.bindings.get(qualifier[:size])
            if binding is not None:
                return binding, size
    return None


def _rewrite_references(scope: _Scope, tokens: list[_Token]) -> set[int]:
    declarations = {id(part) for table in scope.tables for part in table.path}
    removed: set[int] = set()
    index = 0
    while index < len(tokens):
        if not tokens[index].is_name:
            index += 1
            continue
        parts = [tokens[index]]
        dots: list[_Token] = []
        end = index + 1
        while end + 1 < len(tokens) and tokens[end].is_punct(".") and (
            tokens[end + 1].is_name or tokens[end + 1].raw == "*"
        ):
            dots.append(tokens[end])
            parts.append(tokens[end + 1])
            end += 2
        if len(parts) > 1 and not any(id(part) in declarations for part in parts):
            is_call = end < len(tokens) and tokens[end].is_punct("(")
            match = None if is_call else _resolve(scope, parts)
            if match is not None:
                binding, size = match
                if binding.replace and binding.alias is not None:
                    parts[0].raw = binding.alias.raw
                    parts[0].kind = T.Name
                    parts[0].alias = True
                    removed.update(id(part) for part in parts[1:size])
                    removed.update(id(dot) for dot in dots[:size - 1])
                elif binding.alias is not None:
                    parts[0].alias = True
        index = end
    return removed


def _normalize_names(tokens: list[_Token]) -> None:
    for index, token in enumerate(tokens):
        if not token.is_name or token.is_quoted:
            continue
        previous = tokens[index - 1] if index else None
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if token.alias:
            token.raw = token.raw.lower()
        elif token.raw[0] in "@:$#?%" or (
            previous is not None and previous.raw in {"@", "@@", ":", "$"}
        ):
            continue
        elif following is not None and (
            (following.is_punct("(") and not (
                previous is not None and previous.last_word in _TABLE_NAME_PRECEDERS
            )) or (following.kind in T.Literal.String and not following.gap)
        ):
            continue
        else:
            token.raw = token.raw.upper()


def _normalize_identifiers(items: list[_Node]) -> list[_Token]:
    scopes = _query_scopes(items)
    for scope in scopes:
        scope.tables = _find_tables(scope.items)
    # Parenthesized table sources and compound ordering have dialect-specific
    # visibility. Preserve their query's qualifications, including correlated names.
    preserved_roots = {
        id(scope.root) for scope in scopes
        if scope.preserve_qualifiers or any(table.opaque for table in scope.tables)
    }
    for scope in scopes:
        if id(scope.root) in preserved_roots:
            for table in scope.tables:
                table.generate = False
    insertions = _bind_tables(scopes)
    removed: set[int] = set()
    for scope in scopes:
        tokens = _scope_tokens(scope.items)
        removed.update(_rewrite_references(scope, tokens))
        _normalize_names(tokens)
    result: list[_Token] = []
    for token in _flatten(items):
        if id(token) not in removed:
            result.append(token)
        alias = insertions.get(id(token))
        if alias is not None:
            result.append(alias)
    return result
