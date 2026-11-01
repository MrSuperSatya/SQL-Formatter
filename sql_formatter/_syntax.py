"""SQL keyword categories and formatting limits shared by the pipeline."""

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
