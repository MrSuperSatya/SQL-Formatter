"""Public API regression tests, runnable with the standard library."""

import json
import tempfile
import unittest
from pathlib import Path

from sql_formatter import format_sql, format_sql_file


_FIXTURES = Path(__file__).with_name("fixtures") / "formatting.json"


class FormattingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(_FIXTURES.read_text(encoding="utf-8"))

    def test_matches_original_output(self):
        for case in self.cases:
            for keyword_case, expected in case["expected"].items():
                with self.subTest(case=case["name"], keyword_case=keyword_case):
                    self.assertEqual(
                        format_sql(case["sql"], keyword_case=keyword_case), expected
                    )

    def test_formatting_is_idempotent(self):
        for case in self.cases:
            for keyword_case, formatted in case["expected"].items():
                with self.subTest(case=case["name"], keyword_case=keyword_case):
                    self.assertEqual(
                        format_sql(formatted, keyword_case=keyword_case), formatted
                    )

    def test_default_keyword_case_is_lower(self):
        self.assertEqual(format_sql("SELECT 1"), "select\n\t1;\n")

    def test_calls_do_not_share_alias_state(self):
        source = "select * from customers"
        expected = "select\n\t*\nfrom\n\tCUSTOMERS c;\n"
        self.assertEqual(format_sql(source), expected)
        format_sql("select * from loans c join customers on c.id = customers.id")
        self.assertEqual(format_sql(source), expected)

    def test_non_string_inputs_are_rejected(self):
        for value in (None, 1, b"select 1", ["select 1"]):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TypeError, "^sql must be a string$"):
                    format_sql(value)

    def test_invalid_keyword_case_is_rejected(self):
        for value in ("title", "LOWER", "", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "keyword_case must be"):
                    format_sql("select 1", keyword_case=value)

    def test_unmatched_parentheses_are_rejected(self):
        for source, message in (
            ("select (1", "Unmatched opening parenthesis."),
            ("select 1)", "Unmatched closing parenthesis."),
        ):
            with self.subTest(source=source):
                with self.assertRaises(ValueError) as caught:
                    format_sql(source)
                self.assertEqual(str(caught.exception), message)

    def test_excessive_nesting_is_rejected(self):
        source = "select " + "(" * 81 + "1" + ")" * 81
        with self.assertRaisesRegex(ValueError, "supported nesting depth of 80"):
            format_sql(source)

    def test_unrecognized_tokens_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unrecognized SQL token"):
            format_sql("select 'unterminated")

    def test_client_directives_are_rejected(self):
        for directive in ("GO", "DELIMITER", "PROMPT", "SPOOL"):
            with self.subTest(directive=directive):
                with self.assertRaisesRegex(ValueError, "Client directive"):
                    format_sql(f"{directive}\nselect 1")

    def test_procedural_sql_is_rejected(self):
        for source in (
            "BEGIN select 1; END",
            "DECLARE x integer",
            "WHILE 1 LOOP select 1; END LOOP",
            "IF 1 = 1 select 1",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "Procedural SQL is unsupported"):
                    format_sql(source)

    def test_stored_routines_are_rejected(self):
        for source in (
            "CREATE PROCEDURE p AS select 1",
            "CREATE FUNCTION f() RETURNS int AS $$ SELECT 1 $$",
            "CREATE TRIGGER t BEFORE INSERT ON customers select 1",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "Stored routine definitions"):
                    format_sql(source)


class FileFormattingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / "input.sql"
        self.target = self.root / "output.sql"

    def test_bom_input_and_utf8_output_with_lf_newlines(self):
        original = b"\xef\xbb\xbfSELECT 'caf\xc3\xa9'\r\nFROM customers\r\n"
        self.source.write_bytes(original)
        result = format_sql_file(self.source, self.target, keyword_case="upper")
        self.assertEqual(result, self.target)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(
            self.target.read_bytes(), b"SELECT\n\t'caf\xc3\xa9'\nFROM\n\tCUSTOMERS c;\n"
        )

    def test_string_paths_and_explicit_encoding(self):
        self.source.write_bytes("select 'caf\u00e9'".encode("cp1252"))
        result = format_sql_file(
            str(self.source), str(self.target), encoding="cp1252"
        )
        self.assertEqual(result, self.target)
        self.assertEqual(self.target.read_bytes(), "select\n\t'caf\u00e9';\n".encode("utf-8"))

    def test_can_format_a_file_in_place(self):
        self.source.write_text("select 1", encoding="utf-8")
        self.assertEqual(format_sql_file(self.source, self.source), self.source)
        self.assertEqual(self.source.read_bytes(), b"select\n\t1;\n")

    def test_invalid_sql_does_not_overwrite_an_existing_target(self):
        self.source.write_text("select (1", encoding="utf-8")
        self.target.write_bytes(b"existing content")
        with self.assertRaises(ValueError):
            format_sql_file(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"existing content")

    def test_missing_input_does_not_create_output(self):
        with self.assertRaises(FileNotFoundError):
            format_sql_file(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_empty_input_creates_an_empty_file(self):
        self.source.write_text(" \t\n", encoding="utf-8")
        format_sql_file(self.source, self.target)
        self.assertEqual(self.target.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
