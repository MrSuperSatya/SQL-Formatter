"""Exercise the GUI buttons with real Tk widgets and an isolated clipboard."""

import tkinter as tk
import unittest
from unittest.mock import patch

from app_gui import SQLFormatterApp


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}") from exc
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.app = SQLFormatterApp(self.root)
        self.addCleanup(self.app.destroy)
        # Button tests must not replace the user's system clipboard.
        clear_patch = patch.object(self.app, "clipboard_clear")
        append_patch = patch.object(self.app, "clipboard_append")
        self.clear_clipboard = clear_patch.start()
        self.copy_text = append_patch.start()
        self.addCleanup(clear_patch.stop)
        self.addCleanup(append_patch.stop)

    def set_input(self, source):
        self.app.input_text.delete("1.0", tk.END)
        self.app.input_text.insert("1.0", source)

    def test_format_and_copy_preserves_input(self):
        source = "SELECT customer_id FROM customers"
        self.set_input(source)
        self.app.copy_button.invoke()
        self.assertEqual(self.app.input_text.get("1.0", "end-1c"), source)
        self.clear_clipboard.assert_called_once_with()
        self.copy_text.assert_called_once_with(
            "select\n\tCUSTOMER_ID\nfrom\n\tCUSTOMERS c;\n"
        )
        self.assertEqual(self.app.status.get(), "SQL formatted and copied to clipboard.")

    def test_format_and_copy_uses_current_input(self):
        self.set_input("select 1")
        self.app.copy_button.invoke()
        self.clear_clipboard.reset_mock()
        self.copy_text.reset_mock()
        self.set_input("select 2")
        self.app.copy_button.invoke()
        self.clear_clipboard.assert_called_once_with()
        self.copy_text.assert_called_once_with("select\n\t2;\n")
        self.assertEqual(self.app.status.get(), "SQL formatted and copied to clipboard.")

    def test_invalid_sql_does_not_copy_or_change_input(self):
        self.set_input("select 1")
        self.app.copy_button.invoke()
        self.clear_clipboard.reset_mock()
        self.copy_text.reset_mock()
        self.set_input("select (1")
        self.app.copy_button.invoke()
        self.assertEqual(self.app.input_text.get("1.0", "end-1c"), "select (1")
        self.assertIn("Unmatched opening parenthesis", self.app.status.get())
        self.clear_clipboard.assert_not_called()
        self.copy_text.assert_not_called()

    def test_empty_input_does_not_copy(self):
        self.set_input("select 1")
        self.app.copy_button.invoke()
        self.clear_clipboard.reset_mock()
        self.copy_text.reset_mock()
        self.set_input(" \t\n")
        self.app.copy_button.invoke()
        self.assertEqual(self.app.status.get(), "Enter SQL to format.")
        self.clear_clipboard.assert_not_called()
        self.copy_text.assert_not_called()

    def test_clear_button_empties_input_without_copying(self):
        self.set_input("select 1")
        self.app.clear_button.invoke()
        self.assertEqual(self.app.input_text.get("1.0", "end-1c"), "")
        self.assertEqual(self.app.status.get(), "Input cleared.")
        self.clear_clipboard.assert_not_called()
        self.copy_text.assert_not_called()

    def test_clipboard_clear_failure_keeps_input_and_reports_error(self):
        self.set_input("select 1")
        self.clear_clipboard.side_effect = tk.TclError("Clipboard unavailable")
        self.app.copy_button.invoke()
        self.assertEqual(self.app.input_text.get("1.0", "end-1c"), "select 1")
        self.assertIn("Could not copy to clipboard", self.app.status.get())
        self.copy_text.assert_not_called()

    def test_clipboard_append_failure_reports_error(self):
        self.set_input("select 1")
        self.copy_text.side_effect = tk.TclError("Clipboard unavailable")
        self.app.copy_button.invoke()
        self.clear_clipboard.assert_called_once_with()
        self.copy_text.assert_called_once_with("select\n\t1;\n")
        self.assertIn("Could not copy to clipboard", self.app.status.get())
        self.assertEqual(self.app.input_text.get("1.0", "end-1c"), "select 1")


if __name__ == "__main__":
    unittest.main()
