"""Fantlab.ru API client + lookup window.

Uses the unofficial (but publicly accessible) Fantlab REST API:
  Search: https://api.fantlab.ru/search-works?q=QUERY
  Work:   https://api.fantlab.ru/work/ID

No API key is required for these endpoints.
Results are cached in memory to avoid duplicate network calls.
"""
import tkinter as tk
from tkinter import ttk
import json
import threading
import urllib.request
import urllib.parse
import urllib.error
from functools import lru_cache

try:
    from window_persistence import setup_window_persistence
except ImportError:
    from .window_persistence import setup_window_persistence

_BASE = 'https://api.fantlab.ru'
_TIMEOUT = 10  # seconds

# Module-level in-memory cache: query -> list of work dicts
_search_cache: dict = {}
# Module-level rating cache: work_id -> rating dict
_rating_cache: dict = {}


def _http_get(url: str) -> dict | None:
    """Perform an HTTP GET and return parsed JSON, or None on error."""
    try:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'fb2parser/1.0 (library organizer)'}
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = resp.read()
            return json.loads(data.decode('utf-8'))
    except urllib.error.HTTPError as e:
        return None
    except Exception:
        return None


def search_works(title: str, author: str = '') -> list:
    """Search Fantlab for works matching title + author.

    Returns list of dicts with keys: work_id, name, name_orig, author_name,
    work_type_name, year, rating, votes.
    """
    query = ' '.join(filter(None, [title, author])).strip()
    if not query:
        return []
    if query in _search_cache:
        return _search_cache[query]

    encoded = urllib.parse.quote(query)
    url = f'{_BASE}/search-works?q={encoded}&page=1&size=10'
    raw = _http_get(url)
    if not raw:
        return []

    # Fantlab returns: {"works": [...], "total": N}
    items = raw.get('works') or raw.get('matches') or []
    results = []
    for item in items[:20]:
        results.append({
            'work_id':       item.get('work_id') or item.get('id', ''),
            'name':          item.get('name', ''),
            'name_orig':     item.get('name_orig', ''),
            'author_name':   item.get('author_name', ''),
            'work_type':     item.get('work_type_name', item.get('work_type', '')),
            'year':          item.get('year', ''),
            'rating':        item.get('rating', {}).get('rating', '') if isinstance(item.get('rating'), dict)
                             else item.get('rating', ''),
            'votes':         item.get('rating', {}).get('votes', '') if isinstance(item.get('rating'), dict)
                             else item.get('votes', ''),
        })
    _search_cache[query] = results
    return results


def get_work_details(work_id) -> dict:
    """Fetch detailed info for one work from Fantlab.

    Returns dict with keys: work_id, name, rating, votes, reviews,
    description, year, author_name, series_name, genres.
    """
    if not work_id:
        return {}
    key = str(work_id)
    if key in _rating_cache:
        return _rating_cache[key]

    url = f'{_BASE}/work/{work_id}'
    raw = _http_get(url)
    if not raw:
        return {}

    rt = raw.get('rating') or {}
    result = {
        'work_id':     raw.get('work_id', work_id),
        'name':        raw.get('name', ''),
        'name_orig':   raw.get('name_orig', ''),
        'year':        raw.get('year', ''),
        'author_name': raw.get('authors', [{}])[0].get('name', '')
                       if raw.get('authors') else raw.get('author_name', ''),
        'work_type':   raw.get('work_type_name', ''),
        'rating':      rt.get('rating', ''),
        'votes':       rt.get('votes', ''),
        'reviews':     raw.get('stat', {}).get('response_count', ''),
        'description': raw.get('description', '').strip()[:500],
        'genres':      ', '.join(g.get('name', '') for g in (raw.get('genres') or [])[:5]),
    }
    _rating_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# GUI Window
# ---------------------------------------------------------------------------

class FantlabWindow:
    """Окно поиска рейтингов книг на Fantlab.ru."""

    def __init__(self, parent=None, title: str = '', author: str = ''):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Рейтинг на Fantlab.ru")
        self.window.minsize(750, 500)
        if parent:
            self.window.transient(parent)
        self.window.geometry('850x550')

        self._build_ui(title, author)
        if title or author:
            # Auto-search on open
            self.window.after(100, self._search)

    def _build_ui(self, default_title: str, default_author: str):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Search form
        form = ttk.LabelFrame(main, text="Поиск", padding=6)
        form.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(form, text="Название:").grid(row=0, column=0, sticky='e', padx=4)
        self._title_var = tk.StringVar(value=default_title)
        ttk.Entry(form, textvariable=self._title_var, width=45).grid(
            row=0, column=1, sticky='ew', padx=4)
        ttk.Label(form, text="Автор:").grid(row=0, column=2, sticky='e', padx=4)
        self._author_var = tk.StringVar(value=default_author)
        ttk.Entry(form, textvariable=self._author_var, width=30).grid(
            row=0, column=3, sticky='ew', padx=4)
        ttk.Button(form, text="Найти", command=self._search).grid(
            row=0, column=4, padx=8)
        form.columnconfigure(1, weight=2)
        form.columnconfigure(3, weight=1)

        self._status_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self._status_var,
                  foreground='gray').pack(fill=tk.X, pady=(0, 2))

        # Results table
        results_frame = ttk.Frame(main)
        results_frame.pack(fill=tk.BOTH, expand=True)
        results_frame.rowconfigure(0, weight=3)
        results_frame.rowconfigure(2, weight=1)
        results_frame.columnconfigure(0, weight=1)

        cols = ("name", "author_name", "work_type", "year", "rating", "votes")
        headers = {"name": "Название", "author_name": "Автор",
                   "work_type": "Тип", "year": "Год",
                   "rating": "Рейтинг", "votes": "Голосов"}
        widths = {"name": 240, "author_name": 160, "work_type": 80,
                  "year": 60, "rating": 70, "votes": 70}

        self._results_tree = ttk.Treeview(results_frame, columns=cols, show='headings',
                                          height=8)
        vsb = ttk.Scrollbar(results_frame, orient=tk.VERTICAL,
                            command=self._results_tree.yview)
        self._results_tree.configure(yscrollcommand=vsb.set)
        for col in cols:
            self._results_tree.heading(col, text=headers[col])
            self._results_tree.column(col, width=widths[col], minwidth=40)
        self._results_tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        ttk.Separator(results_frame, orient='horizontal').grid(
            row=1, column=0, columnspan=2, sticky='ew', pady=4)

        # Detail pane
        detail_frame = ttk.LabelFrame(results_frame, text="Подробности",
                                      padding=6)
        detail_frame.grid(row=2, column=0, columnspan=2, sticky='nsew', pady=(0, 4))
        detail_frame.rowconfigure(0, weight=1)
        detail_frame.columnconfigure(0, weight=1)

        self._detail_text = tk.Text(detail_frame, height=7, wrap='word',
                                    state='disabled', bg='#f5f5f5')
        dsb = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL,
                            command=self._detail_text.yview)
        self._detail_text.configure(yscrollcommand=dsb.set)
        self._detail_text.grid(row=0, column=0, sticky='nsew')
        dsb.grid(row=0, column=1, sticky='ns')

        self._results_tree.bind('<<TreeviewSelect>>', self._on_select)

        # Open on Fantlab button
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Открыть на Fantlab.ru",
                   command=self._open_in_browser).pack(side=tk.LEFT, padx=4)

        self._work_ids = {}  # iid -> work_id

    # ------------------------------------------------------------------
    def _search(self):
        title  = self._title_var.get().strip()
        author = self._author_var.get().strip()
        if not title and not author:
            return
        self._status_var.set("Поиск на Fantlab.ru…")
        for item in self._results_tree.get_children():
            self._results_tree.delete(item)
        self._work_ids.clear()
        self._clear_detail()
        threading.Thread(target=self._run_search, args=(title, author), daemon=True).start()

    def _run_search(self, title: str, author: str):
        results = search_works(title, author)
        self.window.after(0, lambda: self._populate_results(results))

    def _populate_results(self, results: list):
        for r in results:
            iid = self._results_tree.insert('', tk.END, values=(
                r['name'], r['author_name'], r['work_type'],
                r['year'], r['rating'], r['votes']
            ))
            self._work_ids[iid] = r['work_id']
        count = len(results)
        self._status_var.set(f"Найдено: {count}" if count else "Ничего не найдено")

    def _on_select(self, _event):
        sel = self._results_tree.selection()
        if not sel:
            return
        iid = sel[0]
        work_id = self._work_ids.get(iid)
        if not work_id:
            return
        self._status_var.set("Загрузка подробностей…")
        threading.Thread(target=self._load_details, args=(work_id,), daemon=True).start()

    def _load_details(self, work_id):
        det = get_work_details(work_id)
        self.window.after(0, lambda: self._show_details(det))

    def _show_details(self, det: dict):
        self._detail_text.configure(state='normal')
        self._detail_text.delete('1.0', tk.END)
        if not det:
            self._detail_text.insert(tk.END, "Нет данных")
        else:
            lines = [
                f"Название: {det.get('name','')}",
                f"Автор: {det.get('author_name','')}",
                f"Год: {det.get('year','')}   Тип: {det.get('work_type','')}",
                f"Рейтинг: {det.get('rating','')}  Голосов: {det.get('votes','')}  Отзывов: {det.get('reviews','')}",
                f"Жанры: {det.get('genres','')}",
                "",
                det.get('description', ''),
            ]
            self._detail_text.insert(tk.END, '\n'.join(lines))
        self._detail_text.configure(state='disabled')
        self._status_var.set('')

    def _clear_detail(self):
        self._detail_text.configure(state='normal')
        self._detail_text.delete('1.0', tk.END)
        self._detail_text.configure(state='disabled')

    def _open_in_browser(self):
        sel = self._results_tree.selection()
        if not sel:
            return
        work_id = self._work_ids.get(sel[0])
        if not work_id:
            return
        import webbrowser
        webbrowser.open(f'https://fantlab.ru/work{work_id}')
