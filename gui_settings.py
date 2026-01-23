"""Окно настроек: выбор пути к библиотеке, сохранение."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Обработка импортов
try:
    # PRIORITY: Прямой импорт из текущей директории
    import settings_manager
    import importlib
    importlib.reload(settings_manager)
    from settings_manager import SettingsManager
    from window_manager import get_window_manager
except Exception:
    try:
        # Fallback: Относительный импорт
        from .settings_manager import SettingsManager
        from .window_manager import get_window_manager
    except Exception:
        # Last resort: Абсолютный импорт
        from fb2parser.settings_manager import SettingsManager
        from fb2parser.window_manager import get_window_manager


class SettingsWindow(tk.Toplevel):
    def __init__(self, master, settings_manager):
        super().__init__(master)
        self.title('Настройки')
        self.settings_manager = settings_manager
        self.master_window = master

        # Восстановление размеров окна из настроек
        geometry = self.settings_manager.get_window_geometry('settings')
        if geometry:
            self.geometry(geometry)
        else:
            self.geometry('600x400')
        self.result = None

        # Управление окном через менеджер
        window_manager = get_window_manager()
        window_manager.open_child_window(
            master, 
            self,
            on_close=self._on_window_closing
        )

        # Main layout - use Notebook (tabs)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)

        # General tab
        self.tab_general = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_general, text='Общие')
        self._create_general_tab()

        # Lists tab
        self.tab_lists = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_lists, text='Списки')
        self._create_lists_tab()

        # Buttons frame
        btns = ttk.Frame(self)
        btns.pack(side='bottom', fill='x', padx=10, pady=10)
        ttk.Button(btns, text='Сохранить', command=self._save).pack(side='left', padx=(0, 10))
        ttk.Button(btns, text='Отмена', command=lambda: get_window_manager().close_window(self)).pack(side='left')

    def _create_general_tab(self):
        """Create General settings tab."""
        self.path_var = tk.StringVar(value=self.settings_manager.get_library_path())
        ttk.Label(self.tab_general, text='Путь к библиотеке:').pack(anchor='w', padx=10, pady=(10, 0))
        
        # Frame for entry and button side by side
        entry_frame = ttk.Frame(self.tab_general)
        entry_frame.pack(fill='x', padx=10, pady=5)
        entry_frame.columnconfigure(0, weight=1)  # Entry expands
        
        entry = ttk.Entry(entry_frame, textvariable=self.path_var)
        entry.grid(row=0, column=0, sticky='ew', padx=(0, 5))
        entry.focus_set()
        entry.bind('<Return>', lambda event: self._save())
        
        ttk.Button(entry_frame, text='Обзор', command=self._choose_folder).grid(row=0, column=1)
        
        # Separator
        ttk.Separator(self.tab_general, orient='horizontal').pack(fill='x', padx=10, pady=10)
        
        # Folder parse limit
        self.folder_limit_var = tk.StringVar(value=str(self.settings_manager.get_folder_parse_limit()))
        
        limit_frame = ttk.Frame(self.tab_general)
        limit_frame.pack(fill='x', padx=10, pady=5)
        limit_frame.columnconfigure(1, weight=1)
        
        ttk.Label(limit_frame, text='Предел количества папок при парсинге, начиная от файла:').grid(row=0, column=0, sticky='w', padx=(0, 5))
        
        # Entry for limit with validation
        limit_entry = ttk.Entry(limit_frame, textvariable=self.folder_limit_var, width=10)
        limit_entry.grid(row=0, column=1, sticky='w')
        limit_entry.bind('<FocusOut>', self._validate_folder_limit)
        limit_entry.bind('<Return>', lambda event: self._save())
        
        # Separator
        ttk.Separator(self.tab_general, orient='horizontal').pack(fill='x', padx=10, pady=10)
        
        # CSV generation setting
        self.generate_csv_var = tk.BooleanVar(value=self.settings_manager.get_generate_csv())
        csv_frame = ttk.Frame(self.tab_general)
        csv_frame.pack(fill='x', padx=10, pady=5)
        
        ttk.Checkbutton(
            csv_frame,
            text='Генерировать CSV-файл при нормализации',
            variable=self.generate_csv_var
        ).pack(anchor='w')


    def _create_lists_tab(self):
        """Create Lists management tab."""
        # Main container with grid
        main_frame = ttk.Frame(self.tab_lists)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)
        main_frame.columnconfigure(0, weight=2)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(2, weight=1)  # Only row with lists should expand

        # List selector
        ttk.Label(main_frame, text='Выберите список для редактирования:').grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 5))
        
        self.list_key_var = tk.StringVar()
        self.list_key_combo = ttk.Combobox(main_frame, textvariable=self.list_key_var, state='readonly')
        self.list_key_combo.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 10))
        self.list_key_combo.bind('<<ComboboxSelected>>', self._on_list_selected)

        # Left side: list items
        left_frame = ttk.Frame(main_frame)
        left_frame.grid(row=2, column=0, sticky='nsew', padx=(0, 10))
        left_frame.rowconfigure(0, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.ls_listbox = tk.Listbox(left_frame, height=10, selectmode='extended')
        self.ls_listbox.grid(row=0, column=0, sticky='nsew')

        # Scrollbar for listbox
        scrollbar = ttk.Scrollbar(left_frame, orient='vertical', command=self.ls_listbox.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.ls_listbox.config(yscrollcommand=scrollbar.set)

        # Entry + buttons
        entry_frame = ttk.Frame(left_frame)
        entry_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(5, 0))
        entry_frame.columnconfigure(0, weight=1)

        self.ls_entry = tk.StringVar()
        ttk.Entry(entry_frame, textvariable=self.ls_entry).pack(side='left', fill='x', expand=True, padx=(0, 5))
        ttk.Button(entry_frame, text='Добавить', command=self._add_list_item).pack(side='left', padx=(0, 5))
        ttk.Button(entry_frame, text='Удалить', command=self._remove_selected_list).pack(side='left')

        # Right side: description
        right_frame = ttk.Frame(main_frame)
        right_frame.grid(row=2, column=1, sticky='nsew')
        right_frame.rowconfigure(0, weight=1)

        ttk.Label(right_frame, text='Описание:').pack(anchor='w')
        self.list_description_label = ttk.Label(right_frame, text='', justify='left', anchor='nw', wraplength=200)
        self.list_description_label.pack(fill='both', expand=True, pady=(5, 0))

        # List descriptions
        self._list_descriptions = {
            'filename_blacklist': 'Список слов и фраз, которые не должны считаться названиями серий.\n'
                                 'Включает жанровые термины, технические слова и другие элементы,\n'
                                 'которые могут быть ошибочно приняты за названия серий.',
            'service_words': 'Служебные слова, которые игнорируются при анализе названий файлов\n'
                            'и поиске серий. Эти слова не учитываются при определении\n'
                            'потенциальных названий серий.',
            'sequence_patterns': 'Шаблоны поиска (регулярные выражения) для распознавания номеров серий.\n'
                                'Используются для удаления нумерации перед анализом названий файлов.\n\n'
                                'Служебные символы:\n'
                                '  \\d  - любая цифра (0-9)\n'
                                '  \\s  - пробел\n'
                                '  +   - одна или больше\n'
                                '  *   - ноль или больше\n\n'
                                'Примеры:\n'
                                '  \\d+\\. (точка)  - "1. ", "12. "\n'
                                '  \\d+том        - "1том", "12том"\n'
                                '  книга\\s\\d+    - "книга 1", "книга 5"',
            'female_names': 'Список женских имён для идентификации авторов-женщин.\n'
                           'Используется при фильтрации книг женских авторов.',
            'male_names': 'Список мужских имён для идентификации авторов-мужчин.\n'
                         'Используется при фильтрации книг мужских авторов.',
            'abbreviations_preserve_case': 'Список аббревиатур, для которых нужно сохранять исходный кейс.\n'
                                           'Например: СССР, РФ, США, НАТО\n\n'
                                           'По умолчанию все слова приводятся к Title Case,\n'
                                           'но эти аббревиатуры остаются в исходном виде.',
            'author_initials_and_suffixes': 'Суффиксы и инициалы авторов, которые следует игнорировать\n'
                                           'при сравнении авторов.\n\n'
                                           'Примеры:\n'
                                           '  мл (младший)\n'
                                           '  ст (старший)\n'
                                           '  ср (средний)',
            'genre_category_words': 'Слова-категории серий для распознавания типов серий.\n'
                                    'Используются при анализе названий для определения жанра\n'
                                    'и типа серии.\n\n'
                                    'Примеры:\n'
                                    '  фантастический\n'
                                    '  боевик\n'
                                    '  детектив'
        }

        # Populate combobox with list keys
        keys = self.settings_manager.list_list_keys()
        # Ensure all editable lists are present in the combobox
        required_keys = [
            'filename_blacklist',
            'service_words',
            'sequence_patterns',
            'abbreviations_preserve_case',
            'author_initials_and_suffixes',
            'genre_category_words',
            'male_names',
            'female_names'
        ]
        for key in required_keys:
            if key not in keys:
                keys.append(key)
        self.list_key_combo['values'] = keys
        if keys:
            self.list_key_var.set(keys[0])
            self._load_list_items()

    def _choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.path_var.set(folder)

    def _on_list_selected(self, event=None):
        """Load the selected list items."""
        self._load_list_items()

    def _load_list_items(self):
        """Load items from current list into listbox."""
        self.ls_listbox.delete(0, tk.END)
        key = self.list_key_var.get()
        if not key:
            return
        items = self.settings_manager.get_list(key) or []
        for it in items:
            self.ls_listbox.insert(tk.END, it)
        
        # Update description
        description = self._list_descriptions.get(key, '')
        self.list_description_label.config(text=description)

    def _add_list_item(self):
        """Add new item to current list."""
        tok = (self.ls_entry.get() or '').strip()
        if not tok:
            return
        existing = [self.ls_listbox.get(i) for i in range(self.ls_listbox.size())]
        if tok.lower() in (e.lower() for e in existing):
            messagebox.showinfo('Дубликат', f'Элемент "{tok}" уже существует в списке')
            self.ls_entry.set('')
            return
        self.ls_listbox.insert(tk.END, tok)
        self.ls_entry.set('')
        # Save immediately
        self._save_current_list()

    def _remove_selected_list(self):
        """Remove selected items from list."""
        sel = list(self.ls_listbox.curselection())
        if not sel:
            return
        for i in reversed(sel):
            self.ls_listbox.delete(i)
        # Save immediately
        self._save_current_list()

    def _validate_folder_limit(self, event=None):
        """Validate folder limit input - must be a positive integer."""
        value = self.folder_limit_var.get()
        try:
            int_value = int(value)
            if int_value <= 0:
                raise ValueError("Must be positive")
            # Valid - do nothing, value will be saved
        except (ValueError, TypeError):
            # Invalid - restore previous value
            self.folder_limit_var.set(str(self.settings_manager.get_folder_parse_limit()))

    def _save(self):
        """Save all settings and close."""
        # General
        self.settings_manager.set_library_path(self.path_var.get())
        self.settings_manager.set_folder_parse_limit(self.folder_limit_var.get())
        self.settings_manager.set_generate_csv(self.generate_csv_var.get())
            
        # Lists panel: persist current list
        key = self.list_key_var.get()
        if key:
            ls_items = [self.ls_listbox.get(i) for i in range(self.ls_listbox.size())]
            self.settings_manager.set_list(key, ls_items)
        
        self.destroy()

    def _on_window_closing(self):
        """Callback when window is being closed by manager."""
        try:
            self.settings_manager.set_window_geometry('settings', self.geometry())
        except tk.TclError:
            pass

    def destroy(self):
        # Save window geometry
        try:
            self.settings_manager.set_window_geometry('settings', self.geometry())
        except tk.TclError:
            pass
        try:
            super().destroy()
        except tk.TclError:
            pass
