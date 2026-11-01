"""Format SQL into a tab-indented, lowercase-keyword house style.

Install:  python -m pip install sqlparse
Import:   from satya_format_sql import format_sql, format_sql_file

Style: one tab per indent level, lowercase keywords, inline comma-separated
lists, outer clause headings on their own lines, compact headings inside
subqueries, and multiline derived tables. Function, literal, and comment
spelling is preserved; table and column names are upper-cased and table
aliases lower-cased (missing table aliases are generated). This is a
formatter, not a SQL validator or dialect converter.

SELECTs, CTEs, joins, subqueries, set operations, and ordinary INSERT/UPDATE/
DELETE statements get the custom layout. Other statements get conservative
spacing. Procedural blocks and common client directives (GO, DELIMITER,
PROMPT, SPOOL) are rejected: format their SQL statements separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

try:
    from sqlparse import lexer, tokens as T
except ImportError as exc:
    raise ImportError("Install the dependency: python -m pip install sqlparse") from exc

__all__ = ["format_sql", "format_sql_file"]


# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

_INDENT = "\t"
_MAX_NESTING = 80
_KEYWORD_CASES = {"lower", "upper", "preserve"}

# Keywords that end a FROM/JOIN table list.
_FROM_ENDERS = {
    "SELECT", "WHERE", "ON", "GROUP BY", "ORDER BY", "HAVING", "SET", "USING", "VALUES",
    "UNION", "UNION ALL", "INTERSECT", "EXCEPT", "LIMIT", "OFFSET", "WINDOW", "QUALIFY",
    "RETURNING", "FETCH",
}
# The lexer reads these as names when no space precedes the parenthesis.
_CALL_LIKE_KEYWORDS = {"EXISTS", "IN", "OVER", "FILTER", "VALUES", "USING", "TOP"}
# After these keywords, `name(` is a table rather than a function call.
_TABLE_NAME_PRECEDERS = {"INTO", "TABLE", "UPDATE", "JOIN", "FROM"}

_CLAUSES = {
    "SELECT", "FROM", "WHERE", "GROUP BY", "HAVING", "ORDER BY", "QUALIFY",
    "LIMIT", "OFFSET", "FETCH", "WINDOW", "CONNECT BY", "START WITH",
    "RETURNING", "SET", "VALUES", "INTO", "ON CONFLICT", "ON DUPLICATE KEY",
}
_SETS = {"UNION", "UNION ALL", "UNION DISTINCT", "EXCEPT", "EXCEPT ALL",
         "INTERSECT", "INTERSECT ALL", "MINUS"}
_LEADING = {"WITH", "INSERT", "UPDATE", "DELETE"}
_HEADERS = _CLAUSES | _SETS | _LEADING | {"INSERT INTO"}
_LOCKING = {"FOR UPDATE", "FOR SHARE"}
_PREDICATE_CLAUSES = {"WHERE", "HAVING", "QUALIFY", "FROM"}
_APPLY = {"CROSS APPLY", "OUTER APPLY"}
# Keywords followed by a space before "(" (other keywords look like function calls).
_PAREN_SPACE = {
    "IN", "NOT IN", "EXISTS", "NOT EXISTS", "AS", "OVER", "FILTER",
    "VALUES", "USING", "ON", "AND", "OR", "NOT", "WHEN", "THEN",
    "ELSE", "BY", "FROM", "WHERE", "SELECT", "DISTINCT", "ALL",
    "LATERAL", "TOP", "TABLE", "WITH", "PARTITION", "CHECK", "KEY",
}

# First keyword of something formatted as a query.
_QUERY_KEYS = {"SELECT", "WITH", "VALUES", "INSERT", "UPDATE", "DELETE"}
# Keywords that can begin a statement when looking for missing semicolons.
_STATEMENT_KEYS = {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH"}
_DML_KEYS = {"SELECT", "INSERT", "UPDATE", "DELETE"}
# DML keywords whose body starts right away (INSERT has a column list first).
_BODY_KEYS = {"SELECT", "UPDATE", "DELETE"}

_CLIENT_DIRECTIVES = {"GO", "DELIMITER", "PROMPT", "SPOOL"}
_PROCEDURAL_KEYS = {"BEGIN", "BEGIN ATOMIC", "DECLARE", "WHILE", "LOOP"}
_ROUTINE_KEYS = {"PROCEDURE", "FUNCTION", "TRIGGER"}
_CREATE_KEYS = {"CREATE", "CREATE OR REPLACE", "ALTER"}


# --------------------------------------------------------------------------
# Tokens and tree
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Tokenizing and identifier normalization
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

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
            following = items[i + 1] if i + 1 < len(items) else None
            key = _key(node)
            if key == "CASE":
                case_depth += 1
            elif key == "END":
                case_depth = max(0, case_depth - 1)
            if _is_comment(node):
                self.write_comment(node, level)
                previous = node
                continue
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


# --------------------------------------------------------------------------
# Validation and statement splitting
# --------------------------------------------------------------------------

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
    following = [n for n in items[i + 1:] if not _is_comment(n)][:2]
    if key == "WITH":
        if not following or not isinstance(following[0], _Token):
            return False
        if not (following[0].key == "RECURSIVE" or following[0].kind in T.Name):
            return False
        if len(following) < 2 or not (
            isinstance(following[1], _Group)
            or (isinstance(following[1], _Token) and following[1].key == "AS")
        ):
            return False
        return body
    if key == "INSERT" and following and isinstance(following[0], _Group):
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
        elif not body and (
            (first == "WITH" and key in _DML_KEYS)
            or (first == "INSERT" and key in {"SELECT", "VALUES", "SET"})
        ):
            body = True
        prev = node
        result.append(node)
    return result, inserted


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
    return "".join(renderer.out.parts).rstrip() + "\n", added


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


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def format_sql(sql: str, *, keyword_case: str = "lower") -> str:
    """Return formatted SQL, including a final newline.

    Each indentation level is one tab character. Keyword case may be 'lower',
    'upper', or 'preserve'. Function names, quoted identifiers, string
    literals, and comments retain their original spelling; table and column
    names are upper-cased and table aliases lower-cased.
    Multiple statements are each ended with a semicolon and separated by a
    blank line. No SQL is executed.
    ValueError is raised for unsupported scripts, lexical errors, unmatched
    parentheses, or a formatting change that alters the significant tokens.
    SQL syntax itself is not validated.
    """
    if not isinstance(sql, str):
        raise TypeError("sql must be a string")
    if keyword_case not in _KEYWORD_CASES:
        raise ValueError("keyword_case must be 'lower', 'upper', or 'preserve'")
    tokens = _tokens(sql.lstrip("\ufeff"))
    if not tokens:
        return ""
    _check_supported(tokens)
    items, inserted = _split_statements(_tree(tokens))
    result, added = _render(items, keyword_case)
    _verify_tokens(tokens, result, inserted + added)
    return result


def format_sql_file(input_path: str | Path, output_path: str | Path, *,
                    keyword_case: str = "lower",
                    encoding: str = "utf-8-sig") -> Path:
    """Format a file. Call with distinct paths to keep the original untouched."""
    source, target = Path(input_path), Path(output_path)
    sql = source.read_text(encoding=encoding)
    result = format_sql(sql, keyword_case=keyword_case)
    with target.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(result)
    return target
