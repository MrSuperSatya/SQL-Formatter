"""Coordinate token processing, validation, and layout for the public API."""

from __future__ import annotations

from pathlib import Path

from ._tokens import _tokens, _tree, _verify_tokens
from ._identifiers import _normalize_identifiers
from ._layout import _render
from ._statements import _check_supported, _split_statements
from ._syntax import _KEYWORD_CASES


def format_sql(sql: str, *, keyword_case: str = "lower") -> str:
    """Return formatted SQL, including a final newline.

    Each indentation level is one tab character. Keyword case may be 'lower',
    'upper', or 'preserve'. Function names, quoted identifiers, string
    literals, and comments retain their original spelling; table and column
    names are upper-cased and unquoted table aliases lower-cased.
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
    items, _ = _split_statements(_tree(tokens))
    normalized = _normalize_identifiers(items)
    result, added = _render(_tree(normalized), keyword_case)
    _verify_tokens(normalized, result, added)
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
