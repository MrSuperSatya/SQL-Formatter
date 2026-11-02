"""Render expressions, clauses, and statements in the house SQL style."""

from __future__ import annotations

from dataclasses import dataclass

from sqlparse import tokens as T

from ._syntax import (
    _APPLY,
    _CLAUSES,
    _HEADERS,
    _INDENT,
    _LEADING,
    _LOCKING,
    _PAREN_SPACE,
    _PREDICATE_CLAUSES,
    _QUERY_KEYS,
    _SETS,
)
from ._tokens import (
    _Group,
    _Node,
    _Token,
    _first,
    _is_comment,
    _is_distinct_from,
    _is_semicolon,
    _key,
)


class _Writer:
    def __init__(self) -> None:
        self.parts: list[str] = []
        self.at_start = True

    def write(self, text: str, level: int, space: bool = True) -> None:
        if not text:
            return
        if self.at_start:
            self.parts.append(_INDENT * level)
        elif space:
            self.parts.append(" ")
        self.parts.append(text)
        self.at_start = text.endswith(("\n", "\r"))

    def newline(self, blank: bool = False) -> None:
        if not self.at_start:
            self.parts.append("\n")
        if blank:
            self.parts.append("\n")
        self.at_start = True


def _space_between(previous: _Node, node: _Node) -> bool:
    """Whether a space separates `previous` from `node` on one line."""
    prev = previous.closing if isinstance(previous, _Group) else previous
    curr = node.opening if isinstance(node, _Group) else node
    a, b = prev.raw, curr.raw
    if b in {",", ";", ".", ")", "]", "::", ":"} or a in {".", "[", "::", ":"}:
        return False
    if isinstance(node, _Group):
        if node.is_query or isinstance(previous, _Group):
            return True
        if prev.key in _PAREN_SPACE or "JOIN" in prev.key:
            return True
        if prev.kind in T.Name or prev.kind in T.Keyword:
            return False  # function calls: SUM(x), COALESCE(x, y)
        return a != "("
    if b == "[":
        return bool(curr.gap)
    # Preserve literal prefixes (N'...', E'...', U&'...', _utf8'...'),
    # parameters (@x, @@ROWCOUNT), and adjacent vendor-specific operators.
    if not curr.gap and (
        (curr.kind in T.Literal.String and (prev.kind in T.Name or a == "&"))
        or a in {"@", "@@", ":", "$"}
        or (b == "&" and a.upper() == "U")
    ):
        return False
    return True


@dataclass
class _Clause:
    name: str  # e.g. "FROM", "GROUP BY"; "" for text before the first clause
    header: list[_Node]
    body: list[_Node]


def _clause_at(items: list[_Node], index: int, first_clause: bool) -> tuple[str, int] | None:
    """If a clause heading starts at `index`, return (name, number of header tokens)."""
    node = items[index]
    if not isinstance(node, _Token) or not node.key:
        return None
    if _is_distinct_from(items, index):
        return None
    key = node.key
    pair = f"{key} {_key(items[index + 1]) if index + 1 < len(items) else ''}"
    if pair in _HEADERS or pair in _LOCKING:
        return pair, 2
    if key in _CLAUSES or key in _SETS:
        return key, 1
    if first_clause and key in _LEADING:
        return key, 1
    return None


def _split_clauses(items: list[_Node]) -> list[_Clause]:
    # CASE expressions have their own scope; clause words inside them must not
    # start an outer clause.
    clauses: list[_Clause] = []
    current = _Clause("", [], [])
    case_depth = 0
    i = 0
    while i < len(items):
        key = _key(items[i])
        if key == "CASE":
            case_depth += 1
        elif key == "END":
            case_depth = max(0, case_depth - 1)
        match = _clause_at(items, i, first_clause=not current.name) if case_depth == 0 else None
        if match:
            if current.header or current.body:
                clauses.append(current)
            name, size = match
            current = _Clause(name, items[i:i + size], [])
            i += size
        else:
            current.body.append(items[i])
            i += 1
    if current.header or current.body:
        clauses.append(current)
    return clauses


class _Formatter:
    def __init__(self, keyword_case: str) -> None:
        self.out = _Writer()
        self.keyword_case = keyword_case

    def spelling(self, node: _Token, next_node: _Node | None = None) -> str:
        if node.kind not in T.Keyword:
            return node.raw
        # Some function names are classified as keywords by the lexer.
        if (isinstance(next_node, _Group) and node.key not in _PAREN_SPACE
                and node.key not in _HEADERS and "JOIN" not in node.key):
            return node.raw
        value = " ".join(node.raw.split())
        if self.keyword_case == "preserve":
            return value
        return value.lower() if self.keyword_case == "lower" else value.upper()

    def write_comment(self, node: _Token, level: int) -> None:
        # Keep a comment that originally occupied its own line there.
        if node.after_break:
            self.out.newline()
        self.out.write(node.raw, level)
        if node.kind in T.Comment.Single or "\n" in node.raw:
            self.out.newline()

    def expression(self, items: list[_Node], level: int, *, joins: bool = False,
                   predicates: bool = False, ctes: bool = False,
                   first_space: bool = True) -> None:
        previous: _Node | None = None
        case_depth = 0
        between = False
        for i, node in enumerate(items):
            key = _key(node)
            if key == "CASE":
                case_depth += 1
            elif key == "END":
                case_depth = max(0, case_depth - 1)
            if _is_comment(node):
                self.write_comment(node, level)
                previous = node
                continue
            # Comments do not change whether a keyword is used as a function.
            next_index = i + 1
            while next_index < len(items) and _is_comment(items[next_index]):
                next_index += 1
            following = items[next_index] if next_index < len(items) else None
            if case_depth == 0:
                if joins and ("JOIN" in key.split() or key in _APPLY):
                    self.out.newline()
                if predicates:
                    if key == "BETWEEN":
                        between = True
                    elif key in {"AND", "OR"}:
                        if key == "AND" and between:
                            between = False
                        else:
                            self.out.newline()
            # PostgreSQL concatenates adjacent string literals across a newline.
            # That newline is significant; do not replace it with a space.
            if (isinstance(previous, _Token) and isinstance(node, _Token)
                    and previous.kind in T.Literal.String
                    and node.kind in T.Literal.String and node.after_break):
                self.out.newline()
            space = first_space if previous is None else _space_between(previous, node)
            if isinstance(node, _Group):
                self.write_group(node, level, space)
            else:
                self.out.write(self.spelling(node, following), level, space)
            if ctes and isinstance(node, _Token) and node.raw == ",":
                self.out.newline()
            previous = node

    def write_group(self, group: _Group, level: int, space: bool) -> None:
        self.out.write("(", level, space)
        if group.is_query:
            self.out.newline()
            self.statement(group.items, level + 1, nested=True)
            self.out.newline()
        else:
            self.expression(group.items, level, first_space=False)
        self.out.write(")", level, False)

    def statement(self, items: list[_Node], level: int = 0, *, nested: bool = False) -> None:
        first = _first(items)
        if not isinstance(first, _Token) or first.key not in _QUERY_KEYS:
            self.expression(items, level)
            return

        for clause in _split_clauses(items):
            self.out.newline()
            if not clause.header:
                self.expression(clause.body, level)
                continue
            self.expression(clause.header, level)
            if not clause.body:
                continue
            leading = _first(clause.body)
            derived = isinstance(leading, _Group) and leading.is_query
            expanded = not nested or (clause.name == "FROM" and derived) or clause.name == "WITH"
            body_level = level + 1 if expanded else level
            if expanded:
                self.out.newline()
            self.expression(clause.body, body_level,
                            joins=clause.name == "FROM",
                            predicates=clause.name in _PREDICATE_CLAUSES,
                            ctes=clause.name == "WITH")


def _render(items: list[_Node], keyword_case: str) -> tuple[str, int]:
    """Lay out terminated statements; returns the text and terminators added."""
    renderer = _Formatter(keyword_case)
    statement: list[_Node] = []
    added = 0
    i = 0
    while i < len(items):
        node = items[i]
        i += 1
        if not _is_semicolon(node):
            statement.append(node)
            continue
        renderer.statement(statement)
        renderer.out.write(";", 0, False)
        statement = []
        # An inline comment after a terminator belongs to that statement.
        while i < len(items) and _is_comment(items[i]) and not items[i].after_break:
            renderer.write_comment(items[i], 0)
            i += 1
        if i < len(items):
            renderer.out.newline(blank=True)
    if statement:
        renderer.statement(statement)
        if any(not _is_comment(n) for n in statement):
            renderer.out.write(";", 0, False)
            added = 1
    return "".join(renderer.out.parts).rstrip("\r\n") + "\n", added
