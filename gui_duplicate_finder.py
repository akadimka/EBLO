import os
import re
import hashlib
import unicodedata
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from .window_persistence import setup_window_persistence
except ImportError:
    from window_persistence import setup_window_persistence

try:
    from fb2_utils import fb2_rglob, read_fb2_bytes
except ImportError:
    from .fb2_utils import fb2_rglob, read_fb2_bytes


_COLLECTION_WORDS = re.compile(
    r'\b(сборник|антология|anthology|collection|omnibus|сборн)\b',
    re.IGNORECASE | re.UNICODE,
)


def _priority_score(path: Path, rec=None) -> float:
    """Чем выше score — тем больше этот файл заслуживает быть оригиналом (не дублём).

    Критерии (убывающий приоритет):
      +2  — есть proposed_series (файл в организованной серии)
      +1  — ни одна часть пути не содержит слова-сборника
      +0.1 × глубина — более глубокая иерархия предпочтительнее
    """
    score = 0.0
    if rec is not None:
        series = getattr(rec, 'proposed_series', '') or ''
        if series.strip():
            score += 2.0
    parts = path.parts
    if not any(_COLLECTION_WORDS.search(p) for p in parts):
        score += 1.0
    score += len(parts) * 0.1
    return score


def _file_hash(path: Path, chunk_size: int = 65536) -> str:
    """SHA-256 первых 256 КБ FB2-содержимого (прозрачно распаковывает fb2.zip)."""
    h = hashlib.sha256()
    try:
        # Для fb2.zip берём внутренние байты, чтобы дубли между .fb2 и .fb2.zip
        # одного файла корректно обнаруживались как дубликаты.
        raw = read_fb2_bytes(path)
        data = raw[:chunk_size * 4]
        h.update(data)
        return h.hexdigest()
    except Exception:
        return ''


def _norm_str(s: str) -> str:
    """Нормализация строки для сравнения: NFKC, строчные, ё→е, без лишних символов."""
    s = unicodedata.normalize('NFKC', s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'„"‟\(\)\[\]…]', '', s)
    return re.sub(r'\s+', ' ', s).strip()


def _norm_author(s: str) -> str:
    """Нормализация имени автора: точки → пробел (С.А. → с а), затем collapse spaces."""
    s = unicodedata.normalize('NFKC', s or '').lower().replace('ё', 'е')
    s = re.sub(r'\.', ' ', s)   # С.А.Кори → С А Кори
    return re.sub(r'\s+', ' ', s).strip()


def _rec_authors(rec) -> frozenset:
    """Извлечь frozenset нормализованных имён авторов.

    Приоритет: proposed_author (нормализован пайплайном), затем metadata_authors.
    """
    proposed = getattr(rec, 'proposed_author', '') or ''
    meta = getattr(rec, 'metadata_authors', '') or ''
    src = proposed if proposed else meta
    parts = re.split(r'[;,]', src)
    return frozenset(a for a in (_norm_author(p) for p in parts) if len(a) >= 3)


def _authors_set(s: str) -> frozenset:
    """Разбить строку авторов на frozenset нормализованных имён."""
    parts = re.split(r'[;,]', s or '')
    return frozenset(a for a in (_norm_author(p) for p in parts) if len(a) >= 3)


class DuplicateFinderWindow:
    def __init__(self, parent=None, settings_manager=None, on_close=None):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.withdraw()
        self.window.title("Поиск дубликатов")
        self.settings_manager = settings_manager
        self.search_path = tk.StringVar()
        self._duplicates: list = []
        self._all_dups: dict = {}
        self._total_files: int = 0
        self._searching = False
        self._on_close_cb = on_close

        if settings_manager:
            setup_window_persistence(self.window, 'duplicate_finder', settings_manager, '1200x700+200+150', parent_window=parent)
            saved = settings_manager.settings.get('duplicate_finder_path', '')
            if saved and os.path.isdir(saved):
                self.search_path.set(saved)
        else:
            self.window.geometry("1200x700")

        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        self.search_path.trace_add('write', self._save_search_path)
        self._build_ui()

    def _on_close(self):
        if self._on_close_cb:
            self._on_close_cb()
        self.window.destroy()

    def _save_search_path(self, *_):
        if self.settings_manager:
            self.settings_manager.settings['duplicate_finder_path'] = self.search_path.get()
            self.settings_manager.save()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.window

        # ── Верхняя панель: папка ────────────────────────────────────
        top = ttk.Frame(root, padding='8 6 8 4')
        top.pack(fill=tk.X)

        ttk.Label(top, text='Папка для поиска:').pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.search_path, width=70).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Button(top, text='Обзор…', command=self._browse).pack(side=tk.LEFT)

        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # ── Основная область: два списка со смещаемой перегородкой ──
        mid_wrap = ttk.Frame(root, padding='8 4 8 4')
        mid_wrap.pack(fill=tk.BOTH, expand=True)

        paned = ttk.PanedWindow(mid_wrap, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Левая панель — исходники
        left_pane = ttk.Frame(paned)
        paned.add(left_pane, weight=1)
        left_pane.rowconfigure(1, weight=1)
        left_pane.columnconfigure(0, weight=1)

        ttk.Label(left_pane, text='Исходные файлы', font=('', 9, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w', padx=(0, 6), pady=(0, 2))

        lf = ttk.Frame(left_pane)
        lf.grid(row=1, column=0, sticky='nsew')
        lf.rowconfigure(0, weight=1)
        lf.columnconfigure(0, weight=1)

        self.src_list = tk.Listbox(lf, selectmode=tk.SINGLE,
                                   bg='white', font=('', 9), activestyle='none')
        vsb_l = ttk.Scrollbar(lf, command=self.src_list.yview)
        hsb_l = ttk.Scrollbar(lf, orient=tk.HORIZONTAL, command=self.src_list.xview)
        self.src_list.configure(yscrollcommand=vsb_l.set, xscrollcommand=hsb_l.set)
        self.src_list.grid(row=0, column=0, sticky='nsew')
        vsb_l.grid(row=0, column=1, sticky='ns')
        hsb_l.grid(row=1, column=0, sticky='ew')
        self.src_list.bind('<<ListboxSelect>>', self._on_src_select)

        # Правая панель — дубликаты (Treeview с чекбоксами)
        right_pane = ttk.Frame(paned)
        paned.add(right_pane, weight=2)
        right_pane.rowconfigure(1, weight=1)
        right_pane.columnconfigure(0, weight=1)

        ttk.Label(right_pane, text='Дубликаты  (отметьте для удаления)',
                  font=('', 9, 'bold')).grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 2))

        rf = ttk.Frame(right_pane)
        rf.grid(row=1, column=0, sticky='nsew')
        rf.rowconfigure(0, weight=1)
        rf.columnconfigure(0, weight=1)

        self.dup_tree = ttk.Treeview(
            rf, columns=('check', 'path', 'reason', 'series', 'size'),
            show='headings', selectmode='none')
        self.dup_tree.heading('check',  text='✓',       anchor='center')
        self.dup_tree.heading('path',   text='Путь',    anchor='w',
                              command=lambda: self._sort_dup('path'))
        self.dup_tree.heading('reason', text='Тип',     anchor='center',
                              command=lambda: self._sort_dup('reason'))
        self.dup_tree.heading('series', text='Серия',   anchor='w',
                              command=lambda: self._sort_dup('series'))
        self.dup_tree.heading('size',   text='Размер',  anchor='e',
                              command=lambda: self._sort_dup('size'))
        self.dup_tree.column('check',  width=30,  stretch=False, anchor='center')
        self.dup_tree.column('path',   width=380, stretch=True)
        self.dup_tree.column('reason', width=100, stretch=False, anchor='center')
        self.dup_tree.column('series', width=160, stretch=False)
        self.dup_tree.column('size',   width=80,  stretch=False, anchor='e')
        self.dup_tree.tag_configure('checked',   background='#ffe0e0')
        self.dup_tree.tag_configure('unchecked', background='white')
        self.dup_tree.bind('<Button-1>', self._toggle_check)

        vsb_r = ttk.Scrollbar(rf, command=self.dup_tree.yview)
        hsb_r = ttk.Scrollbar(rf, orient=tk.HORIZONTAL, command=self.dup_tree.xview)
        self.dup_tree.configure(yscrollcommand=vsb_r.set, xscrollcommand=hsb_r.set)
        self.dup_tree.grid(row=0, column=0, sticky='nsew')
        vsb_r.grid(row=0, column=1, sticky='ns')
        hsb_r.grid(row=1, column=0, sticky='ew')

        # ── Прогресс + статус ────────────────────────────────────────
        bot_top = ttk.Frame(root, padding='8 2 8 2')
        bot_top.pack(fill=tk.X)
        self.progress = ttk.Progressbar(bot_top, mode='determinate')
        self.progress.pack(fill=tk.X)
        self.status_var = tk.StringVar(value='Готово')
        ttk.Label(bot_top, textvariable=self.status_var,
                  font=('', 9), foreground='#444').pack(anchor='w', pady=2)

        ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=8)

        # ── Нижние кнопки ────────────────────────────────────────────
        bot = ttk.Frame(root, padding='8 4 8 6')
        bot.pack(fill=tk.X)

        self.btn_search = ttk.Button(bot, text='Поиск', command=self._start_search)
        self.btn_search.pack(side=tk.LEFT, padx=4)

        self.btn_check_all = ttk.Button(bot, text='Отметить все',
                                        command=self._check_all, state=tk.DISABLED)
        self.btn_check_all.pack(side=tk.LEFT, padx=4)

        self.btn_delete = ttk.Button(bot, text='Удалить отмеченные',
                                     command=self._delete_checked, state=tk.DISABLED)
        self.btn_delete.pack(side=tk.LEFT, padx=4)

        ttk.Button(bot, text='Закрыть',
                   command=self.window.destroy).pack(side=tk.RIGHT, padx=4)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _browse(self):
        folder = filedialog.askdirectory(
            parent=self.window,
            initialdir=self.search_path.get() or os.path.expanduser('~'))
        if folder:
            self.search_path.set(folder)

    def _toggle_check(self, event):
        if self.dup_tree.identify_region(event.x, event.y) != 'cell':
            return
        if self.dup_tree.identify_column(event.x) != '#1':
            return
        iid = self.dup_tree.identify_row(event.y)
        if not iid:
            return
        vals = list(self.dup_tree.item(iid, 'values'))
        if vals[0] == '✓':
            vals[0] = ''
            self.dup_tree.item(iid, values=vals, tags=('unchecked',))
        else:
            vals[0] = '✓'
            self.dup_tree.item(iid, values=vals, tags=('checked',))
        self._update_delete_btn()

    def _check_all(self):
        for iid in self.dup_tree.get_children():
            vals = list(self.dup_tree.item(iid, 'values'))
            vals[0] = '✓'
            self.dup_tree.item(iid, values=vals, tags=('checked',))
        self._update_delete_btn()

    def _update_delete_btn(self):
        checked = sum(
            1 for iid in self.dup_tree.get_children()
            if self.dup_tree.item(iid, 'values')[0] == '✓')
        if checked:
            self.btn_delete.configure(state=tk.NORMAL,
                                      text=f'Удалить отмеченные ({checked})')
        else:
            self.btn_delete.configure(state=tk.DISABLED, text='Удалить отмеченные')

    def _sort_dup(self, col):
        items = [(self.dup_tree.item(i, 'values'), i)
                 for i in self.dup_tree.get_children()]
        idx = {'path': 1, 'reason': 2, 'series': 3, 'size': 4}[col]
        reverse = getattr(self, '_sort_rev', False)
        self._sort_rev = not reverse
        items.sort(key=lambda x: x[0][idx], reverse=reverse)
        for pos, (_, iid) in enumerate(items):
            self.dup_tree.move(iid, '', pos)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _start_search(self):
        if self._searching:
            return
        folder = self.search_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror('Ошибка', f'Папка не найдена:\n{folder}',
                                 parent=self.window)
            return

        self.src_list.delete(0, tk.END)
        for iid in self.dup_tree.get_children():
            self.dup_tree.delete(iid)
        self.btn_delete.configure(state=tk.DISABLED, text='Удалить отмеченные')
        self.btn_check_all.configure(state=tk.DISABLED)
        self.btn_search.configure(state=tk.DISABLED)
        self.progress['value'] = 0
        self.status_var.set('Фаза 1: генерация индекса…')
        self._searching = True

        threading.Thread(target=self._search_worker,
                         args=(folder,), daemon=True).start()

    def _search_worker(self, folder: str):
        try:
            # ── Фаза 1: генерация CSV (0–60%) ──────────────────────────
            try:
                from regen_csv import RegenCSVService
            except ImportError:
                from .regen_csv import RegenCSVService

            svc = RegenCSVService()

            def _csv_progress(current, total, status):
                pct = int(current / max(total, 1) * 60)
                self.window.after(0, lambda p=pct, s=status: (
                    self.progress.__setitem__('value', p),
                    self.status_var.set(f'Фаза 1: {s}'),
                ))

            records = svc.generate_csv(folder, output_csv_path=None,
                                       progress_callback=_csv_progress) or []

            # ── Фаза 2: поиск по хэшу (60–100%) ───────────────────────
            self.window.after(0, lambda: self.status_var.set('Фаза 2: поиск по хэшу…'))

            files = fb2_rglob(Path(folder))
            total = len(files)

            hash_map: dict = {}
            for i, path in enumerate(files, 1):
                h = _file_hash(path)
                if h:
                    hash_map.setdefault(h, []).append(path)
                if i % 20 == 0 or i == total:
                    pct = 60 + int(i / max(total, 1) * 40)
                    msg = f'Фаза 2: проверено {i} / {total} файлов'
                    self.window.after(0, lambda p=pct, m=msg: (
                        self.progress.__setitem__('value', p),
                        self.status_var.set(m),
                    ))

            # ── Объединение результатов ─────────────────────────────────
            all_dups = self._merge_duplicates(folder, hash_map, records)
            self.window.after(0, lambda: self._on_done(all_dups, total))

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.window.after(0, lambda: self._on_error(str(e)))

    def _merge_duplicates(self, folder: str, hash_map: dict, records: list) -> dict:
        """Объединить хэш-дубликаты и метадата-дубликаты.

        Возвращает {dup_path: {'source': Path, 'reasons': set, 'series': str}}.
        Оригинал выбирается по _priority_score (серия > не-сборник > глубина > алфавит).
        """
        work_dir = Path(folder)
        result: dict = {}  # dup_path → {source, reasons, series}

        # Индекс record по абсолютному пути для быстрого доступа при хэш-дублях
        rec_by_path: dict = {}
        for rec in records:
            fp = getattr(rec, 'file_path', '') or ''
            abs_p = self._resolve_path(work_dir, fp)
            if abs_p:
                rec_by_path[abs_p] = rec

        def _pick_source(paths_with_recs):
            """Вернуть (src, dups) отсортированные по приоритету (лучший = оригинал)."""
            scored = sorted(
                paths_with_recs,
                key=lambda pr: (-_priority_score(pr[0], pr[1]), str(pr[0])),
            )
            src = scored[0][0]
            dups = [p for p, _ in scored[1:]]
            return src, dups

        # ── Хэш-дубликаты ──────────────────────────────────────────────
        for paths in hash_map.values():
            if len(paths) < 2:
                continue
            paths_with_recs = [(p, rec_by_path.get(p)) for p in paths]
            src, dups = _pick_source(paths_with_recs)
            for dup in dups:
                if dup not in result:
                    result[dup] = {'source': src, 'reasons': {'Хэш'}, 'series': ''}
                else:
                    result[dup]['reasons'].add('Хэш')

        # ── Метаданные-дубликаты ───────────────────────────────────────
        title_map: dict = {}  # title_norm → [rec]
        for rec in records:
            title = _norm_str(getattr(rec, 'file_title', '') or '')
            if title:
                title_map.setdefault(title, []).append(rec)

        for title, recs in title_map.items():
            if len(recs) < 2:
                continue
            # Попарная проверка: пересечение авторов → дубликат
            recs_sorted = sorted(recs, key=lambda r: str(getattr(r, 'file_path', '')))
            for i, rec_a in enumerate(recs_sorted):
                authors_a = _rec_authors(rec_a)
                if not authors_a:
                    continue
                for rec_b in recs_sorted[i + 1:]:
                    authors_b = _rec_authors(rec_b)
                    if not authors_b or not (authors_a & authors_b):
                        continue
                    path_a = self._resolve_path(work_dir, getattr(rec_a, 'file_path', ''))
                    path_b = self._resolve_path(work_dir, getattr(rec_b, 'file_path', ''))
                    if path_b is None or not path_b.exists():
                        continue
                    # Выбираем оригинал по приоритету
                    score_a = _priority_score(path_a, rec_a) if path_a else 0
                    score_b = _priority_score(path_b, rec_b)
                    if score_a >= score_b:
                        src_path, dup_path, dup_rec = path_a, path_b, rec_b
                    else:
                        src_path, dup_path, dup_rec = path_b, path_a, rec_a
                        if src_path is None or not src_path.exists():
                            continue
                    series = (getattr(dup_rec, 'proposed_series', '') or
                              getattr(rec_a, 'proposed_series', '') or
                              getattr(rec_b, 'proposed_series', '') or '')
                    if dup_path not in result:
                        result[dup_path] = {
                            'source': src_path,
                            'reasons': {'Метаданные'},
                            'series': series,
                        }
                    else:
                        result[dup_path]['reasons'].add('Метаданные')
                        if series and not result[dup_path]['series']:
                            result[dup_path]['series'] = series

        return result

    @staticmethod
    def _resolve_path(work_dir: Path, file_path: str) -> Path:
        if not file_path:
            return None
        p = Path(file_path)
        if p.is_absolute():
            return p
        return work_dir / p

    def _on_done(self, all_dups: dict, total: int):
        self._searching = False
        self.btn_search.configure(state=tk.NORMAL)
        self.progress['value'] = 100
        self._all_dups = all_dups
        self._total_files = total

        sources = sorted({str(v['source']) for v in all_dups.values() if v['source']})
        for s in sources:
            self.src_list.insert(tk.END, s)

        self._populate_dup_tree(all_dups)

        if all_dups:
            self.btn_check_all.configure(state=tk.NORMAL)
            self._update_delete_btn()

    def _populate_dup_tree(self, dups: dict):
        """Заполнить dup_tree записями из dups, сохраняя состояние чекбоксов."""
        # Сохранить отмеченные пути
        checked = set()
        for iid in self.dup_tree.get_children():
            vals = self.dup_tree.item(iid, 'values')
            if vals and vals[0] == '✓':
                checked.add(vals[1])

        for iid in self.dup_tree.get_children():
            self.dup_tree.delete(iid)

        dup_size_total = 0
        for dup_path in sorted(dups):
            info = dups[dup_path]
            sz = dup_path.stat().st_size if dup_path.exists() else 0
            dup_size_total += sz
            sz_str = (f'{sz // 1024} КБ' if sz < 1_048_576
                      else f'{sz / 1_048_576:.1f} МБ')
            reason = '+'.join(sorted(info['reasons']))
            path_str = str(dup_path)
            is_checked = path_str in checked or path_str not in checked  # по умолчанию все отмечены
            tag = 'checked'
            self.dup_tree.insert('', tk.END,
                values=('✓' if is_checked else '☐', path_str, reason, info['series'], sz_str),
                tags=(tag,))

        total = getattr(self, '_total_files', 0)
        all_count = len(getattr(self, '_all_dups', {}))
        shown = len(dups)
        if all_count:
            mb = dup_size_total / 1_048_576
            if shown < all_count:
                self.status_var.set(
                    f'Показано {shown} из {all_count} дубликат(а/ов)'
                    f' — {mb:.1f} МБ')
            else:
                self.status_var.set(
                    f'Найдено {all_count} дубликат(а/ов) из {total} файлов'
                    f' — можно освободить {mb:.1f} МБ')
        else:
            self.status_var.set(f'Дубликаты не найдены ({total} файлов проверено)')
        self._update_delete_btn()

    def _on_src_select(self, _event=None):
        """Фильтровать дубликаты по выбранному источнику."""
        sel = self.src_list.curselection()
        if not sel:
            self._populate_dup_tree(self._all_dups)
            return
        selected_src = self.src_list.get(sel[0])
        filtered = {
            p: info for p, info in self._all_dups.items()
            if str(info.get('source', '')) == selected_src
        }
        self._populate_dup_tree(filtered)

    def _on_error(self, msg: str):
        self._searching = False
        self.btn_search.configure(state=tk.NORMAL)
        self.status_var.set(f'Ошибка: {msg}')
        messagebox.showerror('Ошибка', msg, parent=self.window)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def _delete_checked(self):
        to_delete = [
            self.dup_tree.item(iid, 'values')[1]
            for iid in self.dup_tree.get_children()
            if self.dup_tree.item(iid, 'values')[0] == '✓'
        ]
        if not to_delete:
            return

        if not messagebox.askyesno(
            'Подтверждение',
            f'Удалить {len(to_delete)} файл(а/ов)?\nДействие необратимо.',
            parent=self.window
        ):
            return

        failed = []
        deleted = []
        root = Path(self.search_path.get().strip())
        for path_str in to_delete:
            try:
                p = Path(path_str)
                p.unlink(missing_ok=True)
                deleted.append(path_str)
                parent = p.parent
                while parent != root and parent.is_dir():
                    if not any(parent.iterdir()):
                        parent.rmdir()
                        parent = parent.parent
                    else:
                        break
            except OSError as e:
                failed.append(f'{path_str}: {e}')

        deleted_set = set(deleted)
        for iid in list(self.dup_tree.get_children()):
            if self.dup_tree.item(iid, 'values')[1] in deleted_set:
                self.dup_tree.delete(iid)

        remaining = len(self.dup_tree.get_children())
        self.status_var.set(
            f'Удалено {len(deleted)} файл(а/ов).'
            + (f' Осталось: {remaining}.' if remaining else ' Все дубликаты удалены.')
            + (f' Ошибок: {len(failed)}.' if failed else '')
        )
        self._update_delete_btn()
        if not remaining:
            self.btn_check_all.configure(state=tk.DISABLED)

        if failed:
            messagebox.showwarning(
                'Ошибки при удалении',
                '\n'.join(failed[:10]) + ('\n…' if len(failed) > 10 else ''),
                parent=self.window)

    def run(self):
        self.window.mainloop()


def open_duplicate_finder(parent=None, settings_manager=None):
    DuplicateFinderWindow(parent, settings_manager)


if __name__ == '__main__':
    DuplicateFinderWindow().run()
