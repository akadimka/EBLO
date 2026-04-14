import os
import hashlib
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from .window_persistence import setup_window_persistence
except ImportError:
    from window_persistence import setup_window_persistence


def _file_hash(path: Path, chunk_size: int = 65536) -> str:
    """SHA-256 первых 256 КБ файла (быстро и достаточно точно)."""
    h = hashlib.sha256()
    try:
        with open(path, 'rb') as f:
            for _ in range(4):  # 4 × 64 КБ = 256 КБ
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except OSError:
        return ''
    return h.hexdigest()


class DuplicateFinderWindow:
    def __init__(self, parent=None, settings_manager=None):
        self.window = tk.Toplevel(parent) if parent else tk.Tk()
        self.window.title("Поиск дубликатов")
        self.settings_manager = settings_manager
        self.search_path = tk.StringVar()
        self._duplicates: list = []
        self._searching = False

        if settings_manager:
            setup_window_persistence(self.window, 'duplicate_finder', settings_manager, '1100x700+200+150')
        else:
            self.window.geometry("1100x700")

        self._build_ui()

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

        self.src_list = tk.Listbox(lf, selectmode=tk.EXTENDED,
                                   bg='white', font=('', 9), activestyle='none')
        vsb_l = ttk.Scrollbar(lf, command=self.src_list.yview)
        hsb_l = ttk.Scrollbar(lf, orient=tk.HORIZONTAL, command=self.src_list.xview)
        self.src_list.configure(yscrollcommand=vsb_l.set, xscrollcommand=hsb_l.set)
        self.src_list.grid(row=0, column=0, sticky='nsew')
        vsb_l.grid(row=0, column=1, sticky='ns')
        hsb_l.grid(row=1, column=0, sticky='ew')

        # Правая панель — дубликаты (Treeview с чекбоксами)
        right_pane = ttk.Frame(paned)
        paned.add(right_pane, weight=1)
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
            rf, columns=('check', 'path', 'size'),
            show='headings', selectmode='none')
        self.dup_tree.heading('check', text='✓', anchor='center')
        self.dup_tree.heading('path',  text='Путь',  anchor='w',
                              command=lambda: self._sort_dup('path'))
        self.dup_tree.heading('size',  text='Размер', anchor='e',
                              command=lambda: self._sort_dup('size'))
        self.dup_tree.column('check', width=30,  stretch=False, anchor='center')
        self.dup_tree.column('path',  width=460, stretch=True)
        self.dup_tree.column('size',  width=80,  stretch=False, anchor='e')
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
        idx = {'path': 1, 'size': 2}[col]
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
        self.status_var.set('Сканирование…')
        self._searching = True

        threading.Thread(target=self._search_worker,
                         args=(folder,), daemon=True).start()

    def _search_worker(self, folder: str):
        try:
            files = list(Path(folder).rglob('*.fb2'))
            total = len(files)
            if total == 0:
                self.window.after(0, lambda: self._on_done({}, total))
                return

            hash_map: dict = {}
            for i, path in enumerate(files, 1):
                h = _file_hash(path)
                if h:
                    hash_map.setdefault(h, []).append(path)
                if i % 20 == 0 or i == total:
                    pct = int(i / total * 100)
                    msg = f'Проверено: {i} / {total}'
                    self.window.after(0, lambda p=pct, m=msg: (
                        self.progress.__setitem__('value', p),
                        self.status_var.set(m)
                    ))
            self.window.after(0, lambda: self._on_done(hash_map, total))
        except Exception as e:
            self.window.after(0, lambda: self._on_error(str(e)))

    def _on_done(self, hash_map: dict, total: int):
        self._searching = False
        self.btn_search.configure(state=tk.NORMAL)
        self.progress['value'] = 100

        sources = []
        duplicates = []
        for paths in hash_map.values():
            if len(paths) < 2:
                continue
            paths_sorted = sorted(paths)
            sources.append(paths_sorted[0])
            duplicates.extend(paths_sorted[1:])

        for p in sorted(sources):
            self.src_list.insert(tk.END, str(p))

        dup_size_total = 0
        for p in sorted(duplicates):
            sz = p.stat().st_size if p.exists() else 0
            dup_size_total += sz
            sz_str = f'{sz // 1024} КБ' if sz < 1_048_576 else f'{sz / 1_048_576:.1f} МБ'
            self.dup_tree.insert('', tk.END,
                values=('✓', str(p), sz_str), tags=('checked',))

        if duplicates:
            mb = dup_size_total / 1_048_576
            self.status_var.set(
                f'Найдено {len(duplicates)} дубликат(а/ов) из {total} файлов'
                f' — можно освободить {mb:.1f} МБ')
            self.btn_check_all.configure(state=tk.NORMAL)
            self._update_delete_btn()
        else:
            self.status_var.set(f'Дубликаты не найдены ({total} файлов проверено)')

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
        for path_str in to_delete:
            try:
                Path(path_str).unlink(missing_ok=True)
                deleted.append(path_str)
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