"""Window: New books tracker — shows books added to the DB since a given date."""
import tkinter as tk
from tkinter import ttk
import sqlite3
import threading
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager


class NewBooksWindow:
    """Окно новых книг: какие книги появились в библиотеке за последние N дней."""

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.settings = settings_manager
        self.db_path = Path(__file__).parent / '.library_cache.db'

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Новые книги")
        self.window.minsize(700, 450)

        if settings_manager:
            setup_window_persistence(self.window, 'new_books', settings_manager, '950x550+160+120')
        else:
            self.window.geometry('950x550')

        self._build_ui()
        threading.Thread(target=self._load_data, daemon=True).start()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ctrl, text="За последние").pack(side=tk.LEFT)
        self._days_var = tk.IntVar(value=30)
        ttk.Spinbox(ctrl, from_=1, to=3650, width=6,
                    textvariable=self._days_var).pack(side=tk.LEFT, padx=4)
        ttk.Label(ctrl, text="дней").pack(side=tk.LEFT)
        ttk.Button(ctrl, text="Показать", command=self._refresh).pack(side=tk.LEFT, padx=10)
        self._status_var = tk.StringVar(value="Загрузка…")
        ttk.Label(ctrl, textvariable=self._status_var, foreground="gray").pack(side=tk.LEFT)

        table_frame = ttk.Frame(main)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        cols = ("added_date", "author", "series", "title", "file_path")
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings')
        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        headers = {"added_date": "Добавлено", "author": "Автор", "series": "Серия",
                   "title": "Название", "file_path": "Путь"}
        widths  = {"added_date": 140, "author": 160, "series": 160,
                   "title": 200, "file_path": 300}
        for col in cols:
            self.tree.heading(col, text=headers[col],
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=widths[col], minwidth=60)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

        self.tree.bind('<Double-Button-1>', self._on_double_click)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="Открыть в проводнике",
                   command=self._open_in_explorer).pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    def _refresh(self):
        self._status_var.set("Обновление…")
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self):
        try:
            if not self.db_path.exists():
                self.window.after(0, lambda: self._status_var.set(
                    "БД не найдена. Выполните синхронизацию."))
                return

            days = self._days_var.get()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()

            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()
            c.execute("""
                SELECT added_date, author, series, title, file_path
                FROM books
                WHERE added_date >= ?
                ORDER BY added_date DESC
            """, (cutoff,))
            rows = c.fetchall()
            conn.close()

            self.window.after(0, lambda: self._populate(rows, days))
        except Exception as e:
            msg = f"Ошибка: {e}"
            self.window.after(0, lambda: self._status_var.set(msg))

    def _populate(self, rows, days):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            # Format date: keep only YYYY-MM-DD HH:MM
            date_str = str(row[0])[:16] if row[0] else ''
            self.tree.insert('', tk.END, values=(date_str,) + tuple(row[1:]))
        self._status_var.set(
            f"Новых книг за {days} дней: {len(rows)}"
        )

    def _sort_by(self, col):
        data = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children()]
        data.sort()
        for idx, (_, iid) in enumerate(data):
            self.tree.move(iid, '', idx)

    def _on_double_click(self, _event):
        self._open_in_explorer()

    def _open_in_explorer(self):
        sel = self.tree.selection()
        if not sel:
            return
        file_path = self.tree.set(sel[0], 'file_path')
        if not file_path:
            return
        library_path = ''
        if self.settings:
            library_path = self.settings.get_library_path() or ''
        full_path = Path(library_path) / file_path if library_path else Path(file_path)
        folder = full_path.parent
        if folder.exists():
            subprocess.Popen(['explorer', str(folder)])
