"""
Диалог компиляции FB2-файлов.

Открывается из окна нормализации кнопкой «Скомпилировать».
Показывает все найденные группы (автор + серия ≥ 2 книг),
даёт запустить компиляцию с опцией удаления исходников.
"""

import tkinter as tk
from tkinter import ttk, messagebox
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


class CompilerDialog:
    """Модальный диалог компиляции серий."""

    def __init__(self, parent: tk.Widget, records: list, work_dir: Path, logger=None):
        """
        Args:
            parent:   Родительское окно (CSVNormalizerApp.root).
            records:  Список BookRecord из текущей загруженной таблицы.
            work_dir: Корневая папка (для разрешения file_path).
            logger:   Logger приложения.
        """
        self._parent   = parent
        self._records  = records
        self._work_dir = work_dir
        self._logger   = logger
        self._service  = FB2CompilerService(logger=logger)
        self._groups: List[CompilationGroup] = []
        self._results: List[CompilationResult] = []

        self._win = tk.Toplevel(parent)
        self._win.withdraw()  # скрываем до позиционирования
        self._win.title('Компиляция серий')
        self._win.resizable(True, True)

        # Позиционируем окно относительно родительского (тот же монитор)
        try:
            from window_persistence import setup_window_persistence
            _W, _H = 900, 620
            try:
                _settings = getattr(parent, 'settings', None) or getattr(
                    parent.master, 'settings', None)
            except Exception:
                _settings = None

            if _settings is not None:
                setup_window_persistence(
                    self._win, 'compiler_dialog', _settings,
                    f'{_W}x{_H}+100+100', parent_window=parent,
                )
            else:
                # Нет settings — просто центрируем на родителе
                from window_persistence import _default_geometry_near_parent
                self._win.geometry(_default_geometry_near_parent(parent, _W, _H))
        except Exception:
            self._win.geometry('900x620')

        self._build_ui()
        self._win.after(100, self._load_groups)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ── Верхняя панель ────────────────────────────────────────────
        top = ttk.Frame(self._win, padding='5 5 5 0')
        top.pack(fill=tk.X)

        ttk.Label(top, text='Найденные группы серий (≥ 2 файлов):',
                  font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT)

        self._status_var = tk.StringVar(value='Анализ…')
        ttk.Label(top, textvariable=self._status_var,
                  foreground='#0067C0').pack(side=tk.RIGHT, padx=5)

        # ── Нижняя панель: опции + кнопки (пакуем ДО PanedWindow, чтобы
        #    expand=True не вытеснял кнопки за пределы окна) ───────────
        bot = ttk.Frame(self._win, padding='5 3 5 5')
        bot.pack(fill=tk.X, side=tk.BOTTOM)

        self._delete_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            bot, text='Удалять исходники сразу после компиляции',
            variable=self._delete_var,
        ).grid(row=0, column=0, columnspan=2, sticky='w', pady=2)

        btn_frm = ttk.Frame(bot)
        btn_frm.grid(row=1, column=0, columnspan=2, sticky='e', pady=4)

        self._sel_all_btn = ttk.Button(btn_frm, text='Выбрать все',
                                       command=self._select_all)
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

        self._tree.tag_configure('ok',    background=_ORDER_OK_COLOR)
        self._tree.tag_configure('warn',  background=_ORDER_WARN_COLOR)
        self._tree.tag_configure('alpha', background='#E8F4FD')  # бледно-голубой

        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self._tree.bind('<ButtonRelease-1>', self._on_select)
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

        self._det_tree.grid(row=0, column=0, sticky='nsew')
        det_vsb.grid(row=0, column=1, sticky='ns')

        paned.add(bot_frm, weight=1)

    # ------------------------------------------------------------------
    # Загрузка групп
    # ------------------------------------------------------------------

    def _load_groups(self):
        """Запустить поиск групп в фоне."""
        def worker():
            groups = self._service.find_groups(self._records, self._work_dir)
            self._win.after(0, lambda: self._populate_groups(groups))

        threading.Thread(target=worker, daemon=True).start()

    def _populate_groups(self, groups: List[CompilationGroup]):
        self._groups = groups

        for iid in self._tree.get_children():
            self._tree.delete(iid)

        if not groups:
            self._status_var.set('Групп для компиляции не найдено')
            return

        total      = len(groups)
        compilable = total  # все группы теперь компилируемы

        for idx, g in enumerate(groups):
            # Описание источника сортировки
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

        alpha = sum(1 for g in groups if getattr(g, 'alphabetical_order', False))
        warn  = sum(1 for g in groups if not g.order_determined
                    and not getattr(g, 'alphabetical_order', False))
        status = f'Групп: {total}  |  К компиляции: {compilable}'
        if alpha:
            status += f'  |  По названию: {alpha}'
        if warn:
            status += f'  |  Частично: {warn}'
        self._status_var.set(status)
        self._compile_btn.configure(state=tk.NORMAL if compilable else tk.DISABLED)

    # ------------------------------------------------------------------
    # Взаимодействие
    # ------------------------------------------------------------------

    def _on_select(self, _event=None):
        """Показать детали выбранной группы."""
        sel = self._tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx >= len(self._groups):
            return
        group = self._groups[idx]

        for iid in self._det_tree.get_children():
            self._det_tree.delete(iid)

        for pos, book in enumerate(group.books, 1):
            title     = (book.record.file_title or '').strip() or book.abs_path.stem
            sort_lbl  = _SORT_SOURCE_LABEL.get(book.sort_source, book.sort_source)
            is_alpha = getattr(group, 'alphabetical_order', False)
            sn = book.volume_label or ('α' if is_alpha else ('?' if book.order_ambiguous else '—'))
            warn = '' if is_alpha else (' ⚠' if book.order_ambiguous else '')
            self._det_tree.insert(
                '', tk.END,
                values=(
                    pos,
                    title,
                    book.abs_path.name,
                    sort_lbl + warn,
                    sn,
                ),
            )

    def _select_all(self):
        """Выделить все строки в таблице групп."""
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
        to_compile = selected_groups  # все группы компилируемы
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
        self._status_var.set('Компиляция…')

        def worker():
            results = []
            for g in to_compile:
                r = self._service.compile_group(g, None, delete_sources=delete_now)
                results.append(r)
            self._win.after(0, lambda: self._on_compile_done(results, delete_now))

        threading.Thread(target=worker, daemon=True).start()

    def _on_compile_done(
        self,
        results: List[CompilationResult],
        delete_now: bool,
    ):
        ok      = [r for r in results if r.success]
        failed  = [r for r in results if not r.success]

        self._compile_btn.configure(state=tk.NORMAL)
        self._sel_all_btn.configure(state=tk.NORMAL)
        self._status_var.set(
            f'Готово: {len(ok)} успешно, {len(failed)} ошибок'
        )

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
        lines = [f'Успешно скомпилировано: {len(ok)}']
        for r in ok:
            lines.append(f'  ✓ {r.group.author} / {r.group.series} → {r.output_path.name}')
        if failed:
            lines.append(f'\nОшибок: {len(failed)}')
            for r in failed:
                lines.append(f'  ✗ {r.group.series}: {r.error}')
        messagebox.showinfo('Результат компиляции', '\n'.join(lines), parent=self._win)
