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


class NamesDialog:
    """Окно просмотра и редактирования извлечённых имён авторов."""

    GENDER_OPTIONS = ("Муж.", "Жен.")

    def __init__(self, parent, rows, settings_manager):
        """
        Args:
            rows: список кортежей (author_source, proposed_author, first_name, gender)
            settings_manager: экземпляр SettingsManager
        """
        self.settings_manager = settings_manager
        self.top = tk.Toplevel(parent)
        self.top.title("Имена авторов")
        self.top.geometry("860x500")
        self.top.transient(parent)
        self.top.grab_set()

        # Данные строк: (author_source, proposed_author, StringVar(name), StringVar(gender))
        self._row_data = []
        for source, author, name, gender in rows:
            self._row_data.append((source, author, tk.StringVar(value=name),
                                   tk.StringVar(value=gender)))

        self._build_ui()

    def _build_ui(self):
        # ---- заголовок таблицы ----
        hdr = ttk.Frame(self.top)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        for text, w in (("author_source", 130), ("proposed_author", 280),
                        ("Names", 180), ("Gender", 120)):
            ttk.Label(hdr, text=text, relief="groove", width=w // 7,
                      anchor="w").pack(side=tk.LEFT, padx=1)

        # ---- прокручиваемый canvas ----
        container = ttk.Frame(self.top)
        container.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        canvas = tk.Canvas(container, borderwidth=0, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        def _on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(win_id, width=event.width)

        self._inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Прокрутка колесом мыши
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.top.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ---- строки данных ----
        for i, (source, author, name_var, gender_var) in enumerate(self._row_data):
            row_frame = ttk.Frame(self._inner)
            row_frame.pack(fill=tk.X, pady=1)

            # author_source — нередактируемое
            ttk.Label(row_frame, text=source, width=18, anchor="w",
                      relief="sunken").pack(side=tk.LEFT, padx=1)

            # proposed_author — кликабельные блоки (разделитель — пробел, дефис не делит)
            author_frame = tk.Frame(row_frame, relief="sunken", bd=1,
                                    width=270, height=24)
            author_frame.pack(side=tk.LEFT, padx=1)
            author_frame.pack_propagate(False)

            bg = author_frame.cget("bg")
            for word in author.split():
                w_lbl = tk.Label(author_frame, text=word, cursor="hand2",
                                 bg=bg, padx=2)
                w_lbl.pack(side=tk.LEFT)
                # ЛКМ — записать слово в Name
                w_lbl.bind("<Button-1>",
                           lambda e, v=word, nv=name_var: nv.set(v))
                # Подсветка при наведении
                w_lbl.bind("<Enter>",
                           lambda e, lbl=w_lbl: lbl.config(
                               fg="blue", font="TkDefaultFont 9 underline"))
                w_lbl.bind("<Leave>",
                           lambda e, lbl=w_lbl: lbl.config(
                               fg="black", font="TkDefaultFont 9"))

            # Names — редактируемое
            ttk.Entry(row_frame, textvariable=name_var, width=24).pack(
                side=tk.LEFT, padx=1)
            # Gender — выпадающий список
            cb = ttk.Combobox(row_frame, textvariable=gender_var,
                              values=self.GENDER_OPTIONS, width=10, state="readonly")
            cb.pack(side=tk.LEFT, padx=1)

        # ---- кнопки внизу ----
        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="Пополнить списки",
                   command=self._save_names).pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Отмена",
                   command=self.top.destroy).pack(side=tk.LEFT, padx=5)

    def _save_names(self):
        """Записать имена в списки config.json и отсортировать их по алфавиту."""
        if not self.settings_manager:
            messagebox.showerror("Ошибка", "settings_manager не передан")
            return

        male_new = []
        female_new = []
        for _, _, name_var, gender_var in self._row_data:
            name = name_var.get().strip()
            gender = gender_var.get()
            if not name:
                continue
            if gender == "Муж.":
                male_new.append(name)
            elif gender == "Жен.":
                female_new.append(name)

        if not male_new and not female_new:
            messagebox.showinfo("Информация", "Нет имён для добавления")
            return

        # Добавляем к существующим, дедупликация + сортировка
        if male_new:
            existing = self.settings_manager.get_male_names()
            merged = sorted(set(existing + male_new), key=lambda s: s.lower())
            self.settings_manager.set_male_names(merged)

        if female_new:
            existing = self.settings_manager.get_female_names()
            merged = sorted(set(existing + female_new), key=lambda s: s.lower())
            self.settings_manager.set_female_names(merged)

        added = len(male_new) + len(female_new)
        messagebox.showinfo("Готово",
                            f"Добавлено / обновлено: {added} имён\n"
                            f"Мужских: {len(male_new)}, женских: {len(female_new)}")
        self.top.destroy()


class StdoutRedirector:
    """Перехватывает вывод stdout и обновляет progress_var и логи."""
    def __init__(self, progress_var, root, original_stdout, log_callback=None):
        self.progress_var = progress_var
        self.root = root
        self.original_stdout = original_stdout
        self.log_callback = log_callback  # Функция для добавления текста в логи
        self.buffer = ""
    
    def write(self, message):
        """Перехватить вывод и обновить progress_var и логи."""
        self.original_stdout.write(message)  # Также выводим в оригинальный stdout
        
        # Очищаем управляющие символы для отображения в progress
        display_message = message.rstrip()
        if display_message and not display_message.startswith("="):
            # Обновляем progress_var (потокобезопасно)
            try:
                self.root.after(0, lambda: self.progress_var.set(display_message))
            except:
                pass
        
        # Добавляем в логи окна
        if self.log_callback:
            try:
                self.root.after(0, lambda msg=message: self.log_callback(msg))
            except:
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
            "book_title", "metadata_genre"
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
            "metadata_genre": "metadata_genre"
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
        ttk.Button(buttons_frame, text="Шаблоны", command=self.show_templates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Дубликаты", command=self.show_duplicates).pack(side=tk.LEFT, padx=2)
        ttk.Button(buttons_frame, text="Удалить пустые папки", command=self.delete_empty_folders).pack(side=tk.LEFT, padx=2)
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
            messagebox.showerror("Ошибка", "Укажите корректную папку")
            return
        
        if self.processing:
            self._log("ОШИБКА: Обработка уже в процессе")
            messagebox.showwarning("Внимание", "Обработка уже в процессе")
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
        # Сохраняем оригинальный stdout
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
                    f"Обработано {len(records)} файлов\nТаблица обновлена"
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
                    f"Ошибка при обработке: {str(e)}"
                )
            )
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))
        finally:
            # Убедимся, что stdout восстановлен
            sys.stdout = original_stdout
            self.processing = False
    
    def _fill_table(self, records):
        """Заполнить таблицу записями."""
        # Очистить таблицу
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # Добавить записи
        for record in records:
            self.tree.insert(
                '',
                tk.END,
                values=record.to_tuple()
            )
        
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
        """Запустить только Precache + Pass1 + Pass2 + Pass2Fallback."""
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
            work_dir = _Path(folder_path)
            # Приоритет: settings_manager из главного окна (актуален после сохранения имён);
            # fallback — внутренний settings csv_service (другой экземпляр, может быть устаревшим)
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

            pass2_fallback = Pass2Fallback(logger)
            pass2_fallback.execute(records)

            # Собрать уникальные имена (второе слово из "Фамилия Имя")
            male_set = set(n.lower() for n in settings.get_male_names())
            female_set = set(n.lower() for n in settings.get_female_names())

            rows = []
            seen = set()  # деdup по одному автору
            for rec in records:
                combined = rec.proposed_author or ""
                source = rec.author_source or ""
                if not combined or combined == "Сборник":
                    continue

                # Разбить на отдельных авторов (разделители: ", " или "; ")
                import re as _re
                authors = [a.strip() for a in _re.split(r'[,;]+', combined) if a.strip()]

                for author in authors:
                    key = author
                    if key in seen:
                        continue
                    seen.add(key)

                    # Второе слово = имя (формат "Фамилия Имя ...")
                    parts = author.split()
                    first_name = parts[1] if len(parts) >= 2 else ""

                    # Определить пол по списку
                    fn_lower = first_name.lower()
                    if fn_lower in male_set:
                        gender = "Муж."
                    elif fn_lower in female_set:
                        gender = "Жен."
                    else:
                        gender = ""  # неизвестно

                    # Показывать только тех, чьё имя ещё не в списках
                    if gender != "":
                        continue
                    rows.append((source, author, first_name, gender))

            self.root.after(0, lambda: self.progress_var.set("Готово"))
            self.root.after(0, lambda: NamesDialog(self.root, rows, self.settings_manager))
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.root.after(0, lambda: messagebox.showerror("Ошибка", f"{e}\n\n{tb}"))
            self.root.after(0, lambda: self.progress_var.set("ОШИБКА"))
        finally:
            sys.stdout = original_stdout
            self.processing = False

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
        messagebox.showinfo("Информация", "Показать шаблоны")
        
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
        self.log_window.transient(self.root)  # Сделать окно зависимым от главного
        self.log_window.grab_set()  # Перехватить фокус - окно модальное
        self.log_window.geometry("800x400")
        
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