# SQL Formatter

A Python SQL formatter using `sqlparse` and a tab-indented house style.
Requires Python 3.10 or newer.

## Install and use

From the project directory:

```sh
python -m pip install -r requirements.txt
```

Import directly from the package:

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

The formatter uppercases table and column names, lowercases unquoted table
aliases, and generates missing aliases for unquoted tables when safe.
Functions, quoted identifiers, literals, and comments retain their spelling.
Statements receive semicolons and are separated by a blank line.

`format_sql_file` accepts strings or `pathlib.Path` objects and returns the
output `Path`. It reads UTF-8 with an optional BOM by default; pass `encoding`
to read a different encoding. Output is UTF-8 with LF newlines. Using the same
input and output path replaces the input file.

This formats SQL without executing it or validating its syntax. Unsupported
procedural SQL, stored routines, client directives, lexical errors, unmatched
parentheses, and token-preservation failures raise `ValueError`.

## GUI app

On Windows, double-click **app_gui.bat** in the project folder.
The launcher uses `.venv\Scripts\pythonw.exe` to open `app_gui.py`.

You can also run it from the project directory:

```sh
python app_gui.py
```

Paste SQL into the input area. **Format & Copy** formats the current input
and copies the result to the clipboard. **Clear** empties the input area.
Formatting errors appear below the input area.
The GUI requires a Python installation with Tkinter support.

## Structure

| File | Responsibility |
| --- | --- |
| `app_gui.bat` | Double-click launcher using the project's virtual environment |
| `app_gui.py` | Tkinter GUI with Format & Copy and Clear buttons |
| `sql_formatter/__init__.py` | Public package imports |
| `sql_formatter/_api.py` | Public string and file formatting functions |
| `sql_formatter/_tokens.py` | Lexing, parenthesis trees, qualified-name reading, and token preservation |
| `sql_formatter/_identifiers.py` | Query scopes, table aliases, and identifier normalization |
| `sql_formatter/_statements.py` | Script validation, statement boundaries, and grouping with trailing comments |
| `sql_formatter/_layout.py` | Expression, clause, and statement rendering |
| `sql_formatter/_syntax.py` | Shared SQL keyword categories and formatting limits |

The processing order is tokenization, script validation, parenthesis grouping,
statement splitting, identifier normalization, layout, and token verification.
Modules prefixed with `_` are internal; use the two public functions above.

## Tests

No additional test dependencies are required:

```sh
python -m unittest discover -s tests -v
```

The regression fixtures cover 44 SQL examples in
all three keyword modes. Tests check exact output, formatting idempotence,
statement comments and empty statements, invalid input, and file behavior
including BOMs, encodings, LF newlines, and preserving an existing output file
when formatting fails.
Additional regression tests execute SQL against an in-memory SQLite database
to check query results before and after formatting, including scoped aliases,
schema-qualified columns, comments, quoted names, and compound queries.
GUI tests exercise both buttons, empty and invalid input, and clipboard errors
using real Tk widgets without changing the system clipboard. They are skipped
when a Tk display is unavailable.
