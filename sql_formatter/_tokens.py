"""Tokenize SQL, build parenthesis trees, and verify token preservation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Union

try:
    from sqlparse import lexer, tokens as T
except ImportError as exc:
    raise ImportError("Install the dependency: python -m pip install sqlparse") from exc

from ._syntax import (
    _CALL_LIKE_KEYWORDS,
    _MAX_NESTING,
    _QUERY_KEYS,
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
        return (
            self.kind in T.Name and self.kind not in T.Name.Placeholder
        ) or self.kind in T.Literal.String.Symbol

    @property
    def is_quoted(self) -> bool:
        return len(self.raw) > 1 and (self.raw[0], self.raw[-1]) in {
            ('"', '"'), ("`", "`"), ("[", "]"),
        }

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


def _is_distinct_from(items: list[_Node], index: int) -> bool:
    """Distinguish the FROM in an IS [NOT] DISTINCT FROM comparison."""
    if _key(items[index]) != "FROM":
        return False
    previous = (
        items[i] for i in range(index - 1, -1, -1)
        if not _is_comment(items[i])
    )
    if _key(next(previous, None)) != "DISTINCT":
        return False
    key = _key(next(previous, None))
    if key == "NOT":
        key = _key(next(previous, None))
    return key in {"IS", "IS NOT"}


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
    return tokens


def _lex(sql: str) -> list[_Token]:
    tokens: list[_Token] = []
    gap = ""
    offset = 0
    for kind, raw in lexer.tokenize(sql):
        # sqlparse emits '/' and '*' as ordinary tokens for an unclosed comment.
        if sql.startswith("/*", offset) and kind not in T.Comment:
            raise ValueError("Unterminated block comment.")
        offset += len(raw)
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


def _flatten(items: list[_Node]) -> Iterator[_Token]:
    for node in items:
        if isinstance(node, _Group):
            yield node.opening
            yield from _flatten(node.items)
            yield node.closing
        else:
            yield node


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
