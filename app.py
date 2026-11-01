"""A small Tkinter interface for the SQL formatter. Run with python app.py."""

import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from sql_formatter import format_sql


class SQLFormatterApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(4, weight=1)

        ttk.Label(self, text="SQL input").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.input_text = ScrolledText(
            self, height=10, wrap=tk.WORD, font="TkFixedFont", undo=True
        )
        self.input_text.grid(row=1, column=0, sticky="nsew")

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="w", pady=10)
        self.format_button = ttk.Button(actions, text="Format", command=self.format_input)
        self.format_button.pack(side=tk.LEFT, padx=(0, 8))
        self.copy_button = ttk.Button(
            actions,
            text="Format & Copy",
            command=lambda: self.format_input(copy_to_clipboard=True),
        )
        self.copy_button.pack(side=tk.LEFT)

        ttk.Label(self, text="Formatted SQL").grid(row=3, column=0, sticky="w", pady=(0, 4))
        self.output_text = ScrolledText(
            self, height=10, wrap=tk.WORD, font="TkFixedFont", state=tk.DISABLED
        )
        self.output_text.grid(row=4, column=0, sticky="nsew")

        self.status = tk.StringVar(master=self, value="Paste SQL above, then choose an action.")
        ttk.Label(self, textvariable=self.status, wraplength=600).grid(
            row=5, column=0, sticky="w", pady=(8, 0)
        )
        self.input_text.focus_set()

    def format_input(self, *, copy_to_clipboard: bool = False) -> None:
        source = self.input_text.get("1.0", "end-1c")
        try:
            formatted = format_sql(source)
        except ValueError as exc:
            self._set_output("")
            self.status.set(f"Could not format SQL: {exc}")
            return

        self._set_output(formatted)
        if not formatted:
            self.status.set("Enter SQL to format.")
            self.input_text.focus_set()
            return

        if copy_to_clipboard:
            try:
                self.clipboard_clear()
                self.clipboard_append(formatted)
            except tk.TclError as exc:
                self.status.set(f"SQL formatted. Could not copy to clipboard: {exc}")
                return
            self.status.set("SQL formatted and copied to clipboard.")
        else:
            self.status.set("SQL formatted.")

    def _set_output(self, text: str) -> None:
        self.output_text.configure(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.configure(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    root.title("SQL Formatter")
    root.geometry("900x650")
    root.minsize(640, 480)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    SQLFormatterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
