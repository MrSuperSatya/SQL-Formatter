"""Check that formatting preserves executable SQL and identifier spelling."""

import sqlite3
import unittest

import sqlparse

from sql_formatter import format_sql


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.database = sqlite3.connect(":memory:")
        self.addCleanup(self.database.close)
        self.database.executescript(
            'create table customers(id integer, parent_id integer, "CustomerId" integer);'
            "insert into customers values(1, 0, 10), (2, 1, 20);"
            "create table accounts(id integer);"
            "insert into accounts values(1), (3);"
            'create table "Customer Table"("CustomerId" integer);'
            'insert into "Customer Table" values(10);'
            "attach database ':memory:' as other;"
            "create table other.customers(id integer);"
            "insert into other.customers values(1), (9);"
        )

    def results(self, sql):
        return [
            self.database.execute(statement).fetchall()
            for statement in sqlparse.split(sql)
        ]

    def assert_equivalent(self, source):
        expected = self.results(source)
        for keyword_case in ("lower", "upper", "preserve"):
            with self.subTest(source=source, keyword_case=keyword_case):
                formatted = format_sql(source, keyword_case=keyword_case)
                self.assertEqual(self.results(formatted), expected)
                self.assertEqual(
                    format_sql(formatted, keyword_case=keyword_case), formatted
                )

    def assert_changes_equivalent(self, source):
        self.database.execute("savepoint formatting")
        try:
            self.database.execute(source)
            expected = self.database.execute(
                "select * from customers order by id"
            ).fetchall()
            self.database.execute("rollback to formatting")
            for keyword_case in ("lower", "upper", "preserve"):
                with self.subTest(source=source, keyword_case=keyword_case):
                    formatted = format_sql(source, keyword_case=keyword_case)
                    self.database.execute(formatted)
                    self.assertEqual(
                        self.database.execute(
                            "select * from customers order by id"
                        ).fetchall(), expected,
                    )
                    self.assertEqual(
                        format_sql(formatted, keyword_case=keyword_case), formatted
                    )
                self.database.execute("rollback to formatting")
        finally:
            self.database.execute("rollback to formatting")
            self.database.execute("release formatting")

    def test_cte_insert_select_keeps_its_source_in_the_same_statement(self):
        for source in (
            "with x as (select 3 as id) insert into customers(id) select id from x",
            "with x(id) as (select 3) insert into customers select id, 0, 30 from x",
            "with x as (select 3 as id) insert into customers(id) "
            "/* source */ select id from x union all select 4",
            "with recursive x(id) as (select 3 union all select id+1 from x "
            "where id<4) insert into customers(id) select id from x",
            "with x as (select 3 as id) insert into customers(id) values(3)",
            "with x as (select 1 as id) update customers set parent_id=3 "
            "where id in(select id from x)",
            "with x as (select 1 as id) delete from customers "
            "where id in(select id from x)",
        ):
            self.assert_changes_equivalent(source)

    def test_cte_insert_select_still_allows_a_following_statement(self):
        source = (
            "with x as (select 3 as id) insert into customers(id) select id from x\n"
            "select id from customers"
        )
        for keyword_case in ("lower", "upper", "preserve"):
            with self.subTest(keyword_case=keyword_case):
                statements = sqlparse.split(format_sql(source, keyword_case=keyword_case))
                self.assertEqual(len(statements), 2)
                self.database.execute("savepoint formatting")
                try:
                    self.database.execute(statements[0])
                    self.assertEqual(
                        self.database.execute(statements[1]).fetchall(),
                        [(1,), (2,), (3,)],
                    )
                finally:
                    self.database.execute("rollback to formatting")
                    self.database.execute("release formatting")

    def test_distinct_from_comparisons_are_not_table_sources(self):
        for operator in (
            "is distinct from", "is not distinct from",
            "is /* comparison */ not distinct /* operand */ from",
        ):
            for source in (
                f"select * from customers where id {operator} parent_id",
                f"select * from customers where id {operator} parent_id order by id",
                f"select * from customers join accounts on customers.id "
                f"{operator} accounts.id",
                f"select id {operator} parent_id as different from customers",
                f"select case when id {operator} parent_id then 1 else 0 end "
                "from customers",
            ):
                self.assert_equivalent(source)
            self.assert_changes_equivalent(
                f"delete from customers where id {operator} parent_id"
            )

    def test_compound_ordering_keeps_references_to_each_operand(self):
        for operator in ("union", "union all", "except", "intersect", "union /* keep */ all"):
            for table in ("customers", "accounts"):
                self.assert_equivalent(
                    f"select id from customers {operator} select id from accounts "
                    f"order by {table}.id"
                )
        for source in (
            "select customers.id from customers union all select accounts.id "
            "from accounts order by customers.id",
            "select main.customers.id from main.customers union all select id "
            "from accounts order by main.customers.id",
            "select x.id from customers x union all select id from accounts order by x.id",
            "select id from customers union all select id from accounts "
            "union all select id from other.customers order by accounts.id",
            "select customers.id from customers where exists (select id "
            "from accounts union all select id from other.customers order by accounts.id)",
            "select customers.id from customers union all select accounts.id "
            "from accounts order by customers.id; select * from customers",
        ):
            self.assert_equivalent(source)

    def test_correlated_ctes_cannot_see_the_consuming_querys_aliases(self):
        for source in (
            "select customers.id from customers where exists (with x as "
            "(select customers.id as id) select x.id from accounts customers "
            "join x on x.id=customers.id)",
            "select customers.id from customers where exists (with x as "
            "(select customers.id as id) select * from accounts customers, x "
            "where x.id=2)",
            "select customers.id from customers where exists (with x as "
            "(select customers.id as id), y as (select x.id from x) select y.id "
            "from accounts customers join y on y.id=customers.id)",
            "select customers.id from customers where exists (with recursive x(id) as "
            "(select customers.id union all select id+1 from x where id<3) "
            "select x.id from accounts customers join x on x.id=customers.id)",
        ):
            self.assert_equivalent(source)

    def test_comment_markers_in_literals_and_comments_are_preserved(self):
        for source in (
            "select '/* unterminated'",
            'select 1 as "/* identifier"',
            "select 1 -- /* not a block comment",
            "select 1 /* complete */",
            "select 1/* first *//* second */",
            "select 'caf\u00e9' /* Unicode before the comment */",
        ):
            self.assert_equivalent(source)

    def test_aliases_are_scoped_to_statements(self):
        first = "select customers.id from accounts customers"
        second = "select customers.id from customers"
        self.assert_equivalent(f"{first}; {second}")
        self.assertEqual(
            self.results(format_sql(f"{first}\n{second}")),
            self.results(f"{first}; {second}"),
        )

    def test_aliases_are_scoped_to_compound_query_branches(self):
        self.assert_equivalent(
            "select customers.id from accounts customers "
            "union all select customers.id from customers"
        )

    def test_nested_queries_keep_local_and_correlated_references(self):
        for source in (
            "select customers.id from accounts customers where exists "
            "(select 1 from customers where customers.id = 1)",
            "select customers.id from customers where exists "
            "(select 1 from accounts where accounts.id = customers.id)",
            "select customers.id from customers where exists "
            "(select 1 from accounts c where c.id = customers.id)",
            "select customers.id from main.customers where exists "
            "(select 1 from other.customers where other.customers.id = main.customers.id)",
        ):
            self.assert_equivalent(source)

    def test_comma_sources_after_join_conditions_keep_their_local_scope(self):
        for condition in ("on a.id=b.id", "using(id)"):
            for source in (
                "customers",
                "accounts customers",
                "(select 1 as id) customers",
                "(customers)",
            ):
                self.assert_equivalent(
                    "select customers.id from customers where exists "
                    f"(select 1 from accounts a join accounts b {condition}, "
                    f"{source} where customers.id=1)"
                )

    def test_schema_qualified_columns_and_wildcards(self):
        for source in (
            "select main.customers.id from main.customers",
            "select main.customers.id from customers",
            "select main /* schema */ . customers.id from main.customers",
            "select main.customers.id, other.customers.id from main.customers "
            "join other.customers on main.customers.id = other.customers.id",
        ):
            self.assert_equivalent(source)

    def test_schema_qualified_correlations_prefer_the_matching_table(self):
        for source in (
            "select other.customers.id from other.customers where exists "
            "(select 1 from customers where customers.id=other.customers.id)",
            "select other.customers.id from other.customers where exists "
            "(select 1 from customers where main.customers.id=other.customers.id)",
            "select main.customers.id from main.customers where exists "
            "(select 1 from other.customers where main.customers.id=other.customers.id)",
        ):
            self.assert_equivalent(source)

    def test_schema_names_are_not_confused_with_inner_table_aliases(self):
        for outer_table, inner_table, alias in (
            ("customers", "other.customers", "main"),
            ("main.customers", "other.customers", "main"),
            ("other.customers", "customers", "other"),
        ):
            schema = "other" if outer_table.startswith("other.") else "main"
            self.assert_equivalent(
                f"select {outer_table}.id from {outer_table} where exists "
                f"(select 1 from {inner_table} {alias} "
                f"where {schema}.customers.id={alias}.id)"
            )

    def test_schema_qualified_wildcard_uses_the_generated_alias(self):
        self.assertEqual(
            format_sql("select main.customers.* from main.customers"),
            "select\n\tc.*\nfrom\n\tMAIN.CUSTOMERS c;\n",
        )

    def test_comments_do_not_hide_existing_aliases(self):
        for source in (
            "select x.id from customers /* note */ x",
            "select x.id from customers /* note */ as x",
            "select x.id from customers as /* note */ x",
            "select x.id from customers -- note\nas x",
            "select x.id from /* note */ customers /* alias */ x",
            "select x.id from main /* schema */ . customers /* alias */ x",
        ):
            self.assert_equivalent(source)

    def test_quoted_identifiers_preserve_spelling_and_execute(self):
        for opening, closing in (("[", "]"), ("`", "`"), ('"', '"')):
            column = f"{opening}CustomerId{closing}"
            table = f"{opening}Customer Table{closing}"
            alias = f"{opening}Customer Alias{closing}"
            for source in (
                f"select {column} from customers",
                f"select {column} from {table}",
                f"select {alias}.{column} from {table} {alias}",
                f"select {alias}.{column} from customers /* note */ as {alias}",
            ):
                self.assert_equivalent(source)
                formatted = format_sql(source)
                self.assertIn(column, formatted)
                if table in source:
                    self.assertIn(table, formatted)
                if alias in source:
                    self.assertIn(alias, formatted)

    def test_compound_selects_with_comments_remain_one_statement(self):
        for source in (
            "select 1 union /* keep */ all select 2",
            "select 1 union -- keep\nall select 2",
            "select 1 union /* keep */ all /* operand */ select 2",
            "select 1 union all /* operand */ select 2",
        ):
            self.assert_equivalent(source)

    def test_derived_tables_and_table_functions(self):
        for source in (
            "select * from (select id from customers)",
            "select * from ((select id from customers))",
            "select x.id from (select id from customers) /* note */ x",
            "select value from json_each('[1, 2]')",
            "select x.value from json_each('[1, 2]') /* note */ x",
        ):
            self.assert_equivalent(source)

    def test_comments_before_function_arguments_keep_function_spelling(self):
        for function in ("MAX", "mIn", "COUNT"):
            for comment in ("/* note */", "-- note\n", "/* first *//* second */"):
                source = f"select {function}{comment}(id) from customers"
                self.assert_equivalent(source)
                for keyword_case in ("lower", "upper", "preserve"):
                    with self.subTest(function=function, comment=comment,
                                      keyword_case=keyword_case):
                        self.assertIn(
                            function + " ", format_sql(source, keyword_case=keyword_case)
                        )

    def test_parenthesized_table_sources_keep_correlated_references(self):
        for source in (
            "select accounts.id from accounts where exists "
            "(select 1 from (accounts) where accounts.id = 1)",
            "select accounts.id from accounts where exists "
            "(select 1 from (accounts) x where accounts.id = x.id)",
            "select accounts.id from accounts where exists "
            "(select 1 from (accounts a join customers c on a.id = c.id) "
            "where c.id = accounts.id)",
        ):
            self.assert_equivalent(source)

    def test_set_quantifiers_do_not_create_statement_boundaries(self):
        for operator in ("union distinct", "except all", "intersect all"):
            for separator in (" ", " /* keep */ "):
                source = f"select 1 {operator.replace(' ', separator)} select 2"
                with self.subTest(source=source):
                    formatted = format_sql(source)
                    self.assertEqual(len(sqlparse.split(formatted)), 1)
                    self.assertEqual(format_sql(formatted), formatted)

    def test_final_comments_keep_trailing_spaces(self):
        for source, comment in (
            ("select 1; -- Note  ", "-- Note  "),
            ("select 1; -- Note  \r\n", "-- Note  "),
            ("-- Only a comment \t", "-- Only a comment \t"),
            ("select 1 -- Note  ", "-- Note  "),
        ):
            with self.subTest(source=source):
                formatted = format_sql(source)
                self.assertIn(comment + "\n", formatted)
                self.assertEqual(format_sql(formatted), formatted)


if __name__ == "__main__":
    unittest.main()
