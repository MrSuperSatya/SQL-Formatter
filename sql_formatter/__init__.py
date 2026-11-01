"""Format SQL into a tab-indented, lowercase-keyword house style.

Install:  python -m pip install sqlparse
Import:   from sql_formatter import format_sql, format_sql_file

Style: one tab per indent level, lowercase keywords, inline comma-separated
lists, outer clause headings on their own lines, compact headings inside
subqueries, and multiline derived tables. Function, literal, and comment
spelling is preserved; table and column names are upper-cased and table
unquoted aliases lower-cased (missing aliases are generated when safe). This is a
formatter, not a SQL validator or dialect converter.

SELECTs, CTEs, joins, subqueries, set operations, and ordinary INSERT/UPDATE/
DELETE statements get the custom layout. Other statements get conservative
spacing. Procedural blocks and common client directives (GO, DELIMITER,
PROMPT, SPOOL) are rejected: format their SQL statements separately.
"""

from ._api import format_sql, format_sql_file

__all__ = ["format_sql", "format_sql_file"]
