"""Double-click to open this app, using its local Python environment when available."""

import os
from pathlib import Path
import runpy
import subprocess
import sys


def main():
    folder = Path(__file__).resolve().parent
    environment = folder / ".venv"
    interpreter = environment / "Scripts" / "pythonw.exe"
    if not interpreter.is_file():
        interpreter = environment / "Scripts" / "python.exe"

    try:
        if interpreter.is_file() and Path(sys.prefix).resolve() != environment.resolve():
            options = {"cwd": str(folder)}
            if os.name == "nt":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            subprocess.Popen(
                [str(interpreter), str(Path(__file__).resolve()), *sys.argv[1:]],
                **options,
            )
        else:
            os.chdir(folder)
            sys.path.insert(0, str(folder))
            runpy.run_path(str(folder / "app_gui.py"), run_name="__main__")
    except Exception as error:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            f"Could not open {folder.name}",
            f"{type(error).__name__}: {error}\n\n"
            "For setup instructions, see README.md in this app's folder.",
            parent=root,
        )
        root.destroy()


if __name__ == "__main__":
    main()
