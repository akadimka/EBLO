"""Window: Series with gaps — finds missing sequence numbers in book series."""
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
import threading
from pathlib import Path

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager


class SeriesGapsWindow:
    """Окно отчёта о пропущенных номерах в сериях."""

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.settings = settings_manager
        self.db_path = Path(__file__).parent / '.library_cache.db'

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Серии с пробелами")
        self.window.minsize(750, 450)
        if parent:
            self.window.transient(parent)

        if settings_manager:
            setup_window_persistence(self.window, 'series_gaps', settings_manager, '900x550+160+120')
        else:
            self.window.geometry('900x550')

        self._build_ui()
        threading.Thread(target=self._load_data, daemon=True).start()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Controls row
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(ctrl, text="Мин. книг в серии:").pack(side=tk.LEFT)
        self._min_books_var = tk.IntVar(value=2)
        ttk.Spinbox(ctrl, from_=2, to=100, width=5,
                    textvariable=self._min_books_var).pack(side=tk.LEFT, padx=4)
        ttk.Button(ctrl, text="Обновить", command=self._refresh).pack(side=tk.LEFT, padx=8)
        self._status_var = tk.StringVar(value="Загрузка…")
        ttk.Label(ctrl, textvariable=self._status_var, foreground="gray").pack(side=tk.LEFT, padx=8)

        # Table
        table_frame = ttk.Frame(main)
        table_frame.pack(fill=tk.BOTH, expand=True)
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        cols = ("author", "series", "have", "missing")
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings')
        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        headers = {"author": "Автор", "series": "Серия",
                   "have": "Есть (номера)", "missing": "Пропущено"}
        widths  = {"author": 180, "series": 220, "have": 200, "missing": 180}
        for col in cols:
            self.tree.heading(col, text=headers[col])
            self.tree.column(col, width=widths[col], minwidth=60)

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')

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

            min_books = self._min_books_var.get()
            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            # Migrate older DB if needed
            try:
                c.execute("ALTER TABLE books ADD COLUMN series_number TEXT DEFAULT ''")
                conn.commit()
            except Exception:
                pass

            c.execute("""
                SELECT author, series, series_number
                FROM books
                WHERE series != '' AND series IS NOT NULL
                ORDER BY author, series
            """)
            rows = c.fetchall()
            conn.close()

            # Group by (author, series)
            from collections import defaultdict
            groups = defaultdict(list)
            for author, series, num in rows:
                groups[(author or '', series or '')].append(num or '')

            results = []
            for (author, series), nums in groups.items():
                if len(nums) < min_books:
                    continue
                int_nums = []
                for n in nums:
                    try:
                        int_nums.append(int(n.strip()))
                    except (ValueError, AttributeError):
                        pass
                if not int_nums:
                    continue
                int_nums_sorted = sorted(set(int_nums))
                expected = list(range(int_nums_sorted[0], int_nums_sorted[-1] + 1))
                missing = [x for x in expected if x not in set(int_nums_sorted)]
                if missing:
                    have_str = ', '.join(str(x) for x in int_nums_sorted)
                    missing_str = ', '.join(str(x) for x in missing)
                    results.append((author, series, have_str, missing_str))

            results.sort(key=lambda r: (r[0], r[1]))
            self.window.after(0, lambda: self._populate(results))

        except Exception as e:
            msg = f"Ошибка: {e}"
            self.window.after(0, lambda: self._status_var.set(msg))

    def _populate(self, results):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in results:
            self.tree.insert('', tk.END, values=row)
        count = len(results)
        self._status_var.set(
            f"Серий с пробелами: {count}" if count else "Пробелов не найдено — библиотека полная!"
        )
