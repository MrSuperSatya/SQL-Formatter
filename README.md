# SQL Formatter

A Python SQL formatter using `sqlparse` and a tab-indented house style.
Requires Python 3.10 or newer.

## Install and use

From the project directory:

```sh
python -m pip install -r requirements.txt
```

Import directly from the package, as shown in `test.ipynb`:

```python
from sql_formatter import format_sql, format_sql_file

print(format_sql("SELECT customer_id FROM customers WHERE active = 1"))

format_sql_file("sample SQL.sql", "formatted.sql", keyword_case="upper")
```

To use the formatter in another project, copy the complete `sql_formatter`
directory.

`format_sql` returns formatted text with a final newline, or an empty string
for empty input. `keyword_case` accepts `"lower"` (the default), `"upper"`, or
`"preserve"`.

The formatter uppercases table and column names, lowercases table aliases,
and generates missing table aliases. Functions, quoted identifiers, literals,
and comments retain their spelling. Statements receive semicolons and are
separated by a blank line.

`format_sql_file` accepts strings or `pathlib.Path` objects and returns the
output `Path`. It reads UTF-8 with an optional BOM by default; pass `encoding`
to read a different encoding. Output is UTF-8 with LF newlines. Using the same
input and output path replaces the input file.

This formats SQL without executing it or validating its syntax. Unsupported
procedural SQL, stored routines, client directives, lexical errors, unmatched
parentheses, and token-preservation failures raise `ValueError`.

## Structure

| File | Responsibility |
| --- | --- |
| `sql_formatter/__init__.py` | Public package imports |
| `sql_formatter/_api.py` | Public string and file formatting functions |
| `sql_formatter/_tokens.py` | Lexing, identifiers, parenthesis trees, and token preservation |
| `sql_formatter/_statements.py` | Script validation and statement boundaries |
| `sql_formatter/_layout.py` | Expression, clause, and statement rendering |
| `sql_formatter/_syntax.py` | Shared SQL keyword categories and formatting limits |

The processing order is token normalization, script validation, parenthesis
grouping, statement splitting, layout, and token verification. Modules prefixed
with `_` are internal; use the two public functions above.

## Tests

No additional test dependencies are required:

```sh
python -m unittest discover -s tests -v
```

The regression fixtures capture 44 SQL examples from the original formatter in
all three keyword modes. Tests check exact output, formatting idempotence,
invalid input, and file behavior including BOMs, encodings,
LF newlines, and preserving an existing output file when formatting fails.
