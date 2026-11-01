"""A small Tkinter interface for the SQL formatter. Run with python app_gui.py."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from sql_formatter import format_sql


class SQLFormatterApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        ttk.Label(self, text="SQL input").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.input_text = ScrolledText(
            self, height=10, wrap=tk.WORD, font="TkFixedFont", undo=True
        )
        self.input_text.grid(row=1, column=0, sticky="nsew")

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="w", pady=10)
        self.button_font = tkfont.nametofont("TkDefaultFont").copy()
        self.button_font.configure(size=14, weight="bold")
        ttk.Style(self).configure(
            "Action.TButton", font=self.button_font, padding=(20, 12)
        )
        self.copy_button = ttk.Button(
            actions,
            text="Format & Copy",
            style="Action.TButton",
            command=self.format_input,
        )
        self.copy_button.pack(side=tk.LEFT)
        self.clear_button = ttk.Button(
            actions, text="Clear", command=self.clear_text, style="Action.TButton"
        )
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))

        self.status = tk.StringVar(master=self, value="Paste SQL above, then choose an action.")
        ttk.Label(self, textvariable=self.status, wraplength=600).grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.input_text.focus_set()

    def format_input(self) -> None:
        source = self.input_text.get("1.0", "end-1c")
        try:
            formatted = format_sql(source)
        except ValueError as exc:
            self.status.set(f"Could not format SQL: {exc}")
            return

        if not formatted:
            self.status.set("Enter SQL to format.")
            self.input_text.focus_set()
            return

        try:
            self.clipboard_clear()
            self.clipboard_append(formatted)
        except tk.TclError as exc:
            self.status.set(f"SQL formatted. Could not copy to clipboard: {exc}")
            return
        self.status.set("SQL formatted and copied to clipboard.")

    def clear_text(self) -> None:
        self.input_text.delete("1.0", tk.END)
        self.status.set("Input cleared.")
        self.input_text.focus_set()


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
