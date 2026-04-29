"""Fantlab.ru API client + lookup window.

Public REST API (no key required):
  Search: GET https://api.fantlab.ru/search-works?q=QUERY&page=1&size=10
  Work:   GET https://api.fantlab.ru/work/{id}

Search returns matches[].work_id, rusname/fullname, autor_rusname,
  midmark[], markcount, rating[].
Work returns title, rating{rating, true_rating, voters},
  val_midmark, val_midmark_by_weight, val_voters, authors[], work_description.
"""
import json
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from functools import lru_cache
from tkinter import ttk

try:
    from window_persistence import setup_window_persistence
except ImportError:
    from .window_persistence import setup_window_persistence

_BASE = 'https://api.fantlab.ru'
_TIMEOUT = 10

_search_cache: dict = {}
_work_cache: dict = {}


def _http_get(url: str) -> dict | None:
    try:
        req = urllib.request.Request(
            url, headers={'User-Agent': 'fb2parser/1.0 (library organizer)'}
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None


def search_works(title: str, author: str = '') -> list:
    """Search Fantlab by title + author. Returns list of result dicts."""
    query = ' '.join(filter(None, [title, author])).strip()
    if not query:
        return []
    if query in _search_cache:
        return _search_cache[query]

    url = f'{_BASE}/search-works?q={urllib.parse.quote(query)}&page=1&size=10'
    raw = _http_get(url)
    if not raw:
        return []

    results = []
    for item in (raw.get('matches') or raw.get('works') or [])[:20]:
        midmark = item.get('midmark') or []
        rating_val = midmark[0] if midmark else ''
        results.append({
            'work_id':    item.get('work_id', ''),
            'name':       item.get('rusname') or item.get('fullname', '').strip(),
            'author':     item.get('autor_rusname') or item.get('all_autor_rusname', ''),
            'year':       item.get('year', ''),
            'rating':     f'{rating_val:.2f}' if isinstance(rating_val, float) else rating_val,
            'votes':      item.get('markcount', ''),
            'work_type':  item.get('name_eng', ''),
        })
    _search_cache[query] = results
    return results


def get_work_details(work_id) -> dict:
    """Fetch full details for one work. Returns dict with rating, description, etc."""
    if not work_id:
        return {}
    key = str(work_id)
    if key in _work_cache:
        return _work_cache[key]

    raw = _http_get(f'{_BASE}/work/{work_id}')
    if not raw:
        return {}

    rating_block = raw.get('rating') or {}
    authors = raw.get('authors') or []
    author_str = ', '.join(a.get('name', '') for a in authors if a.get('type') == 'autor')

    result = {
        'work_id':     raw.get('work_id', work_id),
        'name':        raw.get('title', ''),
        'author':      author_str,
        'year':        '',
        'work_type':   raw.get('work_type_name', ''),
        'rating':      rating_block.get('rating', ''),
        'true_rating': rating_block.get('true_rating', ''),
        'votes':       rating_block.get('voters', ''),
        'description': (raw.get('work_description') or '').strip()[:600],
    }
    _work_cache[key] = result
    return result


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class FantlabWindow:
    """Окно поиска рейтингов книг на Fantlab.ru."""

    def __init__(self, parent=None, title: str = '', author: str = ''):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title('Рейтинг на Fantlab.ru')
        self.window.minsize(750, 480)
        if parent:
            self.window.transient(parent)
        self.window.geometry('860x540')
        self._build_ui(title, author)
        if title or author:
            self.window.after(100, self._search)

    def _build_ui(self, default_title: str, default_author: str):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Search form
        form = ttk.LabelFrame(main, text='Поиск', padding=6)
        form.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(form, text='Название:').grid(row=0, column=0, sticky='e', padx=4)
        self._title_var = tk.StringVar(value=default_title)
        ttk.Entry(form, textvariable=self._title_var, width=45).grid(
            row=0, column=1, sticky='ew', padx=4)
        ttk.Label(form, text='Автор:').grid(row=0, column=2, sticky='e', padx=4)
        self._author_var = tk.StringVar(value=default_author)
        ttk.Entry(form, textvariable=self._author_var, width=30).grid(
            row=0, column=3, sticky='ew', padx=4)
        ttk.Button(form, text='Найти', command=self._search).grid(row=0, column=4, padx=8)
        form.columnconfigure(1, weight=2)
        form.columnconfigure(3, weight=1)

        self._status_var = tk.StringVar()
        ttk.Label(main, textvariable=self._status_var, foreground='gray').pack(
            fill=tk.X, pady=(0, 2))

        # Results table
        rf = ttk.Frame(main)
        rf.pack(fill=tk.BOTH, expand=True)
        rf.rowconfigure(0, weight=3)
        rf.rowconfigure(2, weight=1)
        rf.columnconfigure(0, weight=1)

        cols = ('name', 'author', 'work_type', 'year', 'rating', 'votes')
        heads = {'name': 'Название', 'author': 'Автор', 'work_type': 'Тип',
                 'year': 'Год', 'rating': 'Рейтинг', 'votes': 'Голосов'}
        widths = {'name': 250, 'author': 170, 'work_type': 80,
                  'year': 55, 'rating': 70, 'votes': 70}

        self._tree = ttk.Treeview(rf, columns=cols, show='headings', height=8)
        vsb = ttk.Scrollbar(rf, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        for col in cols:
            self._tree.heading(col, text=heads[col])
            self._tree.column(col, width=widths[col], minwidth=40)
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        ttk.Separator(rf, orient='horizontal').grid(
            row=1, column=0, columnspan=2, sticky='ew', pady=4)

        # Detail pane
        df = ttk.LabelFrame(rf, text='Подробности', padding=6)
        df.grid(row=2, column=0, columnspan=2, sticky='nsew', pady=(0, 4))
        df.rowconfigure(0, weight=1)
        df.columnconfigure(0, weight=1)
        self._detail = tk.Text(df, height=7, wrap='word', state='disabled', bg='#f5f5f5')
        dsb = ttk.Scrollbar(df, orient=tk.VERTICAL, command=self._detail.yview)
        self._detail.configure(yscrollcommand=dsb.set)
        self._detail.grid(row=0, column=0, sticky='nsew')
        dsb.grid(row=0, column=1, sticky='ns')

        self._tree.bind('<<TreeviewSelect>>', self._on_select)

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text='Открыть на Fantlab.ru',
                   command=self._open_in_browser).pack(side=tk.LEFT, padx=4)

        self._work_ids: dict = {}

    def _search(self):
        title  = self._title_var.get().strip()
        author = self._author_var.get().strip()
        if not title and not author:
            return
        self._status_var.set('Поиск на Fantlab.ru…')
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._work_ids.clear()
        self._set_detail('')
        threading.Thread(target=self._run_search, args=(title, author), daemon=True).start()

    def _run_search(self, title: str, author: str):
        results = search_works(title, author)
        self.window.after(0, lambda: self._populate(results))

    def _populate(self, results: list):
        for r in results:
            iid = self._tree.insert('', tk.END, values=(
                r['name'], r['author'], r['work_type'],
                r['year'], r['rating'], r['votes'],
            ))
            self._work_ids[iid] = r['work_id']
        self._status_var.set(f"Найдено: {len(results)}" if results else 'Ничего не найдено')

    def _on_select(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        work_id = self._work_ids.get(sel[0])
        if not work_id:
            return
        self._status_var.set('Загрузка подробностей…')
        threading.Thread(target=self._load_details, args=(work_id,), daemon=True).start()

    def _load_details(self, work_id):
        det = get_work_details(work_id)
        self.window.after(0, lambda: self._show_details(det))

    def _show_details(self, det: dict):
        if not det:
            self._set_detail('Нет данных')
            return
        lines = [
            f"Название: {det.get('name', '')}",
            f"Автор: {det.get('author', '')}",
            f"Тип: {det.get('work_type', '')}",
            f"Рейтинг: {det.get('rating', '')}  (честный: {det.get('true_rating', '')})  Голосов: {det.get('votes', '')}",
            '',
            det.get('description', ''),
        ]
        self._set_detail('\n'.join(lines))
        self._status_var.set('')

    def _set_detail(self, text: str):
        self._detail.configure(state='normal')
        self._detail.delete('1.0', tk.END)
        if text:
            self._detail.insert(tk.END, text)
        self._detail.configure(state='disabled')

    def _open_in_browser(self):
        sel = self._tree.selection()
        if not sel:
            return
        work_id = self._work_ids.get(sel[0])
        if work_id:
            webbrowser.open(f'https://fantlab.ru/work{work_id}')
