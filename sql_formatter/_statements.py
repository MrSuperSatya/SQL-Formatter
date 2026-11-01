"""Validate supported scripts and separate their top-level SQL statements."""

from __future__ import annotations

from sqlparse import tokens as T

from ._syntax import (
    _BODY_KEYS,
    _CLIENT_DIRECTIVES,
    _CREATE_KEYS,
    _DML_KEYS,
    _PROCEDURAL_KEYS,
    _ROUTINE_KEYS,
    _SETS,
    _STATEMENT_KEYS,
)
from ._tokens import (
    _Group,
    _Node,
    _Token,
    _is_comment,
    _is_semicolon,
    _key,
    _own_line,
)


def _check_supported(tokens: list[_Token]) -> None:
    # Client commands and procedure bodies need dialect-aware statement splitting.
    # Reject instead of moving a meaningful line break or internal semicolon.
    for i, tok in enumerate(tokens):
        key = tok.key
        word = tok.raw.upper()
        at_start = _own_line(tokens, i)
        if at_start and word in _CLIENT_DIRECTIVES:
            raise ValueError(f"Client directive {word!r} is unsupported; format its SQL batches separately.")
        if key in _PROCEDURAL_KEYS or (key == "IF" and at_start):
            raise ValueError("Procedural SQL is unsupported; format individual SQL statements instead.")
        if key in _ROUTINE_KEYS and any(t.key in _CREATE_KEYS for t in tokens[max(0, i - 4):i]):
            raise ValueError("Stored routine definitions are unsupported.")


def _starts_statement(items: list[_Node], i: int, key: str, body: bool, prev: _Node | None) -> bool:
    """Whether the keyword at `i` begins a new, unterminated statement."""
    if key not in _STATEMENT_KEYS or (not body and key != "WITH"):
        return False
    following = (
        items[index]
        for index in range(i + 1, len(items))
        if not _is_comment(items[index])
    )
    if key == "WITH":
        name = next(following, None)
        if not isinstance(name, _Token):
            return False
        if not (name.key == "RECURSIVE" or name.kind in T.Name):
            return False
        definition = next(following, None)
        if not (
            isinstance(definition, _Group)
            or (isinstance(definition, _Token) and definition.key == "AS")
        ):
            return False
        return body
    if key == "INSERT" and isinstance(next(following, None), _Group):
        return False
    if _key(prev) in {"ALL", "DISTINCT"}:
        preceding = (
            items[index] for index in range(i - 1, -1, -1)
            if not _is_comment(items[index])
        )
        quantifier = _key(next(preceding, None))
        operator = _key(next(preceding, None))
        if f"{operator} {quantifier}" in _SETS:
            return False
    return _key(prev) not in _SETS and _key(prev) not in {"FOR", "DO", "KEY", "THEN"}


def _split_statements(items: list[_Node]) -> tuple[list[_Node], int]:
    """Insert a semicolon between statements that were not terminated."""
    result: list[_Node] = []
    inserted = 0
    first: str | None = None
    body = False
    prev: _Node | None = None
    for i, node in enumerate(items):
        if _is_semicolon(node):
            result.append(node)
            first, body, prev = None, False, None
            continue
        if _is_comment(node):
            result.append(node)
            continue
        key = _key(node)
        if first is None:
            first = key
            body = key in _BODY_KEYS
        elif first in _STATEMENT_KEYS and _starts_statement(items, i, key, body, prev):
            back = len(result)
            while back > 0 and _is_comment(result[back - 1]) and _own_line(result, back - 1):
                back -= 1
            result.insert(back, _Token(T.Punctuation, ";"))
            inserted += 1
            first = key
            body = key in _BODY_KEYS
        elif not body and first == "WITH" and key in _DML_KEYS:
            # An INSERT still needs its SELECT/VALUES body after the CTEs.
            first = key
            body = key in _BODY_KEYS
        elif not body and first == "INSERT" and key in {"SELECT", "VALUES", "SET"}:
            body = True
        prev = node
        result.append(node)
    return result, inserted
