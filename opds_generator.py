"""OPDS Atom feed generator.

Produces a minimal OPDS 1.2 catalog from the .library_cache.db so that
e-reader apps (Marvin, Kybook, PocketBook) can browse and download books.

Usage (standalone):
    python opds_generator.py --output /path/to/opds --library /path/to/books

The generator writes a small set of static XML files:
    catalog.xml      — root catalog (navigation feed)
    by_author.xml    — alphabetical author index
    by_series.xml    — series index
    author_<hash>.xml — per-author acquisition feed
    series_<hash>.xml — per-series acquisition feed
"""

import hashlib
import os
import sqlite3
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

try:
    from window_persistence import setup_window_persistence
    from settings_manager import SettingsManager
except ImportError:
    from .window_persistence import setup_window_persistence
    from .settings_manager import SettingsManager

OPDS_NS = 'http://www.w3.org/2005/Atom'
DC_NS   = 'http://purl.org/dc/terms/'
OPDS_MIME = 'application/atom+xml;profile=opds-catalog;kind=navigation'
ACQFEED_MIME = 'application/atom+xml;profile=opds-catalog;kind=acquisition'
FB2_MIME = 'application/x-fictionbook+xml'


# ---------------------------------------------------------------------------
# Pure generation logic
# ---------------------------------------------------------------------------

def _slug(text: str) -> str:
    """Short deterministic identifier based on text content."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()[:12]


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _feed_header(feed_id: str, title: str, feed_type: str, updated: str,
                 self_href: str, start_href: str = 'catalog.xml') -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<feed xmlns="{OPDS_NS}" xmlns:dc="{DC_NS}">\n'
        f'  <id>{xml_escape(feed_id)}</id>\n'
        f'  <title>{xml_escape(title)}</title>\n'
        f'  <updated>{updated}</updated>\n'
        f'  <link rel="self" href="{xml_escape(self_href)}" type="{feed_type}"/>\n'
        f'  <link rel="start" href="{xml_escape(start_href)}" type="{OPDS_MIME}"/>\n'
    )


def _nav_entry(uid: str, title: str, subtitle: str, href: str, count: int) -> str:
    return (
        '  <entry>\n'
        f'    <id>{xml_escape(uid)}</id>\n'
        f'    <title>{xml_escape(title)}</title>\n'
        f'    <updated>{_now_rfc3339()}</updated>\n'
        f'    <content type="text">{xml_escape(subtitle)} ({count})</content>\n'
        f'    <link rel="subsection" href="{xml_escape(href)}" type="{ACQFEED_MIME}"/>\n'
        '  </entry>\n'
    )


def _book_entry(book: dict, library_path: str) -> str:
    """Render a single book as an OPDS acquisition entry."""
    uid      = _slug(book['file_path'])
    title    = xml_escape(book['title'] or 'Без названия')
    author   = xml_escape(book['author'] or '')
    series   = book.get('series', '')
    snum     = book.get('series_number', '')
    updated  = (book.get('added_date') or _now_rfc3339())[:19] + 'Z'

    # Build relative download URL using file_path
    download_href = xml_escape(book['file_path'].replace('\\', '/'))

    parts = [
        '  <entry>\n',
        f'    <id>urn:book:{uid}</id>\n',
        f'    <title>{title}</title>\n',
        f'    <updated>{updated}</updated>\n',
    ]
    if author:
        parts.append(f'    <author><name>{author}</name></author>\n')
    if series:
        sinfo = xml_escape(series)
        if snum:
            sinfo += f' #{xml_escape(str(snum))}'
        parts.append(f'    <dc:isPartOf>{sinfo}</dc:isPartOf>\n')
    parts.append(
        f'    <link rel="http://opds-spec.org/acquisition" href="{download_href}"'
        f' type="{FB2_MIME}"/>\n'
    )
    parts.append('  </entry>\n')
    return ''.join(parts)


def generate_opds(db_path: str, output_dir: str, library_path: str,
                  progress_callback=None) -> int:
    """Generate OPDS catalog files.

    Args:
        db_path: Path to .library_cache.db
        output_dir: Directory where XML files will be written
        library_path: Base path to the book library (used for download URLs)
        progress_callback: Optional callable(current, total, msg)

    Returns:
        Total number of books exported.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # Ensure series_number column exists
    try:
        c.execute("ALTER TABLE books ADD COLUMN series_number TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass

    c.execute("""
        SELECT id, author, series, series_number, title, file_path, genre,
               added_date, file_hash
        FROM books ORDER BY author, series, title
    """)
    all_books = [dict(row) for row in c.fetchall()]
    conn.close()

    total = len(all_books)
    if progress_callback:
        progress_callback(0, total, 'Индексация…')

    updated = _now_rfc3339()

    # ---- Root catalog ----
    root_xml = (
        _feed_header('urn:opds:root', 'Каталог библиотеки', OPDS_MIME, updated,
                     'catalog.xml')
        + _nav_entry('urn:opds:by_author', 'По авторам',
                     'Книги сгруппированы по авторам', 'by_author.xml', total)
        + _nav_entry('urn:opds:by_series', 'По сериям',
                     'Книги сгруппированы по сериям', 'by_series.xml', total)
        + '</feed>\n'
    )
    (output / 'catalog.xml').write_text(root_xml, encoding='utf-8')

    # ---- Group by author ----
    from collections import defaultdict
    by_author = defaultdict(list)
    for b in all_books:
        by_author[b['author'] or '(неизвестен)'].append(b)

    author_index = (
        _feed_header('urn:opds:by_author', 'По авторам', OPDS_MIME, updated,
                     'by_author.xml')
    )
    author_files = []
    for author in sorted(by_author.keys()):
        slug = _slug(author)
        fname = f'author_{slug}.xml'
        author_index += _nav_entry(
            f'urn:opds:author:{slug}', author,
            f'Все книги автора', fname, len(by_author[author])
        )
        author_files.append((author, slug, fname, by_author[author]))
    author_index += '</feed>\n'
    (output / 'by_author.xml').write_text(author_index, encoding='utf-8')

    # Per-author acquisition feeds
    for i, (author, slug, fname, books) in enumerate(author_files):
        if progress_callback and i % 10 == 0:
            progress_callback(i, len(author_files), f'Автор: {author[:40]}')
        xml = (
            _feed_header(f'urn:opds:author:{slug}', author, ACQFEED_MIME,
                         updated, fname)
        )
        for b in sorted(books, key=lambda x: (x['series'] or '', x['title'] or '')):
            xml += _book_entry(b, library_path)
        xml += '</feed>\n'
        (output / fname).write_text(xml, encoding='utf-8')

    # ---- Group by series ----
    by_series = defaultdict(list)
    for b in all_books:
        by_series[b['series'] or ''].append(b)

    series_with_name = {k: v for k, v in by_series.items() if k}
    series_index = (
        _feed_header('urn:opds:by_series', 'По сериям', OPDS_MIME, updated,
                     'by_series.xml')
    )
    series_files = []
    for series in sorted(series_with_name.keys()):
        slug = _slug(series)
        fname = f'series_{slug}.xml'
        series_index += _nav_entry(
            f'urn:opds:series:{slug}', series,
            'Все книги серии', fname, len(series_with_name[series])
        )
        series_files.append((series, slug, fname, series_with_name[series]))
    series_index += '</feed>\n'
    (output / 'by_series.xml').write_text(series_index, encoding='utf-8')

    for i, (series, slug, fname, books) in enumerate(series_files):
        if progress_callback and i % 10 == 0:
            progress_callback(i, len(series_files), f'Серия: {series[:40]}')
        xml = (
            _feed_header(f'urn:opds:series:{slug}', series, ACQFEED_MIME,
                         updated, fname)
        )
        for b in sorted(books, key=lambda x: (
            int(x['series_number']) if str(x.get('series_number', '') or '').isdigit() else 999,
            x['title'] or ''
        )):
            xml += _book_entry(b, library_path)
        xml += '</feed>\n'
        (output / fname).write_text(xml, encoding='utf-8')

    if progress_callback:
        progress_callback(total, total, f'Готово: {total} книг')

    return total


# ---------------------------------------------------------------------------
# GUI Window
# ---------------------------------------------------------------------------

class OPDSGeneratorWindow:
    """Окно генерации OPDS-каталога."""

    def __init__(self, parent=None, settings_manager: SettingsManager = None):
        self.settings = settings_manager
        self.db_path = str(Path(__file__).parent / '.library_cache.db')

        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Генератор OPDS-каталога")
        self.window.minsize(600, 300)
        if parent:
            self.window.transient(parent)

        if settings_manager:
            setup_window_persistence(self.window, 'opds_generator', settings_manager, '650x300+160+150')
        else:
            self.window.geometry('650x300')

        self._build_ui()

    def _build_ui(self):
        main = ttk.Frame(self.window, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        # Output directory
        ttk.Label(main, text="Папка вывода OPDS:").grid(
            row=0, column=0, sticky='w', pady=4)
        self._out_var = tk.StringVar(value=str(Path.home() / 'opds_catalog'))
        ttk.Entry(main, textvariable=self._out_var, width=55).grid(
            row=0, column=1, sticky='ew', padx=6)
        ttk.Button(main, text="…",
                   command=self._browse_out).grid(row=0, column=2)

        # Library path
        ttk.Label(main, text="Папка библиотеки:").grid(
            row=1, column=0, sticky='w', pady=4)
        lib = ''
        if self.settings:
            lib = self.settings.get_library_path() or ''
        self._lib_var = tk.StringVar(value=lib)
        ttk.Entry(main, textvariable=self._lib_var, width=55).grid(
            row=1, column=1, sticky='ew', padx=6)
        ttk.Button(main, text="…",
                   command=self._browse_lib).grid(row=1, column=2)

        main.columnconfigure(1, weight=1)

        # Progress
        self._progress_var = tk.StringVar(value='')
        ttk.Label(main, textvariable=self._progress_var,
                  foreground='blue').grid(row=2, column=0, columnspan=3,
                                          sticky='w', pady=8)
        self._pb = ttk.Progressbar(main, mode='determinate', maximum=100)
        self._pb.grid(row=3, column=0, columnspan=3, sticky='ew')

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=4, column=0, columnspan=3, sticky='w', pady=(10, 0))
        self._gen_btn = ttk.Button(btn_frame, text="Создать OPDS",
                                   command=self._generate)
        self._gen_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_frame, text="Открыть папку",
                   command=self._open_folder).pack(side=tk.LEFT, padx=4)

    def _browse_out(self):
        d = filedialog.askdirectory(title="Папка для OPDS-файлов",
                                    initialdir=self._out_var.get())
        if d:
            self._out_var.set(d)

    def _browse_lib(self):
        d = filedialog.askdirectory(title="Папка библиотеки")
        if d:
            self._lib_var.set(d)

    def _generate(self):
        out = self._out_var.get().strip()
        lib = self._lib_var.get().strip()
        if not out:
            messagebox.showerror("Ошибка", "Укажите папку для OPDS-файлов")
            return
        if not Path(self.db_path).exists():
            messagebox.showerror("Ошибка",
                                 "БД не найдена. Выполните синхронизацию сначала.")
            return
        self._gen_btn.configure(state='disabled')
        self._pb['value'] = 0
        threading.Thread(
            target=self._run_generate, args=(out, lib), daemon=True
        ).start()

    def _run_generate(self, output_dir: str, library_path: str):
        try:
            def progress(current, total, msg):
                pct = int(current / total * 100) if total else 0
                self.window.after(0, lambda: (
                    self._progress_var.set(msg),
                    self._pb.configure(value=pct),
                ))

            total = generate_opds(self.db_path, output_dir, library_path,
                                   progress_callback=progress)
            self.window.after(0, lambda: (
                self._progress_var.set(f"Готово! Экспортировано {total} книг → {output_dir}"),
                self._pb.configure(value=100),
                self._gen_btn.configure(state='normal'),
            ))
        except Exception as e:
            msg = f"Ошибка: {e}"
            self.window.after(0, lambda: (
                self._progress_var.set(msg),
                self._gen_btn.configure(state='normal'),
            ))

    def _open_folder(self):
        import subprocess
        folder = self._out_var.get()
        if Path(folder).exists():
            subprocess.Popen(['explorer', folder])
