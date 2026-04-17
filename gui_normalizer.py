import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import sys
from pathlib import Path
from io import StringIO

try:
    from regen_csv import RegenCSVService
except ImportError:
    from .regen_csv import RegenCSVService


class _Tooltip:
    """Всплывающая подсказка для любого виджета tkinter.

    text — строка или callable() -> str для динамического содержимого.
    """

    def __init__(self, widget: tk.Widget, text):
        self._widget = widget
        self._text = text   # str | Callable[[], str]
        self._win = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Destroy>", lambda e: self._hide(), add="+")

    def _show(self, event=None):
        text = self._text() if callable(self._text) else self._text
        if self._win or not text:
            return
        try:
            x = self._widget.winfo_rootx() + 20
            y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
            self._win = tw = tk.Toplevel(self._widget)
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            tk.Label(
                tw, text=text,
                background="#FFFFE0", foreground="#1A1A1A",
                relief="solid", borderwidth=1,
                font=("Segoe UI", 9), justify="left",
                wraplength=600, padx=6, pady=4,
            ).pack()
        except Exception:
            self._win = None

    def _hide(self, event=None):
        if self._win:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


class NamesDialog:
    """Окно просмотра и редактирования извлечённых имён авторов."""

    GENDER_OPTIONS = ("Муж.", "Жен.")

    # Цвета подсветки строк онлайн-проверки
    _STATUS_COLORS = {
        'pending':    '#FFFACD',   # лимонный — запрос отправлен
        'found':      '#C8F0C8',   # зелёный  — пол определён
        'uncertain':  '#E8FFD0',   # светло-зелёный — неуверенно, но заполнено
        'unknown':    '#FFE4C4',   # персиковый — сервис не знает
        'error':      '#FFCCCC',   # розово-красный — ошибка сети
        'rate_limit': '#FFD0FF',   # сиреневый — исчерпан суточный лимит
    }

    # Текст подсказки для каждого статуса (для тултипа на поле автора)
    _STATUS_LEGEND = {
        'pending':    'Жёлтый — запрос отправлен в онлайн-сервис, ожидание ответа',
        'found':      'Зелёный — пол определён уверенно (вероятность ≥ 75%)',
        'uncertain':  'Светло-зелёный — пол определён, но вероятность < 75%',
        'unknown':    'Персиковый — сервис не смог определить пол по этому имени',
        'error':      'Розовый — ошибка сети при обращении к онлайн-сервису',
        'rate_limit': 'Сиреневый — превышен суточный лимит запросов (HTTP 429)',
    }

    def __init__(self, parent, rows, settings_manager):
        """
        Args:
            rows: список кортежей:
                  (author_source, proposed_author, first_name, gender)
                  или (author_source, proposed_author, first_name, gender, file_path)
                  Может быть пустым — строки добавляются позже через add_rows().
            settings_manager: экземпляр SettingsManager
        """
        self.settings_manager = settings_manager

        # Полноценное окно (не диалог): без transient/grab_set → все кнопки хрома
        self.top = tk.Toplevel(parent)
        self.top.title("Имена авторов")
        self.top.geometry("960x580")
        self.top.resizable(True, True)

        # Данные строк: (source, author, name_var, gender_var, file_path)
        self._row_data = []
        # UI-ссылки для цветовой сигнализации: (author_frame, [word_labels])
        self._row_ui = []
        # Текущий статус каждой строки (для динамического тултипа)
        self._row_status: list = []
        # Дефолтный bg фрейма автора (определяется при первом _add_row_widget)
        self._default_author_bg: str = ''

        # Счётчики онлайн-проверки
        self._online_total = 0
        self._online_done  = 0

        # Онлайн-сервис (None = недоступен)
        self._service = None
        if settings_manager:
            try:
                from gender_lookup import GenderLookupService
                api_key = settings_manager.get_genderize_api_key()
                self._service = GenderLookupService(api_key=api_key, settings=settings_manager)
            except ImportError:
                pass

        self._build_ui()

        if rows:
            self.add_rows(rows)

    # ------------------------------------------------------------------
    # Построение UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # ---- заголовок таблицы ----
        hdr = ttk.Frame(self.top)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        for text, w in (("Источник", 130), ("Автор (из данных)", 280),
                        ("Имя", 180), ("Пол", 120)):
            ttk.Label(hdr, text=text, relief="groove", width=w // 7,
                      anchor="w").pack(side=tk.LEFT, padx=1)

        # ---- строка «обработка данных» (скрывается когда строки появились) ----
        self._loading_var = tk.StringVar(value="")
        self._loading_label = ttk.Label(
            self.top, textvariable=self._loading_var,
            foreground="gray", font=("Segoe UI", 9),
        )
        self._loading_label.pack(anchor="w", padx=10, pady=(2, 0))

        # ---- прокручиваемый canvas ----
        container = ttk.Frame(self.top)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self._canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = ttk.Frame(self._canvas)
        self._win_id = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")

        def _on_frame_configure(event):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))

        def _on_canvas_configure(event):
            self._canvas.itemconfig(self._win_id, width=event.width)

        self._inner.bind("<Configure>", _on_frame_configure)
        self._canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event):
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.top.bind("<Destroy>", lambda e: self._canvas.unbind_all("<MouseWheel>"))

        # ---- статусная строка (двойная: от логики + онлайн) ----
        status_frame = tk.Frame(self.top, bg="#F3F3F3", pady=3)
        status_frame.pack(fill=tk.X, padx=5, pady=(0, 2))

        self._count_var = tk.StringVar(value="Строк: 0")
        tk.Label(
            status_frame, textvariable=self._count_var,
            bg="#F3F3F3", fg="#555555", font=("Segoe UI", 9), anchor="w",
        ).pack(side=tk.LEFT, padx=6)

        self._online_var = tk.StringVar(value="")
        self._online_lbl = tk.Label(
            status_frame, textvariable=self._online_var,
            bg="#F3F3F3", fg="#0067C0", font=("Segoe UI", 9), anchor="e",
        )
        self._online_lbl.pack(side=tk.RIGHT, padx=6)

        # ---- кнопки ----
        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        ttk.Button(btn_frame, text="Пополнить списки",
                   command=self._save_names).pack(side=tk.LEFT, padx=5)
        self._online_btn = ttk.Button(
            btn_frame, text="Сверить онлайн",
            command=self._run_online_check,
        )
        self._online_btn.pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена",
                   command=self.top.destroy).pack(side=tk.LEFT, padx=5)

    # ------------------------------------------------------------------
    # Динамическое добавление строк
    # ------------------------------------------------------------------

    def add_rows(self, rows):
        """Добавить строки в диалог. Вызывать из UI-потока (через root.after)."""
        if not self.top.winfo_exists():
            return
        start_idx = len(self._row_data)

        for row in rows:
            if len(row) >= 5:
                source, author, name, gender, file_path = (
                    row[0], row[1], row[2], row[3], row[4])
            else:
                source, author, name, gender = row[0], row[1], row[2], row[3]
                file_path = ""
            name_var   = tk.StringVar(value=name)
            gender_var = tk.StringVar(value=gender)
            self._row_data.append((source, author, name_var, gender_var, file_path))
            self._add_row_widget(len(self._row_data) - 1,
                                 source, author, name_var, gender_var, file_path)

        total = len(self._row_data)
        self._count_var.set(f"Строк: {total}")
        if total:
            self._loading_var.set("")

    def _add_row_widget(self, row_idx, source, author, name_var, gender_var, file_path):
        """Создать виджеты для одной строки; сохранить ссылки для подсветки."""
        row_frame = ttk.Frame(self._inner)
        row_frame.pack(fill=tk.X, pady=1)

        # Источник — нередактируемый; tooltip с полным путём
        src_lbl = ttk.Label(row_frame, text=source, width=18, anchor="w",
                            relief="sunken")
        src_lbl.pack(side=tk.LEFT, padx=1)
        if file_path:
            _Tooltip(src_lbl, file_path)

        # Автор — кликабельные слова → поле Name
        author_frame = tk.Frame(row_frame, relief="sunken", bd=1, width=270, height=24)
        author_frame.pack(side=tk.LEFT, padx=1)
        author_frame.pack_propagate(False)

        if not self._default_author_bg:
            self._default_author_bg = author_frame.cget('bg')

        # Индекс этой строки в _row_status (для тултипа)
        self._row_status.append('')
        status_idx = len(self._row_status) - 1

        def _status_tip(idx=status_idx):
            return self._STATUS_LEGEND.get(self._row_status[idx], '')

        _Tooltip(author_frame, _status_tip)

        word_labels = []
        for word in author.split():
            w_lbl = tk.Label(author_frame, text=word, cursor="hand2",
                             bg=self._default_author_bg, padx=2)
            w_lbl.pack(side=tk.LEFT)
            w_lbl.bind("<Button-1>",
                       lambda e, v=word, nv=name_var: nv.set(v))
            w_lbl.bind("<Enter>",
                       lambda e, lbl=w_lbl: lbl.config(
                           fg="blue", font="TkDefaultFont 9 underline"))
            w_lbl.bind("<Leave>",
                       lambda e, lbl=w_lbl: lbl.config(
                           fg="black", font="TkDefaultFont 9"))
            _Tooltip(w_lbl, _status_tip)
            word_labels.append(w_lbl)

        self._row_ui.append((author_frame, word_labels))

        # Имя — редактируемое поле
        ttk.Entry(row_frame, textvariable=name_var, width=24).pack(
            side=tk.LEFT, padx=1)

        # Пол — выпадающий список
        ttk.Combobox(row_frame, textvariable=gender_var,
                     values=self.GENDER_OPTIONS, width=10,
                     state="readonly").pack(side=tk.LEFT, padx=1)

    # ------------------------------------------------------------------
    # Цветовая сигнализация
    # ------------------------------------------------------------------

    def _set_row_status(self, row_idx: int, status: str) -> None:
        """Подсветить поле автора в строке row_idx цветом статуса."""
        if row_idx >= len(self._row_ui):
            return
        if row_idx < len(self._row_status):
            self._row_status[row_idx] = status
        color = self._STATUS_COLORS.get(status, self._default_author_bg)
        author_frame, word_labels = self._row_ui[row_idx]
        try:
            author_frame.configure(bg=color)
            for lbl in word_labels:
                lbl.configure(bg=color)
        except tk.TclError:
            pass  # виджет уже уничтожен

    # ------------------------------------------------------------------
    # Онлайн-проверка
    # ------------------------------------------------------------------

    def _run_online_check(self):
        """Запустить онлайн-проверку для всех строк (по кнопке)."""
        if not self._service:
            messagebox.showinfo(
                "Онлайн-проверка",
                "Сервис недоступен: не удалось загрузить gender_lookup.",
            )
            return
        if not self._row_data:
            return
        self._online_btn.configure(state='disabled')
        self._online_total = 0
        self._online_done  = 0
        all_items = [(i, self._row_data[i][1]) for i in range(len(self._row_data))]
        self._start_online_check(all_items)

    def _start_online_check(self, new_items):
        """Запустить асинхронный lookup для new_items (из UI-потока)."""
        self._online_total += len(new_items)
        self._update_online_status()

        # Немедленно подсветить жёлтым (pending)
        for idx, _ in new_items:
            self._set_row_status(idx, 'pending')

        def on_result(row_idx, name_word, result):
            try:
                self.top.after(
                    0,
                    lambda: self._on_lookup_result(row_idx, name_word, result),
                )
            except Exception:
                pass

        def on_done(rate_limited=False):
            try:
                self.top.after(0, lambda: self._update_online_status(rate_limited))
                self.top.after(0, lambda: self._online_btn.configure(state='normal'))
            except Exception:
                pass

        self._service.lookup_authors_async(new_items, on_result, on_done)

    def _on_lookup_result(self, row_idx: int, name_word: str, result) -> None:
        """Обработать результат из Genderize.io (вызывается в UI-потоке)."""
        from gender_lookup import STATUS_FOUND, STATUS_UNCERTAIN, STATUS_UNKNOWN, STATUS_ERROR, STATUS_RATE_LIMIT

        self._online_done += 1
        self._update_online_status()

        if not self.top.winfo_exists():
            return
        if row_idx >= len(self._row_data):
            return

        _, _, name_var, gender_var, *_ = self._row_data[row_idx]

        if result.status in (STATUS_FOUND, STATUS_UNCERTAIN):
            # Имя — кириллическое слово из нашего автора (не от сервиса!)
            name_var.set(name_word)
            if result.gender_ru:
                gender_var.set(result.gender_ru)
            self._set_row_status(row_idx, result.status)
        elif result.status == STATUS_RATE_LIMIT:
            self._set_row_status(row_idx, 'rate_limit')
        elif result.status == STATUS_UNKNOWN:
            self._set_row_status(row_idx, 'unknown')
        else:  # STATUS_ERROR
            self._set_row_status(row_idx, 'error')

    def _update_online_status(self, rate_limited: bool = False) -> None:
        """Обновить строку прогресса онлайн-проверки."""
        if not self.top.winfo_exists():
            return
        if self._online_total == 0:
            self._online_var.set("")
            return
        done  = self._online_done
        total = self._online_total
        if rate_limited:
            self._online_var.set(
                f"Онлайн-проверка: ⚠ лимит запросов исчерпан "
                f"(выполнено {done}/{total}). Добавьте API-ключ в Настройки → Общие"
            )
            self._online_lbl.configure(fg='#990000')
        elif done < total:
            self._online_var.set(
                f"Онлайн-проверка: {done}/{total}  …"
            )
        else:
            self._online_var.set(
                f"Онлайн-проверка: завершена ({total})"
            )

    # ------------------------------------------------------------------
    # Сохранение
    # ------------------------------------------------------------------

    def _save_names(self):
        """Записать имена в списки config.json (с дедупликацией и отчётом)."""
        if not self.settings_manager:
            messagebox.showerror("Ошибка", "settings_manager не передан")
            return

        male_new = []
        female_new = []
        for _, _, name_var, gender_var, *_ in self._row_data:
            name   = name_var.get().strip()
            gender = gender_var.get().strip()
            if not name or gender not in self.GENDER_OPTIONS:
                continue
            if gender == "Муж.":
                male_new.append(name)
            elif gender == "Жен.":
                female_new.append(name)

        if not male_new and not female_new:
            messagebox.showinfo("Информация", "Нет имён для добавления")
            return

        male_added = male_skipped = 0
        female_added = female_skipped = 0

        if male_new:
            existing = set(self.settings_manager.get_male_names())
            unique_new = set(male_new)
            actual_new = unique_new - existing
            male_skipped = len(unique_new) - len(actual_new)
            male_added   = len(actual_new)
            if actual_new:
                merged = sorted(existing | actual_new, key=lambda s: s.lower())
                self.settings_manager.set_male_names(merged)

        if female_new:
            existing = set(self.settings_manager.get_female_names())
            unique_new = set(female_new)
            actual_new = unique_new - existing
            female_skipped = len(unique_new) - len(actual_new)
            female_added   = len(actual_new)
            if actual_new:
                merged = sorted(existing | actual_new, key=lambda s: s.lower())
                self.settings_manager.set_female_names(merged)

        total_added   = male_added   + female_added
        total_skipped = male_skipped + female_skipped

        msg = (
            f"Добавлено новых: {total_added} имён\n"
            f"  Мужских: {male_added},  женских: {female_added}"
        )
        if total_skipped:
            msg += f"\n\nПропущено (уже в списках): {total_skipped}"

        messagebox.showinfo("Готово", msg)
        self.top.destroy()


class FemaleAuthorsDialog:
    """Окно 'Великомученницы': файлы, у которых все авторы — женщины."""

    def __init__(self, parent, rows, work_dir=None):
        """
        Args:
            rows: список кортежей (file_path, proposed_author),
                  file_path — относительный путь от work_dir
            work_dir: Path — корневая рабочая папка (граница удаления)
        """
        from pathlib import Path as _Path
        self.work_dir = _Path(work_dir) if work_dir else None
        self._rows = list(rows)
        self.top = tk.Toplevel(parent)
        self.top.title("Великомученницы")
        try:
            from window_persistence import setup_window_persistence
            _settings = getattr(parent, 'settings', None) or getattr(
                getattr(parent, 'master', None), 'settings', None)
            if _settings is not None:
                setup_window_persistence(self.top, 'female_authors_dialog', _settings,
                                         '1000x500+100+100', parent_window=parent)
            else:
                from window_persistence import _default_geometry_near_parent
                self.top.geometry(_default_geometry_near_parent(parent, 1000, 500))
        except Exception:
            self.top.geometry('1000x500')
        self._build_ui()

    def _build_ui(self):
        # Счётчик
        self._count_var = tk.StringVar(value=f"Файлов: {len(self._rows)}")
        ttk.Label(self.top, textvariable=self._count_var).pack(
            side=tk.TOP, anchor="w", padx=8, pady=(5, 0))

        # Таблица
        frame = ttk.Frame(self.top)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL)
        self._tree = ttk.Treeview(frame, columns=("file_path", "proposed_author"),
                                  show="headings",
                                  yscrollcommand=vsb.set,
                                  xscrollcommand=hsb.set)
        vsb.config(command=self._tree.yview)
        hsb.config(command=self._tree.xview)

        self._tree.heading("file_path", text="Путь к файлу")
        self._tree.heading("proposed_author", text="Автор(ы)")
        self._tree.column("file_path", width=660, minwidth=200)
        self._tree.column("proposed_author", width=280, minwidth=120)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        for file_path, author in self._rows:
            self._tree.insert("", "end", values=(file_path, author))

        # Кнопки
        btn_frame = ttk.Frame(self.top, padding="5")
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(btn_frame, text="Удалить",
                   command=self._delete_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Закрыть",
                   command=self.top.destroy).pack(side=tk.LEFT, padx=2)

    def _delete_all(self):
        """Удалить все файлы списка и опустевшие папки выше них (не выше work_dir)."""
        import os as _os
        from pathlib import Path as _Path

        if not self._rows:
            messagebox.showinfo("Информация", "Список пуст")
            return

        if not messagebox.askyesno(
            "Подтверждение удаления",
            f"Удалить {len(self._rows)} файл(ов) и пустые директории после них?\n"
            "Это действие необратимо."
        ):
            return

        deleted_files = 0
        errors = []
        dirs_to_check = set()

        for file_path, _ in self._rows:
            if self.work_dir:
                full_path = self.work_dir / file_path
            else:
                full_path = _Path(file_path)
            try:
                if full_path.exists():
                    dirs_to_check.add(full_path.parent)
                    full_path.unlink()
                    deleted_files += 1
            except Exception as e:
                errors.append(f"{file_path}: {e}")

        # Удаление опустевших папок, поднимаясь вверх,
        # но не удаляя саму рабочую директорию
        boundary = self.work_dir.resolve() if self.work_dir else None
        dirs_sorted = sorted(
            (d.resolve() for d in dirs_to_check),
            key=lambda p: len(p.parts),
            reverse=True  # сначала самые глубокие
        )
        deleted_dirs = 0
        for start_dir in dirs_sorted:
            current = start_dir
            while True:
                if boundary and (current == boundary or
                                 not str(current).startswith(str(boundary))):
                    break
                try:
                    if current.is_dir() and not any(current.iterdir()):
                        current.rmdir()
                        deleted_dirs += 1
                        current = current.parent
                    else:
                        break
                except Exception:
                    break

        # Обновить таблицу и счётчик
        self._rows.clear()
        for iid in self._tree.get_children():
            self._tree.delete(iid)
        self._count_var.set("Файлов: 0")

        msg = f"Удалено файлов: {deleted_files}, папок: {deleted_dirs}"
        if errors:
            msg += "\n\nОшибки:\n" + "\n".join(errors)
        messagebox.showinfo("Готово", msg)


class StdoutRedirector:
    """Перехватывает вывод stdout и обновляет progress_var и логи.

    Буферизирует строки внутри потока и сбрасывает в UI-поток раз в
    _FLUSH_INTERVAL_MS мс, чтобы не переполнять event loop при 40k+ файлах.
    """
    _FLUSH_INTERVAL_MS = 100

    def __init__(self, progress_var, root, original_stdout, log_callback=None):
        self.progress_var = progress_var
        self.root = root
        self.original_stdout = original_stdout
        self.log_callback = log_callback
        self._lock = __import__('threading').Lock()
        self._pending_lines: list = []
        self._last_progress: str = ""
        self._timer_active = False

    def write(self, message):
        """Buffer the message; flush to UI at most every _FLUSH_INTERVAL_MS ms."""
        self.original_stdout.write(message)
        with self._lock:
            self._pending_lines.append(message)
            display = message.rstrip()
            if display and not display.startswith("="):
                self._last_progress = display
            if not self._timer_active:
                self._timer_active = True
                try:
                    self.root.after(self._FLUSH_INTERVAL_MS, self._flush_to_ui)
                except Exception:
                    pass

    def _flush_to_ui(self):
        """Called on the UI thread; drains the pending buffer."""
        with self._lock:
            lines = self._pending_lines[:]
            self._pending_lines.clear()
            progress = self._last_progress
            self._timer_active = False
        if progress:
            try:
                self.progress_var.set(progress)
            except Exception:
                pass
        if self.log_callback and lines:
            combined = "".join(lines)
            try:
                self.log_callback(combined)
            except Exception:
                pass

    def flush(self):
        """Flush метод для совместимости."""
        self.original_stdout.flush()


class CSVNormalizerApp:
    def __init__(self, root, folder_path=None, logger=None, settings_manager=None):
        self.root = root
        self.root.title("Нормализация")
        
        # Logger из главного окна (если передан)
        self.logger = logger
        
        # Settings manager из главного окна (если передан)
        self.settings_manager = settings_manager
        
        # Переменные
        self.folder_path = tk.StringVar()
        # Если папка передана, используем её, иначе используем по умолчанию
        if folder_path and os.path.isdir(folder_path):
            self.folder_path.set(folder_path)
        else:
            self.folder_path.set("E:/Users/dmitriy.murov/Downloads/Tribler/Downloads/Test1")
        
        # Переменная для прогресса
        self.progress_var = tk.StringVar(value="Готово")
        
        # Сервис для генерации CSV
        self.csv_service = RegenCSVService()
        self.processing = False
        
        # Окно логов и буфер логов
        self.log_window = None
        self.log_text = None
        self.log_buffer = []  # Буфер для сохранения всех логов
        
        self._log("Инициализация окна нормализации")
        
        # Создание GUI
        self.create_widgets()
        
    def create_widgets(self):
        # Верхняя панель с путем к папке
        top_frame = ttk.Frame(self.root, padding="5")
        top_frame.pack(fill=tk.X, side=tk.TOP)
        
        ttk.Label(top_frame, text="Папка для Input:").pack(side=tk.LEFT, padx=5)
        
        path_entry = ttk.Entry(top_frame, textvariable=self.folder_path, width=80)
        path_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        ttk.Button(top_frame, text="Обзор", command=self.browse_folder).pack(side=tk.LEFT, padx=5)

        # Строка поиска / фильтр
        search_frame = ttk.Frame(self.root, padding="2 0 5 0")
        search_frame.pack(fill=tk.X, side=tk.TOP)
        ttk.Label(search_frame, text="Фильтр:").pack(side=tk.LEFT, padx=5)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=60)
        search_entry.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        self.search_var.trace('w', self._apply_filter)
        ttk.Button(search_frame, text="✕", width=3,
                   command=lambda: self.search_var.set("")).pack(side=tk.LEFT)

        # Основная таблица
        table_frame = ttk.Frame(self.root, padding="5")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        
        # Scrollbars
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        
        # Treeview (таблица)
        columns = (
            "file_path", "metadata_authors", "proposed_author", "author_source",
            "metadata_series", "proposed_series", "series_source",
            "book_title", "metadata_genre", "series_number"
        )
        
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show='headings',
            yscrollcommand=v_scrollbar.set,
            xscrollcommand=h_scrollbar.set
        )
        
        # Настройка scrollbars
        v_scrollbar.config(command=self.tree.yview)
        h_scrollbar.config(command=self.tree.xview)
        
        # Заголовки столбцов
        column_names = {
            "file_path": "file_path",
            "metadata_authors": "metadata_authors",
            "proposed_author": "proposed_author",
            "author_source": "author_source",
            "metadata_series": "metadata_series",
            "proposed_series": "proposed_series",
            "series_source": "series_source",
            "book_title": "book_title",
            "metadata_genre": "metadata_genre",
            "series_number": "series_number",
        }
        
        for col in columns:
            self.tree.heading(col, text=column_names[col])
            self.tree.column(col, width=120, minwidth=80)
        
        # Размещение элементов таблицы
        self.tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        # Панель кнопок (самая нижняя)
        buttons_frame = ttk.Frame(self.root, padding="5")
        buttons_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        ttk.Button(buttons_frame, text="Создать CSV", command=self.create_csv).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Отмена", command=self.cancel).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Получить имена", command=self.get_names).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Битые файлы", command=self.show_broken_files).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Великомученницы", command=self.show_templates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Дубликаты", command=self.show_duplicates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Удалить пустые папки", command=self.delete_empty_folders).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Скомпилировать", command=self.open_compiler).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Логи", command=self.show_logs).pack(side=tk.LEFT, padx=2)
        
        # Панель прогресса (над кнопками)
        progress_frame = ttk.Frame(self.root, padding="5")
        progress_frame.pack(fill=tk.X, side=tk.BOTTOM)
        progress_frame.grid_columnconfigure(1, weight=1)
        
        ttk.Label(progress_frame, text="Статус:").grid(row=0, column=0, sticky='w', padx=5)
        ttk.Label(progress_frame, textvariable=self.progress_var, foreground="blue").grid(row=0, column=1, sticky='ew', padx=5)
        
    def _log(self, message: str):
        """Логирование в основной логер приложения, консоль, прогресс и окно логов."""
        import datetime
        
        # Формируем сообщение с временем
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        # Логируем в основной логер приложения (если есть)
        if self.logger:
            self.logger.log(message)
        
        # Логируем в консоль
        print(f"[NORMALIZER] {formatted_message}", file=sys.stdout)
        sys.stdout.flush()
        
        # Добавляем в окно логов (если оно открыто)
        self._add_log(f"[NORMALIZER] {formatted_message}\n")
        
        # Обновляем прогресс-строку (потокобезопасно)
        try:
            self.root.after(0, lambda: self.progress_var.set(formatted_message))
        except:
            pass  # Игнорируем ошибки если окно закрыто
        
        
    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_path.get())
        if folder:
            self.folder_path.set(folder)
            self._log(f"Папка выбрана: {folder}")
            
    def create_csv(self):
        """Создать CSV из FB2 файлов в папке."""
        folder = self.folder_path.get()
        self._log(f"Начало создания CSV для папки: {folder}")
        
        if not folder or not os.path.isdir(folder):
            self._log(f"ОШИБКА: Папка не существует или не указана: {folder}")
            messagebox.showerror("Ошибка", "Укажите корректную папку", parent=self.root)
            return

        # Проверить наличие FB2-файлов до запуска потока
        fb2_count = sum(1 for _ in Path(folder).rglob('*.fb2'))
        if fb2_count == 0:
            self._log("ОШИБКА: В указанной папке нет FB2-файлов")
            messagebox.showwarning(
                "Папка пуста",
                f"В папке нет FB2-файлов:\n{folder}\n\n"
                "Укажите папку с FB2-файлами.",
                parent=self.root
            )
            return
        
        if self.processing:
            self._log("ОШИБКА: Обработка уже в процессе")
            messagebox.showwarning("Внимание", "Обработка уже в процессе", parent=self.root)
            return
        
        # Запустить обработку в отдельном потоке
        self.processing = True
        self._log("Запуск потока генерации CSV")
        thread = threading.Thread(
            target=self._process_csv_thread,
            args=(folder,),
            daemon=True
        )
        thread.start()
    
    def _process_csv_thread(self, folder_path: str):
        """Обработка CSV в отдельном потоке."""
        # Создаём свежий экземпляр сервиса перед каждым запуском
        # (как при вызове python regen_csv.py — читает актуальный config.json)
        self.csv_service = RegenCSVService()
        original_stdout = sys.stdout
        
        try:
            self._log(f"Начало генерации CSV для папки: {folder_path}")
            
            def progress_callback(current, total, status):
                """Обновить прогресс в UI."""
                self._log(f"Прогресс: {current}/{total} - {status}")
                # Обновить прогресс в интерфейсе
                self.root.after(0, lambda: self.progress_var.set(f"{status} ({current}/{total})"))
            
            # Определяем путь сохранения CSV если нужно
            output_csv_path = None
            if self.settings_manager and self.settings_manager.get_generate_csv():
                # Сохраняем в папку проекта с именем regen.csv
                output_csv_path = str(Path(__file__).parent / 'regen.csv')
                self._log(f"CSV будет сохранён в: {output_csv_path}")
            else:
                self._log("Параметр 'Генерировать CSV-файл' отключен - CSV не будет сохранён")
            
            # Генерировать CSV
            self._log("Запуск сервиса генерации CSV")
            
            # Перенаправляем stdout для перехвата логов из всех модулей
            redirector = StdoutRedirector(self.progress_var, self.root, original_stdout, log_callback=self._add_log)
            sys.stdout = redirector
            
            try:
                records = self.csv_service.generate_csv(
                    folder_path,
                    output_csv_path=output_csv_path,
                    progress_callback=progress_callback
                )
            finally:
                # Восстанавливаем оригинальный stdout
                sys.stdout = original_stdout
            
            self._log(f"CSV сгенерирован: {len(records)} записей")
            if output_csv_path:
                self._log(f"CSV-файл сохранён: {output_csv_path}")
            
            # Обновить таблицу в UI
            self.root.after(0, lambda: self._fill_table(records))
            
            # Показать результат
            self.root.after(
                0,
                lambda: messagebox.showinfo(
                    "Готово",
                    f"Обработано {len(records)} файлов\nТаблица обновлена",
                    parent=self.root
                )
            )
            self._log(f"Обработка завершена успешно: {len(records)} файлов")
            self.root.after(0, lambda: self.progress_var.set("Готово"))
        except Exception as e:
            self._log(f"ОШИБКА при обработке CSV: {str(e)}")
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "Ошибка",
                    f"Ошибка при обработке: {str(e)}",
                    parent=self.root
                )
            )
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))
        finally:
            # Убедимся, что stdout восстановлен
            sys.stdout = original_stdout
            self.processing = False
    
    def _apply_filter(self, *_):
        """Re-display table using current search query."""
        PAGE_SIZE = 1000
        query = self.search_var.get().lower().strip() if hasattr(self, 'search_var') else ''
        all_records = getattr(self, '_all_records', [])
        if not query:
            self._display_records = all_records
        else:
            self._display_records = [
                r for r in all_records
                if query in ' '.join(str(v) for v in r.to_tuple()).lower()
            ]
        # Reload Treeview from scratch
        for item in self.tree.get_children():
            self.tree.delete(item)
        if hasattr(self, '_load_more_btn') and self._load_more_btn:
            try:
                self._load_more_btn.destroy()
            except Exception:
                pass
            self._load_more_btn = None
        self._records_offset = 0
        self._load_more_rows(PAGE_SIZE)
        if self._records_offset < len(self._display_records):
            remaining = len(self._display_records) - self._records_offset
            self._load_more_btn = ttk.Button(
                self.root,
                text=f"Загрузить ещё ({remaining} записей)",
                command=lambda: self._load_more_rows(PAGE_SIZE)
            )
            self._load_more_btn.pack(side=tk.BOTTOM, pady=2, before=self.tree.master)
        else:
            self._load_more_btn = None

    def _fill_table(self, records):
        """Заполнить таблицу записями (пагинация: первые PAGE_SIZE строк + кнопка 'Загрузить ещё')."""
        PAGE_SIZE = 1000

        # Очистить таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Удалить старую кнопку 'Загрузить ещё', если есть
        if hasattr(self, '_load_more_btn') and self._load_more_btn:
            try:
                self._load_more_btn.destroy()
            except Exception:
                pass
            self._load_more_btn = None

        self._all_records = records
        self._display_records = records  # No filter active yet
        self._records_offset = 0

        # Вставить первую страницу
        self._load_more_rows(PAGE_SIZE)

        # Если ещё остались записи, добавить кнопку 'Загрузить ещё'
        if self._records_offset < len(self._display_records):
            remaining = len(self._display_records) - self._records_offset
            btn_frame = self.tree.master  # table_frame
            self._load_more_btn = ttk.Button(
                self.root,
                text=f"Загрузить ещё ({remaining} записей)",
                command=lambda: self._load_more_rows(PAGE_SIZE)
            )
            self._load_more_btn.pack(side=tk.BOTTOM, pady=2, before=self.tree.master)
        else:
            self._load_more_btn = None

    def _load_more_rows(self, count: int):
        """Insert up to *count* rows starting at self._records_offset."""
        display = getattr(self, '_display_records', getattr(self, '_all_records', []))
        end = min(self._records_offset + count, len(display))
        for record in display[self._records_offset:end]:
            self.tree.insert('', tk.END, values=record.to_tuple())
        self._records_offset = end

        # Удалить кнопку если всё загружено
        if self._records_offset >= len(display):
            if hasattr(self, '_load_more_btn') and self._load_more_btn:
                try:
                    self._load_more_btn.destroy()
                except Exception:
                    pass
                self._load_more_btn = None
        elif hasattr(self, '_load_more_btn') and self._load_more_btn:
            remaining = len(display) - self._records_offset
            self._load_more_btn.config(text=f"Загрузить ещё ({remaining} записей)")
        
    def cancel(self):
        if messagebox.askyesno("Подтверждение", "Вы уверены, что хотите отменить?"):
            # Закрываем окно логов если оно открыто
            if self.log_window is not None and self.log_window.winfo_exists():
                self.log_window.destroy()
            # Очищаем логи
            self.log_text = None
            self.log_window = None
            self.log_buffer = []
            self.root.quit()
            
    def get_names(self):
        """Запустить только авторскую часть pipeline и показать окно имён."""
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("Ошибка", "Укажите корректную папку")
            return
        fb2_count = sum(1 for _ in Path(folder).rglob('*.fb2'))
        if fb2_count == 0:
            messagebox.showwarning("Папка пуста",
                f"В папке нет FB2-файлов:\n{folder}",
                parent=self.root)
            return
        if self.processing:
            messagebox.showwarning("Внимание", "Обработка уже в процессе")
            return
        self.processing = True
        self._log("Запуск извлечения авторов...")
        thread = threading.Thread(
            target=self._run_author_pipeline,
            args=(folder,),
            daemon=True
        )
        thread.start()

    def _run_author_pipeline(self, folder_path: str):
        """Прогнать полный пайплайн (без записи CSV) и показать окно имён.

        Используем csv_service.generate_csv(output_csv_path=None) — это
        запускает все пассы (Pass1-Pass6), но не создаёт файл на диске.
        Результат идентичен тому, что попало бы в regen.csv.
        """
        original_stdout = sys.stdout
        redirector = StdoutRedirector(self.progress_var, self.root, original_stdout,
                                      log_callback=self._add_log)
        sys.stdout = redirector

        # ── Открыть диалог немедленно (пустым) на UI-потоке ─────────────────
        dialog_ref = [None]
        ready_event = threading.Event()

        def _open_dialog():
            d = NamesDialog(self.root, [], self.settings_manager)
            d._loading_var.set("Обработка данных…")
            dialog_ref[0] = d
            ready_event.set()

        self.root.after(0, _open_dialog)
        ready_event.wait()

        try:
            self.root.after(0, lambda: self.progress_var.set("Запуск пайплайна…"))
            records = self.csv_service.generate_csv(
                folder_path,
                output_csv_path=None,   # не писать файл
            )

            # ── Фильтрация + стриминг строк в диалог ─────────────────────────
            import re as _re
            settings = self.settings_manager if self.settings_manager else self.csv_service.settings
            male_set   = {n.lower() for n in settings.get_male_names()}
            female_set = {n.lower() for n in settings.get_female_names()}

            BATCH_SIZE = 25
            batch: list = []
            seen:  set  = set()

            def _flush(b):
                d = dialog_ref[0]
                if d and d.top.winfo_exists():
                    d.add_rows(b)

            for rec in records:
                combined  = rec.proposed_author or ""
                source    = rec.author_source   or ""
                file_path = rec.file_path       or ""
                if not combined or combined == "Сборник":
                    continue

                authors = [a.strip() for a in _re.split(r'[,;]+', combined) if a.strip()]
                for author in authors:
                    if author in seen:
                        continue
                    seen.add(author)

                    parts = author.split()
                    first_name = parts[1] if len(parts) >= 2 else ""

                    gender = ""
                    for word in parts:
                        w = word.lower()
                        if w in male_set:
                            gender = "Муж."
                            break
                        if w in female_set:
                            gender = "Жен."
                            break

                    # Показываем только тех, чьё имя ещё не в списках
                    if gender:
                        continue

                    batch.append((source, author, first_name, gender, file_path))
                    if len(batch) >= BATCH_SIZE:
                        chunk = batch[:]
                        self.root.after(0, lambda c=chunk: _flush(c))
                        batch = []

            if batch:
                chunk = batch[:]
                self.root.after(0, lambda c=chunk: _flush(c))

            total_sent = len(seen)
            self.root.after(0, lambda: self.progress_var.set(
                f"Готово — найдено {total_sent} уникальных авторов"
            ))

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"{e}\n\n{tb}"))
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))
        finally:
            sys.stdout = original_stdout
            self.processing = False

    def _run_female_pipeline(self, folder_path: str):
        """Найти файлы, у которых все авторы — женщины."""
        original_stdout = sys.stdout
        try:
            from pathlib import Path as _Path
            from precache import Precache
            from passes.pass1_read_files import Pass1ReadFiles
            from passes.pass2_filename import Pass2Filename
            from passes.pass2_fallback import Pass2Fallback
            from fb2_author_extractor import FB2AuthorExtractor
            from logger import Logger
        except ImportError:
            from pathlib import Path as _Path
            from .precache import Precache
            from .passes.pass1_read_files import Pass1ReadFiles
            from .passes.pass2_filename import Pass2Filename
            from .passes.pass2_fallback import Pass2Fallback
            from .fb2_author_extractor import FB2AuthorExtractor
            from .logger import Logger

        redirector = StdoutRedirector(self.progress_var, self.root, original_stdout,
                                      log_callback=self._add_log)
        sys.stdout = redirector
        try:
            import re as _re
            work_dir = _Path(folder_path)
            settings = self.settings_manager if self.settings_manager else self.csv_service.settings
            logger = self.csv_service.logger
            folder_parse_limit = self.csv_service.folder_parse_limit
            extractor = FB2AuthorExtractor()

            self.root.after(0, lambda: self.progress_var.set("Кеширование папок..."))
            precache = Precache(work_dir, settings, logger, folder_parse_limit)
            precache.execute()

            self.root.after(0, lambda: self.progress_var.set("Чтение файлов..."))
            pass1 = Pass1ReadFiles(work_dir, precache.author_folder_cache,
                                   extractor, logger, folder_parse_limit)
            records = pass1.execute()

            self.root.after(0, lambda: self.progress_var.set("Извлечение авторов..."))
            pass2 = Pass2Filename(settings, logger, work_dir,
                                  male_names=precache.male_names,
                                  female_names=precache.female_names)
            pass2.prebuild_author_cache(records)
            pass2.execute(records)

            pass2_fallback = Pass2Fallback(logger, settings=settings)
            pass2_fallback.execute(records)

            male_set = set(n.lower() for n in settings.get_male_names())
            female_set = set(n.lower() for n in settings.get_female_names())

            def is_female_author(author_str: str) -> bool:
                """Автор женщина: ни одно слово не мужское, хотя бы одно женское."""
                parts = author_str.split()
                if not parts:
                    return False
                for word in parts:
                    if word.lower() in male_set:
                        return False
                for word in parts:
                    if word.lower() in female_set:
                        return True
                return False

            rows = []
            for rec in records:
                combined = rec.proposed_author or ""
                if not combined or combined == "Сборник":
                    continue
                authors = [a.strip() for a in _re.split(r'[,;]+', combined) if a.strip()]
                if authors and all(is_female_author(a) for a in authors):
                    rows.append((rec.file_path, combined))

            self.root.after(0, lambda: self.progress_var.set("Готово"))
            self.root.after(0, lambda: FemaleAuthorsDialog(self.root, rows, work_dir))
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"{e}\n\n{tb}"))
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))
        finally:
            sys.stdout = original_stdout
            self.processing = False

    def _filter_female_authors(self, records: list):
        """Найти файлы с авторами-женщинами из уже загруженных records.

        Не перезапускает pipeline — использует готовые proposed_author.
        """
        try:
            import re as _re
            settings = self.settings_manager if self.settings_manager else self.csv_service.settings
            male_set   = set(n.lower() for n in settings.get_male_names())
            female_set = set(n.lower() for n in settings.get_female_names())

            def is_female_author(author_str: str) -> bool:
                parts = author_str.split()
                if not parts:
                    return False
                for word in parts:
                    if word.lower() in male_set:
                        return False
                for word in parts:
                    if word.lower() in female_set:
                        return True
                return False

            self.root.after(0, lambda: self.progress_var.set("Фильтрация авторов…"))
            rows = []
            for rec in records:
                combined = rec.proposed_author or ""
                if not combined or combined in ("Сборник", "Соавторство", "[unknown]"):
                    continue
                authors = [a.strip() for a in _re.split(r'[,;]+', combined) if a.strip()]
                if authors and all(is_female_author(a) for a in authors):
                    rows.append((rec.file_path, combined))

            work_dir = self.folder_path.get()
            self.root.after(0, lambda: self.progress_var.set(f"Найдено: {len(rows)} файлов"))
            self.root.after(0, lambda: FemaleAuthorsDialog(self.root, rows, work_dir))
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"{e}\n\n{tb}"))
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))

    def apply_changes(self):
        messagebox.showinfo("Информация", "Применение изменений")

    def show_broken_files(self):
        try:
            from gui_broken_files import BrokenFilesWindow
        except ImportError:
            try:
                from .gui_broken_files import BrokenFilesWindow
            except ImportError:
                from fb2parser.gui_broken_files import BrokenFilesWindow
        
        BrokenFilesWindow(self.root, self.settings_manager)
        self._log("Окно 'Битые файлы' открыто")
        
    def show_templates(self):
        folder = self.folder_path.get()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Внимание", "Укажите корректную рабочую папку")
            return

        # Если pipeline уже прогнан — используем готовые records, не перезапускаем.
        existing_records = getattr(self, '_all_records', [])
        if existing_records:
            self._log("Поиск файлов с авторами-женщинами (из текущих данных)...")
            thread = threading.Thread(
                target=self._filter_female_authors,
                args=(existing_records,),
                daemon=True,
            )
            thread.start()
            return

        fb2_count = sum(1 for _ in Path(folder).rglob('*.fb2'))
        if fb2_count == 0:
            messagebox.showwarning("Папка пуста",
                f"В папке нет FB2-файлов:\n{folder}",
                parent=self.root)
            return
        if self.processing:
            messagebox.showwarning("Внимание", "Обработка уже в процессе")
            return
        self.processing = True
        self._log("Поиск файлов с авторами-женщинами (полный пайплайн)...")
        thread = threading.Thread(
            target=self._run_female_pipeline,
            args=(folder,),
            daemon=True
        )
        thread.start()
        
    def show_duplicates(self):
        try:
            from gui_duplicate_finder import DuplicateFinderWindow
        except ImportError:
            try:
                from .gui_duplicate_finder import DuplicateFinderWindow
            except ImportError:
                from fb2parser.gui_duplicate_finder import DuplicateFinderWindow
        
        DuplicateFinderWindow(self.root, self.settings_manager)
        self._log("Окно 'Поиск дубликатов' открыто")
        
    def open_compiler(self):
        """Открыть диалог компиляции серий."""
        records = getattr(self, '_all_records', [])
        if not records:
            messagebox.showwarning('Внимание',
                'Сначала создайте CSV (загрузите данные в таблицу).',
                parent=self.root)
            return

        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showerror('Ошибка', 'Укажите корректную папку.', parent=self.root)
            return

        try:
            try:
                from gui_compiler import CompilerDialog
            except ImportError:
                from .gui_compiler import CompilerDialog
            CompilerDialog(
                parent=self.root,
                records=records,
                work_dir=Path(folder),
                logger=self.logger,
            )
        except Exception as e:
            self._log(f'Ошибка открытия компилятора: {e}')
            messagebox.showerror('Ошибка', str(e), parent=self.root)

    def delete_empty_folders(self):
        if messagebox.askyesno("Подтверждение", "Удалить пустые папки?"):
            messagebox.showinfo("Информация", "Пустые папки удалены")
            
    def show_logs(self):
        """Открыть окно логов."""
        if self.log_window is not None and self.log_window.winfo_exists():
            # Окно уже открыто, просто поднимаем его на передний план
            self.log_window.lift()
            self.log_window.focus()
            return
        
        # Создаем новое окно логов
        self.log_window = tk.Toplevel(self.root)
        self.log_window.title("Логи нормализации")
        try:
            from window_persistence import setup_window_persistence
            _settings = getattr(self, 'settings_manager', None) or getattr(
                self.csv_service, 'settings', None)
            if _settings:
                setup_window_persistence(self.log_window, 'normalizer_log', _settings,
                                         '800x400+100+100', parent_window=self.root)
            else:
                from window_persistence import _default_geometry_near_parent
                self.log_window.geometry(_default_geometry_near_parent(self.root, 800, 400))
        except Exception:
            self.log_window.geometry('800x400')
        
        # Frame с Text и Scrollbar
        frame = ttk.Frame(self.log_window)
        frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        scrollbar.grid(row=0, column=1, sticky='ns')
        
        # Text widget для логов
        self.log_text = tk.Text(
            frame,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            bg='#f5f5f5',
            font=('Courier', 9)
        )
        scrollbar.config(command=self.log_text.yview)
        self.log_text.grid(row=0, column=0, sticky='nsew')
        
        # Загружаем все сохраненные логи в текстовое окно
        for log_line in self.log_buffer:
            self.log_text.insert(tk.END, log_line)
        
        # Прокрутка к концу
        self.log_text.see(tk.END)
        
        # Кнопка очистки логов
        button_frame = ttk.Frame(self.log_window)
        button_frame.pack(fill=tk.X, padx=5, pady=5)
        
        ttk.Button(button_frame, text="Очистить логи", command=self._clear_logs).pack(side=tk.LEFT, padx=2)
        ttk.Button(button_frame, text="Копировать все", command=self._copy_logs).pack(side=tk.LEFT, padx=2)
        
        self._log("Открыто окно логов")
    
    def _add_log(self, message: str):
        """Добавить текст в буфер логов и в окно если оно открыто."""
        # Всегда добавляем в буфер
        self.log_buffer.append(message)
        
        # Добавляем в Text widget если окно открыто
        if self.log_text is not None:
            try:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.insert(tk.END, message)
                # Автопрокрутка к последней строке
                self.log_text.see(tk.END)
            except:
                pass  # Игнорируем ошибки если окно закрыто
    
    def _clear_logs(self):
        """Очистить логи."""
        # Очищаем буфер
        self.log_buffer = []
        
        # Очищаем Text widget если открыт
        if self.log_text is not None:
            try:
                self.log_text.config(state=tk.NORMAL)
                self.log_text.delete(1.0, tk.END)
                self._log("Логи очищены")
            except:
                pass
    
    def _copy_logs(self):
        """Копировать все логи в буфер обмена."""
        if self.log_text is not None:
            try:
                content = self.log_text.get(1.0, tk.END)
                self.root.clipboard_clear()
                self.root.clipboard_append(content)
                self._log("Логи скопированы в буфер обмена")
            except:
                pass

def main():
    root = tk.Tk()
    app = CSVNormalizerApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()