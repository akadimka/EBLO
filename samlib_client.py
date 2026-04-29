"""Samlib.ru scraper — поиск рейтингов книг на samlib.ru.

Самиздат не имеет публичного API. Данные получаются парсингом HTML.
Кодировка сайта: cp1251.

Поиск авторов:
  POST https://samlib.ru/cgi-bin/seek
  Параметры: FIND=<запрос cp1251>, PLACE=index, JANR=0
  → HTML со списком авторов; ссылки вида /к/kulakow_a_i/

Список книг автора с рейтингами:
  GET https://samlib.ru/{letter}/{author_slug}/indexvote.shtml
  → HTML; рейтинг в формате Оценка:<b>7.31*549</b>

Рейтинг возвращается как (score, votes): например (7.31, 549).
"""
import re
import threading
import tkinter as tk
import urllib.parse
import urllib.request
import urllib.error
from tkinter import ttk

_BASE = 'https://samlib.ru'
_TIMEOUT = 10
_ENCODING = 'cp1251'

_search_cache: dict = {}   # query -> list of author dicts
_books_cache: dict = {}    # author_url -> list of book dicts


def _fetch(url: str, post_data: bytes | None = None) -> str | None:
    try:
        req = urllib.request.Request(
            url,
            data=post_data,
            headers={
                'User-Agent': 'Mozilla/5.0 (compatible; fb2parser/1.0)',
                'Accept-Charset': 'windows-1251',
            }
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read().decode(_ENCODING, errors='replace')
    except Exception:
        return None


def search_authors(query: str) -> list:
    """Поиск авторов по имени. Возвращает список {'name', 'url', 'slug'}."""
    if not query.strip():
        return []
    key = query.strip().lower()
    if key in _search_cache:
        return _search_cache[key]

    post_data = urllib.parse.urlencode({
        'FIND': query,
        'PLACE': 'index',
        'JANR': '0',
        'submit': 'Найти',
    }, encoding=_ENCODING).encode(_ENCODING)

    html = _fetch(f'{_BASE}/cgi-bin/seek', post_data=post_data)
    if not html:
        return []

    # Author links look like: href="/к/kulakow_a_i/" or href=/k/kulakow_a_i/
    results = []
    seen = set()
    for m in re.finditer(
        r'href=["\']?(/[a-zа-яё]/([^/"\'\s>]+)/)["\']?>([^<]+)</a>',
        html, re.IGNORECASE
    ):
        url_path, slug, name = m.group(1), m.group(2), m.group(3).strip()
        if slug in seen or not name or len(name) < 3:
            continue
        seen.add(slug)
        results.append({'name': name, 'url': url_path, 'slug': slug})

    _search_cache[key] = results
    return results


def get_author_books(author_url: str) -> list:
    """Получить список книг автора с рейтингами.

    author_url: путь вида /к/kulakow_a_i/
    Возвращает список {'title', 'url', 'score', 'votes', 'size', 'genre'}.
    """
    if author_url in _books_cache:
        return _books_cache[author_url]

    # indexvote.shtml shows all works with ratings
    url = f'{_BASE}{author_url.rstrip("/")}' + '/indexvote.shtml'
    html = _fetch(url)
    if not html:
        return []

    books = []
    # Pattern: <A HREF=book.shtml><b>Title</b></A> ... <b>554k</b> ... Оценка:<b>7.31*549</b>
    for m in re.finditer(
        r'<A HREF=([^\s>]+\.shtml)><b>([^<]+)</b></A>'
        r'.*?<b>([\d.]+k)</b>'
        r'.*?(?:Оценка:<b>([\d.]+)\*(\d+)</b>)?',
        html, re.IGNORECASE | re.DOTALL
    ):
        book_path, title, size = m.group(1), m.group(2).strip(), m.group(3)
        score = m.group(4) or ''
        votes = m.group(5) or ''
        # resolve relative url
        if not book_path.startswith('/'):
            book_path = author_url.rstrip('/') + '/' + book_path
        books.append({
            'title': title,
            'url':   book_path,
            'score': score,
            'votes': votes,
            'size':  size,
        })

    _books_cache[author_url] = books
    return books


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class SamlibWindow:
    """Окно поиска рейтингов книг на samlib.ru."""

    def __init__(self, parent=None, title: str = '', author: str = ''):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title('Рейтинг на Samlib.ru')
        self.window.minsize(750, 500)
        if parent:
            self.window.transient(parent)
        self.window.geometry('900x580')
        self._build_ui(author, title)
        if author or title:
            self.window.after(100, self._search_authors)

    def _build_ui(self, default_author: str, default_title: str):
        main = ttk.Frame(self.window, padding=8)
        main.pack(fill=tk.BOTH, expand=True)

        # Search form
        form = ttk.LabelFrame(main, text='Поиск автора', padding=6)
        form.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(form, text='Автор:').grid(row=0, column=0, sticky='e', padx=4)
        self._author_var = tk.StringVar(value=default_author)
        ttk.Entry(form, textvariable=self._author_var, width=40).grid(
            row=0, column=1, sticky='ew', padx=4)
        ttk.Button(form, text='Найти', command=self._search_authors).grid(
            row=0, column=2, padx=8)
        form.columnconfigure(1, weight=1)

        self._status_var = tk.StringVar()
        ttk.Label(main, textvariable=self._status_var, foreground='gray').pack(
            fill=tk.X, pady=(0, 2))

        paned = ttk.PanedWindow(main, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Left: authors list
        left = ttk.LabelFrame(paned, text='Авторы', padding=4)
        paned.add(left, weight=1)
        self._authors_lb = tk.Listbox(left, width=28, exportselection=False)
        asb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self._authors_lb.yview)
        self._authors_lb.configure(yscrollcommand=asb.set)
        self._authors_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        asb.pack(side=tk.RIGHT, fill=tk.Y)
        self._authors_lb.bind('<<ListboxSelect>>', self._on_author_select)

        # Right: books list
        right = ttk.LabelFrame(paned, text='Книги', padding=4)
        paned.add(right, weight=3)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        cols = ('title', 'score', 'votes', 'size')
        heads = {'title': 'Название', 'score': 'Оценка', 'votes': 'Голосов', 'size': 'Размер'}
        widths = {'title': 340, 'score': 70, 'votes': 80, 'size': 60}

        self._books_tree = ttk.Treeview(right, columns=cols, show='headings', height=16)
        bsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self._books_tree.yview)
        self._books_tree.configure(yscrollcommand=bsb.set)
        for col in cols:
            self._books_tree.heading(col, text=heads[col],
                                     command=lambda c=col: self._sort(c))
            self._books_tree.column(col, width=widths[col], minwidth=40)
        self._books_tree.grid(row=0, column=0, sticky='nsew')
        bsb.grid(row=0, column=1, sticky='ns')

        # Filter by title
        filter_frame = ttk.Frame(main)
        filter_frame.pack(fill=tk.X, pady=(4, 0))
        ttk.Label(filter_frame, text='Фильтр по названию:').pack(side=tk.LEFT, padx=4)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._apply_filter())
        ttk.Entry(filter_frame, textvariable=self._filter_var, width=40).pack(
            side=tk.LEFT, padx=4)
        ttk.Button(filter_frame, text='Открыть на Samlib.ru',
                   command=self._open_in_browser).pack(side=tk.RIGHT, padx=4)

        self._author_data: list = []
        self._books_data: list = []
        self._sort_col = 'score'
        self._sort_rev = True
        self._default_title = default_title

    # ------------------------------------------------------------------
    def _search_authors(self):
        query = self._author_var.get().strip()
        if not query:
            return
        self._status_var.set('Поиск авторов на Samlib.ru…')
        self._authors_lb.delete(0, tk.END)
        self._books_tree.delete(*self._books_tree.get_children())
        self._author_data.clear()
        threading.Thread(target=self._run_search, args=(query,), daemon=True).start()

    def _run_search(self, query: str):
        results = search_authors(query)
        self.window.after(0, lambda: self._populate_authors(results))

    def _populate_authors(self, results: list):
        self._author_data = results
        for a in results:
            self._authors_lb.insert(tk.END, a['name'])
        if results:
            self._status_var.set(f'Найдено авторов: {len(results)}')
            # auto-select first
            self._authors_lb.selection_set(0)
            self._authors_lb.event_generate('<<ListboxSelect>>')
        else:
            self._status_var.set('Авторы не найдены')

    def _on_author_select(self, _event):
        sel = self._authors_lb.curselection()
        if not sel:
            return
        author = self._author_data[sel[0]]
        self._status_var.set(f'Загрузка книг: {author["name"]}…')
        self._books_tree.delete(*self._books_tree.get_children())
        self._books_data.clear()
        threading.Thread(
            target=self._run_books, args=(author['url'],), daemon=True
        ).start()

    def _run_books(self, url: str):
        books = get_author_books(url)
        self.window.after(0, lambda: self._populate_books(books))

    def _populate_books(self, books: list):
        self._books_data = books
        self._apply_filter()
        self._status_var.set(f'Книг: {len(books)}')

    def _apply_filter(self):
        flt = self._filter_var.get().strip().lower()
        self._books_tree.delete(*self._books_tree.get_children())
        data = self._books_data
        if flt:
            data = [b for b in data if flt in b['title'].lower()]
        # sort
        def sort_key(b):
            val = b.get(self._sort_col, '')
            try:
                return float(val)
            except (ValueError, TypeError):
                return val or ''
        data = sorted(data, key=sort_key, reverse=self._sort_rev)
        for b in data:
            self._books_tree.insert('', tk.END, values=(
                b['title'], b['score'], b['votes'], b['size']
            ), tags=(b['url'],))
        # auto-filter by default title
        if self._default_title and not flt:
            self._filter_var.set(self._default_title)
            self._default_title = ''

    def _sort(self, col: str):
        if self._sort_col == col:
            self._sort_rev = not self._sort_rev
        else:
            self._sort_col = col
            self._sort_rev = col in ('score', 'votes')
        self._apply_filter()

    def _open_in_browser(self):
        import webbrowser
        sel = self._books_tree.selection()
        if sel:
            tags = self._books_tree.item(sel[0], 'tags')
            if tags:
                url_path = tags[0]
                if not url_path.startswith('http'):
                    url_path = _BASE + url_path
                webbrowser.open(url_path)
        else:
            # open author page
            idx = self._authors_lb.curselection()
            if idx:
                author = self._author_data[idx[0]]
                webbrowser.open(_BASE + author['url'])
