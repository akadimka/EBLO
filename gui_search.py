"""GUI window for searching books in the SQLite DB by author, title, series, genre.

Double-clicking a result opens File Explorer at the book's folder.
"""
import tkinter as tk
from tkinter import ttk
import sqlite3
import subprocess
import threading
from pathlib import Path

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager


class SearchWindow:
    """Окно поиска по метаданным библиотеки."""

    COLUMNS = ("author", "series", "series_number", "title", "genre", "file_path")
    COL_HEADERS = {
        "author": "Автор", "series": "Серия", "series_number": "#",
        "title": "Название", "genre": "Жанр", "file_path": "Путь"
    }
    COL_WIDTHS = {
        "author": 160, "series": 160, "series_number": 40,
        "title": 200, "genre": 100, "file_path": 300
    }

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.settings = settings_manager
        self.db_path = Path(__file__).parent / '.library_cache.db'

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.withdraw()  # скрываем до позиционирования
        self.window.title("Поиск по библиотеке")
        self.window.minsize(800, 500)

        if settings_manager:
            setup_window_persistence(self.window, 'search', settings_manager,
                                     '1100x600+150+100', parent_window=parent)
        else:
            self.window.geometry('1100x600')

        self._build_ui()
        # Bind Enter key to search
        self.window.bind('<Return>', lambda _: self._search())

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Search form
        form = ttk.LabelFrame(main, text="Условия поиска", padding=6)
        form.pack(fill=tk.X, pady=(0, 8))

        labels = [("Автор:", 0), ("Название:", 1), ("Серия:", 2), ("Жанр:", 3)]
        self._author_var = tk.StringVar()
        self._title_var  = tk.StringVar()
        self._series_var = tk.StringVar()
        self._genre_var  = tk.StringVar()
        fields = [self._author_var, self._title_var, self._series_var, self._genre_var]

        for (lbl, col), var in zip(labels, fields):
            ttk.Label(form, text=lbl).grid(row=0, column=col*2, sticky='e', padx=(8, 2))
            ent = ttk.Entry(form, textvariable=var, width=22)
            ent.grid(row=0, column=col*2+1, sticky='ew', padx=(0, 8))
            form.columnconfigure(col*2+1, weight=1)

        btn_row = ttk.Frame(form)
        btn_row.grid(row=1, column=0, columnspan=8, sticky='w', pady=(6, 0))
        ttk.Button(btn_row, text="Найти (Enter)", command=self._search).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Сбросить", command=self._clear).pack(side=tk.LEFT, padx=4)
        self._status_var = tk.StringVar(value='')
        ttk.Label(btn_row, textvariable=self._status_var,
                  foreground='gray').pack(side=tk.LEFT, padx=10)

        # Results table
        table_frame = ttk.Frame(main)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, columns=self.COLUMNS, show='headings')
        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        for col in self.COLUMNS:
            self.tree.heading(col, text=self.COL_HEADERS[col],
                              command=lambda c=col: self._sort_by(c))
            self.tree.column(col, width=self.COL_WIDTHS[col], minwidth=40)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        self.tree.bind('<Double-Button-1>', self._on_double_click)

        # Bottom buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="Открыть в проводнике",
                   command=self._open_in_explorer).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Рейтинг (Fantlab)",
                   command=self._lookup_fantlab).pack(side=tk.LEFT, padx=4)

    # ------------------------------------------------------------------
    def _clear(self):
        for var in (self._author_var, self._title_var,
                    self._series_var, self._genre_var):
            var.set('')
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._status_var.set('')

    def _search(self):
        if not self.db_path.exists():
            self._status_var.set("БД не найдена. Выполните синхронизацию.")
            return
        self._status_var.set("Поиск…")
        threading.Thread(target=self._run_search, daemon=True).start()

    def _run_search(self):
        try:
            author = self._author_var.get().strip()
            title  = self._title_var.get().strip()
            series = self._series_var.get().strip()
            genre  = self._genre_var.get().strip()

            conditions = []
            params = []
            if author:
                conditions.append("author LIKE ?")
                params.append(f'%{author}%')
            if title:
                conditions.append("title LIKE ?")
                params.append(f'%{title}%')
            if series:
                conditions.append("series LIKE ?")
                params.append(f'%{series}%')
            if genre:
                conditions.append("genre LIKE ?")
                params.append(f'%{genre}%')

            where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            sql = f"""
                SELECT author, series, series_number, title, genre, file_path
                FROM books {where}
                ORDER BY author, series,
                    CAST(NULLIF(series_number,'') AS INTEGER),
                    title
                LIMIT 2000
            """
            conn = sqlite3.connect(str(self.db_path))
            try:
                c = conn.cursor()
                c.execute("ALTER TABLE books ADD COLUMN series_number TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                pass
            c.execute(sql, params)
            rows = c.fetchall()
            conn.close()

            self.window.after(0, lambda: self._populate(rows))
        except Exception as e:
            msg = f"Ошибка: {e}"
            self.window.after(0, lambda: self._status_var.set(msg))

    def _populate(self, rows):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert('', tk.END, values=[str(v) if v is not None else '' for v in row])
        self._status_var.set(f"Найдено: {len(rows)}" + (" (показаны первые 2000)" if len(rows) == 2000 else ""))

    def _sort_by(self, col):
        data = [(self.tree.set(iid, col), iid) for iid in self.tree.get_children()]
        data.sort(key=lambda x: x[0].lower())
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
        full = Path(library_path) / file_path if library_path else Path(file_path)
        folder = full.parent
        if folder.exists():
            subprocess.Popen(['explorer', str(folder)])

    def _lookup_fantlab(self):
        sel = self.tree.selection()
        if not sel:
            return
        title  = self.tree.set(sel[0], 'title')
        author = self.tree.set(sel[0], 'author')
        try:
            from fantlab_client import FantlabWindow
        except ImportError:
            from .fantlab_client import FantlabWindow
        FantlabWindow(parent=self.window, title=title, author=author)
