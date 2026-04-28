"""
Диалог компиляции FB2-файлов.

Открывается из окна нормализации кнопкой «Скомпилировать».
Пользователь выбирает папку, нажимает «Сканировать» — диалог сам
находит все группы (автор + серия ≥ 2 книг) и заполняет таблицу.
Затем можно выбрать группы и запустить компиляцию.
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
from pathlib import Path
from typing import List, Optional

try:
    from fb2_compiler import FB2CompilerService, CompilationGroup, CompilationResult
except ImportError:
    from .fb2_compiler import FB2CompilerService, CompilationGroup, CompilationResult


_SORT_SOURCE_LABEL = {
    'series_number':  'Номер тома (мета)',
    'filename':       'Номер в имени файла',
    'filename_range': 'Диапазон в имени файла',
    'inline_title':   'Номер в названии',
    'title_date':     'Год написания (мета)',
    'publish_date':   'Год издания (мета)',
    'unknown':        '⚠ Не определён',
}

_ORDER_OK_COLOR   = '#DFF0D8'   # бледно-зелёный
_ORDER_WARN_COLOR = '#FCF8E3'   # жёлтый
_ORDER_ERR_COLOR  = '#F2DEDE'   # розовый

_SETTINGS_KEY_COMPILER_DIR = 'compiler_scan_dir'


class CompilerDialog:
    """Диалог компиляции серий."""

    def __init__(self, parent: tk.Widget, logger=None, settings=None,
                 initial_dir: str = '', auto_scan: bool = False):
        """
        Args:
            parent:      Родительское окно.
            logger:      Logger приложения.
            settings:    SettingsManager для сохранения/восстановления состояния.
            initial_dir: Папка, подставляемая в поле сканирования при открытии.
            auto_scan:   Если True — автоматически запустить сканирование после открытия.
        """
        self._parent   = parent
        self._logger   = logger
        self._settings = settings
        self._service  = FB2CompilerService(logger=logger)
        self._groups: List[CompilationGroup] = []
        self._results: List[CompilationResult] = []
        self._scanning = False
        self._initial_dir = initial_dir
        self._auto_scan   = auto_scan

        self._win = tk.Toplevel(parent)
        self._win.withdraw()  # скрываем до позиционирования
        self._win.title('Компиляция серий')
        self._win.resizable(True, True)

        # Позиционируем окно относительно родительского (тот же монитор)
        try:
            from window_persistence import setup_window_persistence
            _W, _H = 900, 640
            if self._settings is not None:
                setup_window_persistence(
                    self._win, 'compiler_dialog', self._settings,
                    f'{_W}x{_H}+100+100', parent_window=parent,
                )
            else:
                from window_persistence import _default_geometry_near_parent
                self._win.geometry(_default_geometry_near_parent(parent, _W, _H))
                self._win.deiconify()
        except Exception:
            self._win.geometry('900x640')
            self._win.deiconify()

        self._build_ui()
        if self._initial_dir and Path(self._initial_dir).is_dir():
            self._dir_var.set(self._initial_dir)
            if self._auto_scan:
                self._win.after(200, self._run_scan)
        else:
            self._load_saved_dir()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Панель выбора директории (вверху) ────────────────────────
        dir_frm = ttk.Frame(self._win, padding='5 5 5 3')
        dir_frm.pack(fill=tk.X)

        ttk.Label(dir_frm, text='Папка для сканирования:').pack(side=tk.LEFT)

        self._dir_var = tk.StringVar()
        self._dir_var.trace_add('write', self._on_dir_changed)
        dir_entry = ttk.Entry(dir_frm, textvariable=self._dir_var)
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 4))

        ttk.Button(dir_frm, text='…', width=3,
                   command=self._browse_dir).pack(side=tk.LEFT)

        ttk.Separator(self._win, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=5)

        # ── Верхняя панель (статус) ───────────────────────────────────
        top = ttk.Frame(self._win, padding='5 3 5 0')
        top.pack(fill=tk.X)

        ttk.Label(top, text='Найденные группы серий (≥ 2 файлов):',
                  font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value='Укажите папку и нажмите «Сканировать»')
        ttk.Label(top, textvariable=self._status_var,
                  foreground='#0067C0').pack(side=tk.RIGHT, padx=5)

        # ── Прогресс-бар сканирования ─────────────────────────────────
        prog_frm = ttk.Frame(self._win, padding='5 0 5 2')
        prog_frm.pack(fill=tk.X)

        self._progress_var = tk.IntVar(value=0)
        self._progressbar = ttk.Progressbar(
            prog_frm, variable=self._progress_var,
            maximum=100, mode='determinate',
        )
        self._progressbar.pack(fill=tk.X)
        self._progressbar.pack_forget()   # скрыт до начала сканирования

        # ── Нижняя панель: опции + кнопки ────────────────────────────
        bot = ttk.Frame(self._win, padding='5 3 5 5')
        bot.pack(fill=tk.X, side=tk.BOTTOM)

        self._delete_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bot, text='Удалять исходники сразу после компиляции',
            variable=self._delete_var,
        ).grid(row=0, column=0, columnspan=2, sticky='w', pady=2)

        btn_frm = ttk.Frame(bot)
        btn_frm.grid(row=1, column=0, columnspan=2, sticky='e', pady=4)

        self._scan_btn = ttk.Button(btn_frm, text='Сканировать',
                                    command=self._run_scan,
                                    state=tk.DISABLED)
        self._scan_btn.pack(side=tk.LEFT, padx=3)

        self._sel_all_btn = ttk.Button(btn_frm, text='Выбрать все',
                                       command=self._select_all,
                                       state=tk.DISABLED)
        self._sel_all_btn.pack(side=tk.LEFT, padx=3)

        self._compile_btn = ttk.Button(btn_frm, text='Скомпилировать',
                                       command=self._run_compile,
                                       state=tk.DISABLED)
        self._compile_btn.pack(side=tk.LEFT, padx=3)

        ttk.Button(btn_frm, text='Закрыть',
                   command=self._win.destroy).pack(side=tk.LEFT, padx=3)

        # ── Перетаскиваемый разделитель между таблицами ───────────────
        paned = ttk.PanedWindow(self._win, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=(2, 0))

        # ── Верхняя панель: таблица групп ────────────────────────────
        top_frm = ttk.Frame(paned)
        top_frm.rowconfigure(0, weight=1)
        top_frm.columnconfigure(0, weight=1)

        cols = ('author', 'series', 'books', 'order', 'range')
        self._tree = ttk.Treeview(
            top_frm, columns=cols, show='headings', selectmode='extended',
        )
        vsb = ttk.Scrollbar(top_frm, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.heading('author', text='Автор')
        self._tree.heading('series', text='Серия')
        self._tree.heading('books',  text='Кн.')
        self._tree.heading('order',  text='Сортировка')
        self._tree.heading('range',  text='Диапазон')

        self._tree.column('author', width=220, minwidth=120)
        self._tree.column('series', width=220, minwidth=120)
        self._tree.column('books',  width=40,  minwidth=40,  anchor='center')
        self._tree.column('order',  width=200, minwidth=140)
        self._tree.column('range',  width=80,  minwidth=60,  anchor='center')

        self._tree.tag_configure('ok',      background=_ORDER_OK_COLOR)
        self._tree.tag_configure('warn',    background=_ORDER_WARN_COLOR)
        self._tree.tag_configure('alpha',   background='#E8F4FD')  # бледно-голубой
        self._tree.tag_configure('cleanup', background='#F5F5F5', foreground='#888888')  # серый — уже скомпилировано

        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self._tree.bind('<ButtonRelease-1>', self._on_select)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        paned.add(top_frm, weight=3)

        # ── Нижняя панель: детали выбранной группы ───────────────────
        bot_frm = ttk.LabelFrame(paned, text='Книги выбранной группы', padding=4)
        bot_frm.rowconfigure(0, weight=1)
        bot_frm.columnconfigure(0, weight=1)

        det_cols = ('num', 'title', 'file', 'sort_src', 'sn')
        self._det_tree = ttk.Treeview(
            bot_frm, columns=det_cols, show='headings',
        )
        det_vsb = ttk.Scrollbar(bot_frm, orient=tk.VERTICAL,
                                 command=self._det_tree.yview)
        self._det_tree.configure(yscrollcommand=det_vsb.set)

        self._det_tree.heading('num',      text='#')
        self._det_tree.heading('title',    text='Название')
        self._det_tree.heading('file',     text='Файл')
        self._det_tree.heading('sort_src', text='Источник порядка')
        self._det_tree.heading('sn',       text='№ тома')

        self._det_tree.column('num',      width=30,  minwidth=25, anchor='center')
        self._det_tree.column('title',    width=260, minwidth=100)
        self._det_tree.column('file',     width=250, minwidth=100)
        self._det_tree.column('sort_src', width=180, minwidth=120)
        self._det_tree.column('sn',       width=60,  minwidth=40, anchor='center')

        self._det_tree.tag_configure('to_delete', background='#FFE4E1', foreground='#CC0000')  # красный — к удалению
        self._det_tree.tag_configure('kept',      background='#E8F5E9', foreground='#2E7D32')  # зелёный — остаётся

        self._det_tree.grid(row=0, column=0, sticky='nsew')
        det_vsb.grid(row=0, column=1, sticky='ns')
        self._det_paths: dict = {}
        self._det_tree.bind('<Double-1>', self._on_book_dblclick)

        # ── Строка предпросмотра имени файла ─────────────────────────
        fname_frm = ttk.Frame(bot_frm)
        fname_frm.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        ttk.Label(fname_frm, text='Имя файла:', foreground='#666666').pack(side=tk.LEFT, padx=(2, 6))
        self._fname_var = tk.StringVar(value='—')
        ttk.Label(
            fname_frm, textvariable=self._fname_var,
            foreground='#0067C0', font=('Segoe UI', 9, 'italic'),
            anchor='w',
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        paned.add(bot_frm, weight=1)

    # ------------------------------------------------------------------
    # Директория
    # ------------------------------------------------------------------

    def _load_saved_dir(self):
        """Загрузить сохранённую директорию из настроек."""
        if self._settings is None:
            return
        try:
            saved = self._settings.get(_SETTINGS_KEY_COMPILER_DIR, '')
            if saved and Path(saved).is_dir():
                self._dir_var.set(saved)
        except Exception:
            pass

    def _save_dir(self, path: str):
        """Сохранить директорию в настройки."""
        if self._settings is None:
            return
        try:
            self._settings.set(_SETTINGS_KEY_COMPILER_DIR, path)
        except Exception:
            pass

    def _browse_dir(self):
        current = self._dir_var.get().strip()
        initial = current if current and Path(current).is_dir() else ''
        chosen = filedialog.askdirectory(
            parent=self._win,
            title='Выберите папку для сканирования',
            initialdir=initial or None,
        )
        if chosen:
            self._dir_var.set(chosen)

    def _on_dir_changed(self, *_):
        folder = self._dir_var.get().strip()
        is_valid = bool(folder) and Path(folder).is_dir()
        self._scan_btn.configure(state=tk.NORMAL if is_valid else tk.DISABLED)
        if is_valid:
            self._save_dir(folder)

    # ------------------------------------------------------------------
    # Сканирование
    # ------------------------------------------------------------------

    def _run_scan(self):
        if self._scanning:
            return
        folder = self._dir_var.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror('Ошибка', 'Укажите корректную папку.', parent=self._win)
            return

        self._scanning = True
        self._scan_btn.configure(state=tk.DISABLED)
        self._sel_all_btn.configure(state=tk.DISABLED)
        self._compile_btn.configure(state=tk.DISABLED)
        self._status_var.set('Сканирование…')

        # Показать прогресс-бар
        self._progress_var.set(0)
        self._progressbar.pack(fill=tk.X)

        # Очистить таблицы
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        for iid in self._det_tree.get_children():
            self._det_tree.delete(iid)
        self._fname_var.set('—')
        self._groups = []

        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    def _scan_worker(self, folder: str):
        import sys, os
        work_dir = Path(folder)

        # tqdm пишет в stdout/stderr — перенаправляем в devnull чтобы не зависнуть.
        _devnull = open(os.devnull, 'w', encoding='utf-8')
        _old_stdout, _old_stderr = sys.stdout, sys.stderr
        sys.stdout = _devnull
        sys.stderr = _devnull

        def _progress(current: int, total: int, status: str):
            pct = int(current / total * 100) if total else 0
            self._win.after(0, lambda p=pct, s=status: (
                self._progress_var.set(p),
                self._status_var.set(s),
            ))

        try:
            try:
                from regen_csv import RegenCSVService
            except ImportError:
                from .regen_csv import RegenCSVService

            self._set_status('Сканирование файлов…')

            svc = RegenCSVService()
            try:
                records = svc.generate_csv(folder, output_csv_path=None,
                                           progress_callback=_progress)
            except Exception:
                records = []
            if not records:
                records = getattr(svc, 'records', []) or []

            self._set_status('Поиск групп для компиляции…')
            groups = self._service.find_groups(records, work_dir)

            self._win.after(0, lambda: self._populate_groups(groups))

        except Exception as exc:
            import traceback
            err = traceback.format_exc()
            self._win.after(0, lambda: self._on_scan_error(err))

        finally:
            sys.stdout = _old_stdout
            sys.stderr = _old_stderr
            _devnull.close()

    def _set_status(self, text: str):
        self._win.after(0, lambda: self._status_var.set(text))

    def _on_scan_error(self, err: str):
        self._scanning = False
        self._progressbar.pack_forget()
        self._scan_btn.configure(
            state=tk.NORMAL if Path(self._dir_var.get().strip()).is_dir() else tk.DISABLED
        )
        self._status_var.set(f'Ошибка: {err}')
        messagebox.showerror('Ошибка сканирования', err, parent=self._win)

    def _populate_groups(self, groups: List[CompilationGroup]):
        self._scanning = False
        self._progressbar.pack_forget()
        folder = self._dir_var.get().strip()
        self._scan_btn.configure(
            state=tk.NORMAL if folder and Path(folder).is_dir() else tk.DISABLED
        )

        self._groups = groups

        if not groups:
            self._status_var.set('Групп для компиляции не найдено')
            return

        compilable_groups = [g for g in groups if not getattr(g, 'cleanup_only', False)]
        cleanup_groups    = [g for g in groups if getattr(g, 'cleanup_only', False)]
        total      = len(compilable_groups)
        compilable = total or len(cleanup_groups)

        for idx, g in enumerate(groups):
            if getattr(g, 'cleanup_only', False):
                dup_count = len(g.duplicate_paths)
                self._tree.insert(
                    '', tk.END,
                    iid=str(idx),
                    values=(
                        g.author,
                        g.series,
                        f'0 (удалить: {dup_count})',
                        '✓ Уже скомпилировано',
                        g.volume_range or '—',
                    ),
                    tags=('cleanup',),
                )
                continue

            sources = {b.sort_source for b in g.books}
            sources.discard('unknown')
            if getattr(g, 'alphabetical_order', False):
                order_txt = '📖 По названию (нет нумерации томов)'
                tag = 'alpha'
            elif g.order_determined:
                order_txt = ', '.join(_SORT_SOURCE_LABEL.get(s, s) for s in sources)
                tag = 'ok'
            else:
                order_txt = '⚠ Порядок частично не определён'
                tag = 'warn'

            self._tree.insert(
                '', tk.END,
                iid=str(idx),
                values=(
                    g.author,
                    g.series,
                    len(g.books),
                    order_txt,
                    g.volume_range or '—',
                ),
                tags=(tag,),
            )

        alpha = sum(1 for g in compilable_groups if getattr(g, 'alphabetical_order', False))
        warn  = sum(1 for g in compilable_groups if not g.order_determined
                    and not getattr(g, 'alphabetical_order', False))

        # Подсчёт файлов и размеров (только компилируемые группы)
        files_before = sum(len(g.books) for g in compilable_groups)
        files_after  = len(compilable_groups)  # каждая группа → 1 файл
        freed_bytes  = 0
        for g in compilable_groups:
            for b in g.books:
                try:
                    freed_bytes += b.abs_path.stat().st_size
                except OSError:
                    pass

        def _fmt_size(b: int) -> str:
            if b >= 1_073_741_824:
                return f'{b/1_073_741_824:.1f} ГБ'
            if b >= 1_048_576:
                return f'{b/1_048_576:.1f} МБ'
            return f'{b/1024:.0f} КБ'

        status = (
            f'Групп: {total}'
            f'  |  Файлов: {files_before} → {files_after}'
            f'  |  Объём исходников: {_fmt_size(freed_bytes)}'
        )
        if cleanup_groups:
            cleanup_dups = sum(len(g.duplicate_paths) for g in cleanup_groups)
            status += f'  |  Устаревших: {cleanup_dups}'
        if alpha:
            status += f'  |  По названию: {alpha}'
        if warn:
            status += f'  |  Частично: {warn}'
        self._status_var.set(status)

        self._sel_all_btn.configure(state=tk.NORMAL if compilable else tk.DISABLED)
        self._compile_btn.configure(state=tk.NORMAL if compilable else tk.DISABLED)

    # ------------------------------------------------------------------
    # Взаимодействие
    # ------------------------------------------------------------------

    def _on_select(self, _event=None):
        """Показать детали выбранной группы."""
        sel = self._tree.selection()
        if not sel:
            self._fname_var.set('—')
            return
        idx = int(sel[0])
        if idx >= len(self._groups):
            return
        group = self._groups[idx]

        for iid in self._det_tree.get_children():
            self._det_tree.delete(iid)
        self._det_paths.clear()

        if getattr(group, 'cleanup_only', False):
            # Сначала — файлы, которые остаются (зелёные)
            for pos, kept_path in enumerate(group.kept_paths or [], 1):
                _iid = self._det_tree.insert(
                    '', tk.END,
                    values=(
                        pos,
                        kept_path.stem,
                        kept_path.name,
                        '✓ Остаётся',
                        '—',
                    ),
                    tags=('kept',),
                )
                self._det_paths[_iid] = kept_path
            # Затем — файлы к удалению (красные)
            offset = len(group.kept_paths or [])
            for pos, dup_path in enumerate(group.duplicate_paths, offset + 1):
                _iid = self._det_tree.insert(
                    '', tk.END,
                    values=(
                        pos,
                        dup_path.stem,
                        dup_path.name,
                        '🗑 К удалению',
                        '—',
                    ),
                    tags=('to_delete',),
                )
                self._det_paths[_iid] = dup_path
            kept_label = f'Уже скомпилировано: {group.volume_range}' if group.volume_range else 'Уже скомпилировано'
            self._fname_var.set(kept_label)
            return

        for pos, book in enumerate(group.books, 1):
            title    = (book.record.file_title or '').strip() or book.abs_path.stem
            sort_lbl = _SORT_SOURCE_LABEL.get(book.sort_source, book.sort_source)
            is_alpha = getattr(group, 'alphabetical_order', False)
            sn = book.volume_label or ('α' if is_alpha else ('?' if book.order_ambiguous else '—'))
            warn = '' if is_alpha else (' ⚠' if book.order_ambiguous else '')
            _iid = self._det_tree.insert(
                '', tk.END,
                values=(
                    pos,
                    title,
                    book.abs_path.name,
                    sort_lbl + warn,
                    sn,
                ),
            )
            self._det_paths[_iid] = book.abs_path

        # Файлы-дубликаты, которые будут удалены при компиляции
        offset = len(group.books)
        for pos, dup_path in enumerate(group.duplicate_paths or [], offset + 1):
            _iid = self._det_tree.insert(
                '', tk.END,
                values=(
                    pos,
                    dup_path.stem,
                    dup_path.name,
                    '🗑 К удалению',
                    '—',
                ),
                tags=('to_delete',),
            )
            self._det_paths[_iid] = dup_path

        # Предпросмотр имени файла компиляции
        try:
            import re as _re
            clean_series = self._service._clean_series_name(group.series)
            safe_author  = _re.sub(r'[\\/:*?"<>|]', '_', group.author)
            part_count   = getattr(group, 'part_count', 0)
            top_lo, top_hi, n_volumes, has_subseries = self._service._run_stats(group.books)
            safe_series = _re.sub(r'[/:*?"<>|]', '_', self._service._series_to_display(clean_series))
            suffix      = self._service._series_suffix(n_volumes, top_lo, top_hi, part_count)
            fname       = f'{safe_author} - {safe_series} ({suffix}).fb2'
            self._fname_var.set(fname)
        except Exception:
            self._fname_var.set('—')

    def _on_book_dblclick(self, _event=None):
        sel = self._det_tree.selection()
        if not sel:
            return
        path = self._det_paths.get(sel[0])
        if path:
            import subprocess
            subprocess.Popen(f'explorer /select,"{path}"', shell=True)

    def _select_all(self):
        self._tree.selection_set(self._tree.get_children())

    # ------------------------------------------------------------------
    # Запуск компиляции
    # ------------------------------------------------------------------

    def _run_compile(self):
        sel = self._tree.selection()
        if not sel:
            messagebox.showwarning('Внимание', 'Выберите группы для компиляции',
                                   parent=self._win)
            return

        selected_groups = [self._groups[int(iid)] for iid in sel]
        to_compile = selected_groups
        alpha_cnt  = sum(1 for g in to_compile if getattr(g, 'alphabetical_order', False))

        if not to_compile:
            messagebox.showwarning('Внимание', 'Выберите группы для компиляции',
                                   parent=self._win)
            return

        delete_now = self._delete_var.get()

        msg = f'Скомпилировать {len(to_compile)} групп(ы)?'
        if alpha_cnt:
            msg += f'\n({alpha_cnt} будут упорядочены по названию → «компиляция романов»)'
        if delete_now:
            msg += '\n\n⚠ Исходные файлы будут удалены сразу!'
        if not messagebox.askyesno('Подтверждение', msg, parent=self._win):
            return

        self._compile_btn.configure(state=tk.DISABLED)
        self._sel_all_btn.configure(state=tk.DISABLED)
        self._scan_btn.configure(state=tk.DISABLED)
        self._status_var.set('Компиляция…')

        # Показать прогресс-бар компиляции
        total_groups = len(to_compile)
        self._progress_var.set(0)
        self._progressbar.pack(fill=tk.X)

        def worker():
            results = []
            for i, g in enumerate(to_compile, 1):
                self._win.after(0, lambda i=i, a=g.author, s=g.series: (
                    self._progress_var.set(int((i - 1) / total_groups * 100)),
                    self._status_var.set(f'Компиляция {i}/{total_groups}: {a} / {s}'),
                ))
                r = self._service.compile_group(g, None, delete_sources=delete_now)
                results.append(r)
            self._win.after(0, lambda: self._on_compile_done(results, delete_now))

        threading.Thread(target=worker, daemon=True).start()

    def _on_compile_done(
        self,
        results: List[CompilationResult],
        delete_now: bool,
    ):
        ok     = [r for r in results if r.success]
        failed = [r for r in results if not r.success]

        self._progressbar.pack_forget()
        folder = self._dir_var.get().strip()
        self._scan_btn.configure(
            state=tk.NORMAL if folder and Path(folder).is_dir() else tk.DISABLED
        )
        self._compile_btn.configure(state=tk.NORMAL if self._groups else tk.DISABLED)
        self._sel_all_btn.configure(state=tk.NORMAL if self._groups else tk.DISABLED)
        self._status_var.set(f'Готово: {len(ok)} успешно, {len(failed)} ошибок')

        # Если не удаляли сразу — предложить удалить сейчас
        if not delete_now and ok:
            if messagebox.askyesno(
                'Удалить исходники?',
                f'Скомпилировано {len(ok)} групп(ы).\n'
                'Удалить исходные файлы?',
                parent=self._win,
            ):
                for r in ok:
                    self._service.delete_sources_for_result(r)

        # Итог
        real_ok     = [r for r in ok if not getattr(r.group, 'cleanup_only', False)]
        cleanup_ok  = [r for r in ok if getattr(r.group, 'cleanup_only', False)]
        lines = [f'Успешно скомпилировано: {len(real_ok)}']
        for r in real_ok:
            lines.append(f'  ✓ {r.group.author} / {r.group.series} → {r.output_path.name}')
        if cleanup_ok:
            cleaned = sum(len(r.source_paths) for r in cleanup_ok)
            lines.append(f'\nУдалено устаревших файлов: {cleaned}')
            for r in cleanup_ok:
                lines.append(f'  ♻ {r.group.author} / {r.group.series} ({r.group.volume_range})')
        if failed:
            lines.append(f'\nОшибок: {len(failed)}')
            for r in failed:
                lines.append(f'  ✗ {r.group.series}: {r.error}')
        messagebox.showinfo('Результат компиляции', '\n'.join(lines), parent=self._win)
