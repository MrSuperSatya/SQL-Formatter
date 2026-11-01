"""Tokenize SQL, normalize identifiers, and build the parenthesis tree."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Union

try:
    from sqlparse import lexer, tokens as T
except ImportError as exc:
    raise ImportError("Install the dependency: python -m pip install sqlparse") from exc

from ._syntax import (
    _CALL_LIKE_KEYWORDS,
    _FROM_ENDERS,
    _MAX_NESTING,
    _QUERY_KEYS,
    _TABLE_NAME_PRECEDERS,
)


@dataclass
class _Token:
    kind: Any  # sqlparse token type
    raw: str
    gap: str = ""  # whitespace that preceded the token in the source
    alias: bool = False  # table alias, or a name that qualifies one

    @property
    def key(self) -> str:
        """Upper-cased, whitespace-normalized keyword text ('' for non-keywords)."""
        return " ".join(self.raw.upper().split()) if self.kind in T.Keyword else ""

    @property
    def last_word(self) -> str:
        return self.key.rsplit(" ", 1)[-1]

    @property
    def after_break(self) -> bool:
        return "\n" in self.gap or "\r" in self.gap

    @property
    def is_name(self) -> bool:
        """An identifier, excluding placeholders such as ? or :param."""
        return self.kind in T.Name and self.kind not in T.Name.Placeholder

    def is_punct(self, value: str) -> bool:
        return self.kind in T.Punctuation and self.raw == value


@dataclass
class _Group:
    opening: _Token
    items: list[_Node]
    closing: _Token

    @property
    def is_query(self) -> bool:
        first = _first(self.items)
        return isinstance(first, _Token) and first.key in _QUERY_KEYS


_Node = Union[_Token, _Group]


def _is_comment(node: _Node | None) -> bool:
    return isinstance(node, _Token) and node.kind in T.Comment


def _is_semicolon(node: _Node | None) -> bool:
    return isinstance(node, _Token) and node.is_punct(";")


def _key(node: _Node | None) -> str:
    return node.key if isinstance(node, _Token) else ""


def _first(items: list[_Node]) -> _Node | None:
    return next((n for n in items if not _is_comment(n)), None)


def _own_line(nodes: list[_Node], index: int) -> bool:
    """True when the token at `index` starts a line in the source."""
    if index == 0 or nodes[index].after_break:
        return True
    before = nodes[index - 1]
    return isinstance(before, _Token) and before.raw.endswith(("\r", "\n"))


def _tokens(sql: str) -> list[_Token]:
    tokens = _lex(sql)
    _mark_call_keywords(tokens)
    alias_names, unaliased = _find_aliases(tokens)
    table_alias = _add_missing_aliases(tokens, alias_names, unaliased)
    _requalify(tokens, table_alias)
    _normalize_names(tokens, alias_names)
    return tokens


def _lex(sql: str) -> list[_Token]:
    tokens: list[_Token] = []
    gap = ""
    for kind, raw in lexer.tokenize(sql):
        if kind in T.Whitespace:
            gap += raw
            continue
        if kind in T.Error:
            raise ValueError(f"Unrecognized SQL token: {raw!r}")
        tokens.append(_Token(kind, raw, gap))
        gap = ""
    return tokens


def _mark_call_keywords(tokens: list[_Token]) -> None:
    """Treat EXISTS(...) / IN(...) and similar consistently with or without a space."""
    for tok, nxt in zip(tokens, tokens[1:]):
        if tok.kind in T.Name and tok.raw.upper() in _CALL_LIKE_KEYWORDS and nxt.is_punct("("):
            tok.kind = T.Keyword


def _qualified_end(tokens: list[_Token], start: int) -> int:
    """Index of the last name in a dotted path such as schema.table."""
    last = start
    while (last + 2 < len(tokens) and tokens[last + 1].raw == "."
           and tokens[last + 2].kind in T.Name):
        last += 2
    return last


def _find_aliases(tokens: list[_Token]) -> tuple[set[str], list[int]]:
    """Flag existing table aliases and locate tables that have none.

    Returns the upper-cased alias names and, for each table without an alias
    that is safe to add one to, the index of its last name token.
    """
    alias_names: set[str] = set()
    unaliased: list[int] = []
    in_from = False
    selectable = False  # FROM/JOIN of a query, where adding an alias is safe
    saved: list[tuple[bool, bool]] = []
    last_kw = ""
    for i, tok in enumerate(tokens):
        if tok.is_punct("("):
            saved.append((in_from, selectable))
            in_from = selectable = False
        elif tok.is_punct(")"):
            in_from, selectable = saved.pop() if saved else (False, False)
        elif tok.kind in T.Keyword:
            if tok.key in {"FROM", "UPDATE", "INTO"} or tok.key.endswith("JOIN"):
                in_from = True
                selectable = tok.key not in {"UPDATE", "INTO"} and last_kw != "DELETE"
            elif tok.key in _FROM_ENDERS:
                in_from = selectable = False
            last_kw = tok.key
        elif in_from and tok.is_name and i:
            prev = tokens[i - 1]
            if prev.key == "AS" or prev.is_name or prev.is_punct(")"):
                tok.alias = True
                alias_names.add(tok.raw.upper())
            elif selectable and (prev.key == "FROM" or prev.key.endswith("JOIN")
                                 or prev.is_punct(",")):
                last = _qualified_end(tokens, i)
                after = tokens[last + 1] if last + 1 < len(tokens) else None
                if after is None or not after.is_punct("("):
                    unaliased.append(last)
    return alias_names, unaliased


def _add_missing_aliases(tokens: list[_Token], alias_names: set[str],
                         unaliased: list[int]) -> dict[str, str]:
    """Insert an alias after each unaliased table; returns {TABLE: ALIAS}.

    New aliases are initials of the table name (CUSTOMER_ORDERS -> co), made
    unique against `alias_names`, which is extended in place.
    """
    table_alias: dict[str, str] = {}
    new_tokens: dict[int, _Token] = {}
    for last in unaliased:
        after = tokens[last + 1] if last + 1 < len(tokens) else None
        if after is not None and (after.alias or after.key == "AS"):
            continue
        name = tokens[last].raw.upper()
        if name not in table_alias:
            table_alias[name] = _unique_alias(name, alias_names)
        new_tokens[last] = _Token(T.Name, table_alias[name].lower(), " ", alias=True)
    for index in sorted(new_tokens, reverse=True):
        tokens.insert(index + 1, new_tokens[index])
    return table_alias


def _unique_alias(table: str, taken: set[str]) -> str:
    base = "".join(part[0] for part in table.split("_") if part) or "T"
    alias, n = base, 0
    while alias in taken or next(iter(lexer.tokenize(alias)))[0] in T.Keyword:
        n += 1
        alias = f"{base}{n}"
    taken.add(alias)
    return alias


def _requalify(tokens: list[_Token], table_alias: dict[str, str]) -> None:
    """Qualifiers that used a table name must now use its new alias."""
    for i, (tok, nxt) in enumerate(zip(tokens, tokens[1:])):
        if (tok.kind in T.Name and tok.raw.upper() in table_alias and nxt.raw == "."
                and not (i and tokens[i - 1].raw == ".")):
            tok.raw = table_alias[tok.raw.upper()]


def _normalize_names(tokens: list[_Token], alias_names: set[str]) -> None:
    """Upper-case table/column names and lower-case aliases.

    Function calls, quoted identifiers, parameters, and string-literal
    prefixes are left untouched.
    """
    for i, tok in enumerate(tokens):
        if not tok.is_name:
            continue
        prev = tokens[i - 1] if i else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if tok.alias or (nxt is not None and nxt.raw == "." and tok.raw.upper() in alias_names):
            tok.raw = tok.raw.lower()
            continue
        if tok.raw[0] in "@:$#?%" or (prev is not None and prev.raw in {"@", "@@", ":", "$"}):
            continue
        if nxt is not None:
            is_call = nxt.is_punct("(") and not (
                prev is not None and prev.last_word in _TABLE_NAME_PRECEDERS)
            is_literal_prefix = nxt.kind in T.Literal.String and not nxt.gap
            if is_call or is_literal_prefix:
                continue
        tok.raw = tok.raw.upper()


def _tree(tokens: list[_Token]) -> list[_Node]:
    """Nest tokens into groups at each parenthesis pair."""
    root: list[_Node] = []
    current = root
    stack: list[tuple[list[_Node], _Token]] = []
    for tok in tokens:
        if tok.is_punct("("):
            stack.append((current, tok))
            if len(stack) > _MAX_NESTING:
                raise ValueError(f"SQL exceeds the supported nesting depth of {_MAX_NESTING}.")
            current = []
        elif tok.is_punct(")"):
            if not stack:
                raise ValueError("Unmatched closing parenthesis.")
            parent, opening = stack.pop()
            parent.append(_Group(opening, current, tok))
            current = parent
        else:
            current.append(tok)
    if stack:
        raise ValueError("Unmatched opening parenthesis.")
    return root


def _signature(tokens: list[_Token]) -> list[str]:
    """Token texts for preservation checks, ignoring keyword case and whitespace."""
    result = []
    for tok in tokens:
        value = tok.key or tok.raw
        if tok.kind in T.Comment.Single:
            value = value.rstrip("\r\n")
        result.append(value)
    return result


def _verify_tokens(source: list[_Token], result: str, inserted: int) -> None:
    expected = _signature(source)
    actual = _signature(_tokens(result))
    if actual.count(";") != expected.count(";") + inserted or (
        [s for s in actual if s != ";"] != [s for s in expected if s != ";"]
    ):
        raise ValueError("Formatting would change SQL tokens; this syntax is unsupported.")
