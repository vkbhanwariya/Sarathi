"""Native Windows File and Folder Picker for Mukha Web Frontend.

Provides a controlled boundary to invoke standard OS file dialogs (tkinter.filedialog)
without blocking or crashing the web server thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NativePickerResult:
    """Outcome of a native file/folder picker invocation."""

    paths: tuple[str, ...]
    is_available: bool = True
    error_message: str | None = None


class NativePicker:
    """Controlled native file/folder dialog boundary."""

    @staticmethod
    def is_available() -> bool:
        """Factual check whether Tcl/Tk is available in current Python environment."""
        try:
            import tkinter  # noqa: F401

            return True
        except Exception:
            return False

    @classmethod
    def browse_files(cls, title: str = "Select Document Files") -> NativePickerResult:
        """Open native multi-file picker dialog."""
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                file_paths = filedialog.askopenfilenames(
                    parent=root,
                    title=title,
                    filetypes=[
                        ("All Supported Documents", "*.pdf;*.docx;*.doc;*.csv;*.xlsx;*.xls;*.txt;*.html;*.htm;*.json"),
                        ("Word Documents (*.docx, *.doc)", "*.docx;*.doc"),
                        ("PDF Documents (*.pdf)", "*.pdf"),
                        ("Spreadsheets (*.csv, *.xlsx, *.xls)", "*.csv;*.xlsx;*.xls"),
                        ("Text & HTML (*.txt, *.html, *.htm)", "*.txt;*.html;*.htm"),
                        ("All Files (*.*)", "*.*"),
                    ],
                )
            finally:
                root.destroy()

            if file_paths:
                return NativePickerResult(paths=tuple(str(Path(p).resolve()) for p in file_paths))
            return NativePickerResult(paths=())
        except Exception as err:
            return NativePickerResult(
                paths=(),
                is_available=False,
                error_message=f"Native file dialog unavailable: {err.__class__.__name__}",
            )

    @classmethod
    def browse_folder(cls, title: str = "Select Folder") -> NativePickerResult:
        """Open native folder picker dialog."""
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                folder_path = filedialog.askdirectory(parent=root, title=title)
            finally:
                root.destroy()

            if folder_path:
                return NativePickerResult(paths=(str(Path(folder_path).resolve()),))
            return NativePickerResult(paths=())
        except Exception as err:
            return NativePickerResult(
                paths=(),
                is_available=False,
                error_message=f"Native folder dialog unavailable: {err.__class__.__name__}",
            )
