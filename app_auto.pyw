"""Windows: copy SQL, then double-click this file to format the clipboard.

Keep this file beside sql_formatter.py. Requires its existing sqlparse
dependency: python -m pip install sqlparse
Success is silent; errors appear in a dialog. No SQL is executed.
"""

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import sys
import time


class WindowsClipboard:
    TEXT = 13  # CF_UNICODETEXT

    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = [
            (self.user, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR,
             wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
             ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
             wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND),
            (self.user, "DestroyWindow", [wintypes.HWND], wintypes.BOOL),
            (self.user, "OpenClipboard", [wintypes.HWND], wintypes.BOOL),
            (self.user, "CloseClipboard", [], wintypes.BOOL),
            (self.user, "EmptyClipboard", [], wintypes.BOOL),
            (self.user, "IsClipboardFormatAvailable", [wintypes.UINT], wintypes.BOOL),
            (self.user, "GetClipboardData", [wintypes.UINT], wintypes.HANDLE),
            (self.user, "SetClipboardData", [wintypes.UINT, wintypes.HANDLE], wintypes.HANDLE),
            (self.user, "GetClipboardSequenceNumber", [], wintypes.DWORD),
            (self.kernel, "GlobalAlloc", [wintypes.UINT, ctypes.c_size_t], wintypes.HANDLE),
            (self.kernel, "GlobalLock", [wintypes.HANDLE], ctypes.c_void_p),
            (self.kernel, "GlobalUnlock", [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, "GlobalFree", [wintypes.HANDLE], wintypes.HANDLE),
        ]
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes = args
            function.restype = result
        # A hidden native window supplies the required clipboard owner handle.
        self.window = self.user.CreateWindowExW(
            0, "STATIC", "SQL Clipboard Formatter", 0,
            0, 0, 0, 0, None, None, None, None,
        )
        if not self.window:
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.window:
            self.user.DestroyWindow(self.window)
            self.window = None

    @contextmanager
    def opened(self):
        deadline = time.monotonic() + 1.0
        while not self.user.OpenClipboard(self.window):
            if time.monotonic() >= deadline:
                raise RuntimeError("Clipboard is busy. Please try again.")
            time.sleep(0.02)
        try:
            yield
        finally:
            self.user.CloseClipboard()

    def read(self):
        with self.opened():
            if not self.user.IsClipboardFormatAvailable(self.TEXT):
                raise ValueError("Copy some SQL text to the clipboard first.")
            handle = self.user.GetClipboardData(self.TEXT)
            if not handle:
                raise ctypes.WinError(ctypes.get_last_error())
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                source = ctypes.wstring_at(pointer)
            finally:
                self.kernel.GlobalUnlock(handle)
            return source, self.user.GetClipboardSequenceNumber()

    def replace(self, text, expected_sequence):
        data = text.encode("utf-16-le") + b"\x00\x00"
        handle = self.kernel.GlobalAlloc(0x0002, len(data))  # GMEM_MOVEABLE
        if not handle:
            raise MemoryError("Could not allocate clipboard memory.")
        try:
            pointer = self.kernel.GlobalLock(handle)
            if not pointer:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                ctypes.memmove(pointer, data, len(data))
            finally:
                self.kernel.GlobalUnlock(handle)
            with self.opened():
                if self.user.GetClipboardSequenceNumber() != expected_sequence:
                    raise RuntimeError("Clipboard changed while formatting. Please run again.")
                if not self.user.EmptyClipboard():
                    raise ctypes.WinError(ctypes.get_last_error())
                if not self.user.SetClipboardData(self.TEXT, handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                handle = None  # Windows now owns the memory, even after we exit.
        finally:
            if handle:
                self.kernel.GlobalFree(handle)


def format_clipboard(clipboard, formatter):
    source, sequence = clipboard.read()
    if not source.strip():
        raise ValueError("Copy some SQL text to the clipboard first.")
    formatted = formatter(source)
    if not formatted.strip():
        raise ValueError("The formatter returned empty text; clipboard was kept.")
    if formatted != source:
        clipboard.replace(formatted, sequence)


def main():
    if sys.platform != "win32":
        if sys.stderr is not None:
            print("This version requires Windows.", file=sys.stderr)
        return 1
    clipboard = None
    try:
        from sql_formatter import format_sql

        clipboard = WindowsClipboard()
        format_clipboard(clipboard, format_sql)
        return 0
    except Exception as exc:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.UINT]
        user.MessageBoxW.restype = ctypes.c_int
        user.MessageBoxW(None, str(exc), "SQL Clipboard Formatter", 0x10)
        return 1
    finally:
        if clipboard is not None:
            clipboard.close()


if __name__ == "__main__":
    raise SystemExit(main())
