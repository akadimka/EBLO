"""Library statistics dashboard window."""
import tkinter as tk
from tkinter import ttk
import sqlite3
from pathlib import Path
import threading

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager


class DashboardWindow:
    """Окно статистики библиотеки."""

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.settings = settings_manager
        self.db_path = Path(__file__).parent / '.library_cache.db'

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Статистика библиотеки")
        self.window.minsize(700, 500)

        if settings_manager:
            setup_window_persistence(self.window, 'dashboard', settings_manager, '800x600+150+100')
        else:
            self.window.geometry('800x600')

        self._build_ui()
        # Load data in background so the window opens instantly
        threading.Thread(target=self._load_data, daemon=True).start()

    # ------------------------------------------------------------------
    def _build_ui(self):
        main = ttk.Frame(self.window, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Summary cards row
        self.cards_frame = ttk.LabelFrame(main, text="Общая статистика", padding=8)
        self.cards_frame.pack(fill=tk.X, pady=(0, 8))

        self._stat_vars = {}
        for label, key in [
            ("Книг всего", "total_books"),
            ("Авторов", "total_authors"),
            ("Серий", "total_series"),
            ("Жанров", "total_genres"),
            ("Книг в сериях, %", "pct_in_series"),
            ("С известным автором, %", "pct_known_author"),
        ]:
            frame = ttk.Frame(self.cards_frame, relief="ridge", padding=6)
            frame.pack(side=tk.LEFT, padx=6, expand=True)
            tk.Label(frame, text=label, font=("Arial", 8), fg="gray").pack()
            var = tk.StringVar(value="…")
            tk.Label(frame, textvariable=var, font=("Arial", 14, "bold")).pack()
            self._stat_vars[key] = var

        # Notebook with breakdowns
        nb = ttk.Notebook(main)
        nb.pack(fill=tk.BOTH, expand=True)

        self._top_authors_tree = self._make_tree(nb, "Топ авторов", ["Автор", "Книг"])
        self._top_series_tree  = self._make_tree(nb, "Топ серий",   ["Серия", "Книг"])
        self._genres_tree      = self._make_tree(nb, "Жанры",       ["Жанр", "Книг"])
        self._sources_tree     = self._make_tree(nb, "Источники авторов", ["Источник", "Книг"])

        # Refresh button
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="Обновить", command=self._refresh).pack(side=tk.LEFT)
        self._status_var = tk.StringVar(value="Загрузка…")
        ttk.Label(btn_frame, textvariable=self._status_var, foreground="gray").pack(side=tk.LEFT, padx=10)

    def _make_tree(self, parent_nb, tab_label, columns):
        frame = ttk.Frame(parent_nb, padding=4)
        parent_nb.add(frame, text=tab_label)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        tree = ttk.Treeview(frame, columns=columns, show='headings',
                            yscrollcommand=vsb.set, selectmode='none')
        vsb.config(command=tree.yview)
        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, width=300 if col != "Книг" else 80, minwidth=60)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        return tree

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

            conn = sqlite3.connect(str(self.db_path))
            c = conn.cursor()

            c.execute("SELECT COUNT(*) FROM books")
            total_books = c.fetchone()[0]

            c.execute("SELECT COUNT(DISTINCT author) FROM books WHERE author != '' AND author != '[unknown]'")
            total_authors = c.fetchone()[0]

            c.execute("SELECT COUNT(DISTINCT series) FROM books WHERE series != ''")
            total_series = c.fetchone()[0]

            # Count distinct genres (genre column is comma-separated)
            c.execute("SELECT genre FROM books WHERE genre != ''")
            genre_rows = c.fetchall()
            all_genres = set()
            for (g,) in genre_rows:
                for part in g.split(','):
                    part = part.strip()
                    if part:
                        all_genres.add(part)
            total_genres = len(all_genres)

            # % in series
            c.execute("SELECT COUNT(*) FROM books WHERE series != '' AND series IS NOT NULL")
            in_series = c.fetchone()[0]
            pct_in_series = round(in_series / total_books * 100, 1) if total_books else 0

            # % with known author
            c.execute("SELECT COUNT(*) FROM books WHERE author != '' AND author != '[unknown]' AND author IS NOT NULL")
            known_author = c.fetchone()[0]
            pct_known = round(known_author / total_books * 100, 1) if total_books else 0

            # Top 30 authors
            c.execute("""
                SELECT author, COUNT(*) AS cnt
                FROM books WHERE author != '' AND author != '[unknown]'
                GROUP BY author ORDER BY cnt DESC LIMIT 30
            """)
            top_authors = c.fetchall()

            # Top 30 series
            c.execute("""
                SELECT series, COUNT(*) AS cnt
                FROM books WHERE series != ''
                GROUP BY series ORDER BY cnt DESC LIMIT 30
            """)
            top_series = c.fetchall()

            # Genre distribution (exploded)
            c.execute("SELECT genre FROM books WHERE genre != ''")
            genre_counter = {}
            for (g,) in c.fetchall():
                for part in g.split(','):
                    part = part.strip()
                    if part:
                        genre_counter[part] = genre_counter.get(part, 0) + 1
            genre_dist = sorted(genre_counter.items(), key=lambda x: -x[1])[:50]

            # Author source distribution
            c.execute("""
                SELECT author_source, COUNT(*) FROM books
                GROUP BY author_source ORDER BY COUNT(*) DESC
            """)
            sources = c.fetchall()

            conn.close()

            data = {
                'total_books': total_books,
                'total_authors': total_authors,
                'total_series': total_series,
                'total_genres': total_genres,
                'pct_in_series': pct_in_series,
                'pct_known_author': pct_known,
                'top_authors': top_authors,
                'top_series': top_series,
                'genre_dist': genre_dist,
                'sources': sources,
            }
            self.window.after(0, lambda: self._populate(data))

        except Exception as e:
            msg = f"Ошибка: {e}"
            self.window.after(0, lambda: self._status_var.set(msg))

    def _populate(self, data):
        self._stat_vars['total_books'].set(str(data['total_books']))
        self._stat_vars['total_authors'].set(str(data['total_authors']))
        self._stat_vars['total_series'].set(str(data['total_series']))
        self._stat_vars['total_genres'].set(str(data['total_genres']))
        self._stat_vars['pct_in_series'].set(f"{data['pct_in_series']} %")
        self._stat_vars['pct_known_author'].set(f"{data['pct_known_author']} %")

        self._fill_tree(self._top_authors_tree, data['top_authors'])
        self._fill_tree(self._top_series_tree, data['top_series'])
        self._fill_tree(self._genres_tree, data['genre_dist'])
        self._fill_tree(self._sources_tree, data['sources'])

        self._status_var.set(f"Обновлено. Всего книг: {data['total_books']}")

    @staticmethod
    def _fill_tree(tree, rows):
        for item in tree.get_children():
            tree.delete(item)
        for row in rows:
            tree.insert('', tk.END, values=[str(v) for v in row])
