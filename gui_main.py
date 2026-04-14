#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Главное окно приложения EBook Library Organizer.

Содержит только GUI логику и управление окном.
Все сложные операции вынесены в отдельные модули.

Russian / Русский язык.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import sys
import os
from pathlib import Path
from typing import Dict

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Genre assignment
try:
    import genre_assign
    import importlib
    importlib.reload(genre_assign)
    from genre_assign import assign_genre_threaded
except Exception:
    from .genre_assign import assign_genre_threaded

# Window persistence
from window_persistence import save_window_geometry, restore_window_geometry
from window_manager import get_window_manager

# Тема
try:
    from gui_theme import apply_theme, SmartStatusBar, stripe_treeview
except ImportError:
    apply_theme = None
    SmartStatusBar = None
    stripe_treeview = None

# Core imports
try:
    import genres_manager
    import importlib
    importlib.reload(genres_manager)
    from genres_manager import GenresManager
    
    import settings_manager
    importlib.reload(settings_manager)
    from settings_manager import SettingsManager
    
    import logger
    importlib.reload(logger)
    from logger import Logger
    
    import gui_genres
    importlib.reload(gui_genres)
    from gui_genres import GenresManagerWindow
    
    import gui_normalizer
    importlib.reload(gui_normalizer)
    from gui_normalizer import CSVNormalizerApp
    
    import synchronization
    importlib.reload(synchronization)
    from synchronization import SynchronizationService
    
except Exception as e:
    from .genres_manager import GenresManager
    from .settings_manager import SettingsManager
    from .logger import Logger
    from .gui_genres import GenresManagerWindow
    from .gui_normalizer import CSVNormalizerApp
    from .synchronization import SynchronizationService


class MainWindow(tk.Tk):
    """Главное окно приложения."""
    
    def __init__(self):
        super().__init__()
        self.title('EBook Library Organizer')
        self.minsize(800, 500)

        # Применить тему до создания виджетов
        if apply_theme:
            apply_theme(self)

        # Инициализация менеджера окон
        window_manager = get_window_manager()
        window_manager.register_main_window(self)
        
        # Инициализация модулей
        self.logger = Logger()
        self.settings = SettingsManager('config.json')
        # Авто-детекция путей к config.json и genres.xml при первом запуске
        self.settings.auto_init_file_paths()
        
        # Восстановление позиции/размера окна
        restore_window_geometry(self, 'main', self.settings, 
                              default_geometry='1000x700+100+50')

        # Загружаем файл жанров из конфига (если он там сохранен)
        genres_file = self.settings.get_genres_file_path()
        # Если в конфиге указан несуществующий файл, пробуем локальный genres.xml из каталога приложения
        if not Path(genres_file).exists():
            local_genres = Path(__file__).resolve().parent / 'genres.xml'
            if local_genres.exists():
                genres_file = str(local_genres)
                self.settings.set_genres_file_path(genres_file)

        self.genres_manager = GenresManager(genres_file)
        self.genres_manager.load()  # Принудительно загрузка, чтобы окно жанров всегда показывало актуальный файл
        
        # Переменные состояния
        self.selected_folder = tk.StringVar()
        self.progress_var = tk.StringVar(value='Готово')
        self.view_mode = 'tree'  # 'tree' или 'listboxes'
        self._scan_results: Dict[str, list] = {}  # {genre_combo: [file_paths]}

        # Обработчик закрытия окна
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Очистка БД от orphaned записей при старте приложения (в фоновом потоке)
        self.after(200, self._cleanup_database_on_startup)

        # Создание UI
        self._create_menu()
        self._create_main_ui()
        
        # Установка начального значения папки
        default_folder = self.settings.get_last_scan_path() or self.settings.get_library_path() or os.path.expanduser('~')
        self.selected_folder.set(default_folder)
        self.selected_folder.trace('w', self._on_folder_changed)
        
        # Загружаем структуру папок после создания UI
        self.after(100, self._populate_folder_tree)
        
        # Восстановление геометрии окна ПОСЛЕ отображения (более надежный способ)
        self.after(50, lambda: restore_window_geometry(self, 'main', self.settings, 
                                                       default_geometry='1000x700+100+50'))

    def _cleanup_database_on_startup(self):
        """Очистить БД от записей о несуществующих файлах при старте приложения."""
        try:
            from synchronization import SynchronizationService
            
            # Показать статус очистки БД
            self.progress_var.set("Проверка БД на orphaned записи...")
            self.update()  # Force UI update
            
            def cleanup_progress_callback(current, total, status):
                """Callback для отображения прогресса очистки БД."""
                self.progress_var.set(f"{status} ({current}/{total})")
                self.update()
            
            sync_service = SynchronizationService('config.json')
            stats = sync_service.sync_database_with_library(
                log_callback=self.logger.log,
                progress_callback=cleanup_progress_callback
            )
            
            # Отобразить результаты
            if stats['deleted'] > 0:
                msg = f"При старте удалено {stats['deleted']} orphaned записей из БД"
                self.progress_var.set(msg)
                self.logger.log(f"[STARTUP] {msg}")
            elif stats['checked'] > 0:
                msg = f"БД проверена: {stats['checked']} записей, все файлы актуальны"
                self.progress_var.set(msg)
                self.logger.log(f"[STARTUP] {msg}")
            else:
                self.progress_var.set("БД пуста или отсутствует")
                self.logger.log("[STARTUP] БД пуста или отсутствует")
            
            self.update()
            
        except Exception as e:
            self.logger.log(f"[STARTUP] Ошибка при очистке БД: {str(e)}")
            import traceback
            self.logger.log(f"[STARTUP] Stacktrace: {traceback.format_exc()}")
            self.progress_var.set("Ошибка при проверке БД")
            self.update()

    def _create_menu(self):
        """Создание главного меню."""
        menubar = tk.Menu(self)
        
        # Файл
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label='Новая сессия', command=self._new_session)
        file_menu.add_command(label='Открыть результаты', command=self._open_scan)
        file_menu.add_command(label='Сохранить результаты', command=self._save_scan)
        file_menu.add_separator()
        file_menu.add_command(label='Загрузка жанров', command=self._import_genres)
        file_menu.add_separator()
        file_menu.add_command(label='Настройки', command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label='Выход', command=self.quit)
        menubar.add_cascade(label='Файл', menu=file_menu)
        
        # Действия
        self.action_menu = tk.Menu(menubar, tearoff=0)
        self.action_menu.add_command(label='Сканирование', command=self._on_scan_action)
        self.action_menu.add_command(label='Нормализация', command=self._on_normalization_action)
        self.action_menu.add_command(label='Синхронизация', command=self._on_synchronization_action)
        self.action_menu.add_command(label='Заархивировать', command=self._on_archive_action)
        self.action_menu.add_separator()
        self.action_menu.add_command(label='База данных', command=self._open_database_viewer)
        menubar.add_cascade(label='Действия', menu=self.action_menu)
        
        # Жанры
        genres_menu = tk.Menu(menubar, tearoff=0)
        genres_menu.add_command(label='Менеджер жанров', command=self._open_genres_manager)
        menubar.add_cascade(label='Жанры', menu=genres_menu)
        
        # Лог
        log_menu = tk.Menu(menubar, tearoff=0)
        log_menu.add_command(label='Показать лог', command=self._show_log_window)
        menubar.add_cascade(label='Лог', menu=log_menu)

        # Библиотека
        lib_menu = tk.Menu(menubar, tearoff=0)
        lib_menu.add_command(label='Статистика',         command=self._open_dashboard)
        lib_menu.add_command(label='Поиск по метаданным', command=self._open_search)
        lib_menu.add_separator()
        lib_menu.add_command(label='Новые книги',         command=self._open_new_books)
        lib_menu.add_command(label='Серии с пробелами',   command=self._open_series_gaps)
        lib_menu.add_separator()
        lib_menu.add_command(label='Проверка целостности FB2', command=self._open_integrity_check)
        lib_menu.add_command(label='Генератор OPDS-каталога',  command=self._open_opds_generator)
        menubar.add_cascade(label='Библиотека', menu=lib_menu)

        # Помощь
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label='Содержание', command=self._open_help)
        menubar.add_cascade(label='Помощь', menu=help_menu)

        self.config(menu=menubar)

    def _create_main_ui(self):
        """Создание основного интерфейса."""
        # Верхняя панель выбора папки
        top_frame = ttk.Frame(self)
        top_frame.pack(fill='x', padx=5, pady=5)
        ttk.Label(top_frame, text='Папка для обработки:').pack(side='left', padx=2)
        self.folder_entry = ttk.Entry(top_frame, textvariable=self.selected_folder, width=60)
        self.folder_entry.pack(side='left', padx=2, fill='x', expand=True)
        ttk.Button(top_frame, text='Обзор', command=self._choose_folder).pack(side='left', padx=2)
        ttk.Button(top_frame, text='Переключить вид', command=self._toggle_view_mode).pack(side='left', padx=2)

        # Статусная строка
        if SmartStatusBar:
            self._status_bar = SmartStatusBar(self)
            self._status_bar.pack(fill='x', side='bottom')
            # Перепривязываем progress_var к переменной умного статус-бара
            self.progress_var = self._status_bar.variable
        else:
            self.status = ttk.Label(self, textvariable=self.progress_var, anchor='w')
            self.status.pack(fill='x', side='bottom', padx=5, pady=2)
            self._status_bar = None

        # Основные панели
        self.main_pane = ttk.PanedWindow(self, orient='horizontal')
        self.main_pane.pack(fill='both', expand=True, padx=5, pady=5)

        # Панель жанров
        self.genres_frame = ttk.LabelFrame(self.main_pane, text='Жанры', padding=5)
        self.genres_list = tk.Listbox(
            self.genres_frame, height=15,
            font=("Segoe UI", 10), relief="flat",
            background="#FFFFFF", foreground="#1A1A1A",
            selectbackground="#CCE4F7", selectforeground="#003D7A",
            borderwidth=0, highlightthickness=1, highlightcolor="#C8C8C8",
            activestyle="none",
        )
        self.genres_list.pack(fill='both', expand=True, side='left')
        self.genres_list.bind('<Double-Button-1>', self._on_genre_double_click)
        self.genres_list.bind('<<ListboxSelect>>', self._on_genre_selected)
        genres_scroll = ttk.Scrollbar(self.genres_frame, command=self.genres_list.yview)
        self.genres_list.config(yscrollcommand=genres_scroll.set)
        genres_scroll.pack(side='right', fill='y')

        # Панель ошибок
        self.errors_frame = ttk.LabelFrame(self.main_pane, text='Ошибки/Замечания', padding=5)
        self.errors_list = tk.Listbox(
            self.errors_frame, height=15,
            font=("Segoe UI", 10), relief="flat",
            background="#FFFFFF", foreground="#1A1A1A",
            selectbackground="#CCE4F7", selectforeground="#003D7A",
            borderwidth=0, highlightthickness=1, highlightcolor="#C8C8C8",
            activestyle="none",
        )
        self.errors_list.pack(fill='both', expand=True, side='left')
        errors_scroll = ttk.Scrollbar(self.errors_frame, command=self.errors_list.yview)
        self.errors_list.config(yscrollcommand=errors_scroll.set)
        errors_scroll.pack(side='right', fill='y')

        # Панель деталей
        self.details_frame = ttk.LabelFrame(self.main_pane, text='Детали', padding=5)
        self.details_list = tk.Listbox(
            self.details_frame, height=15,
            font=("Segoe UI", 10), relief="flat",
            background="#FFFFFF", foreground="#1A1A1A",
            selectbackground="#CCE4F7", selectforeground="#003D7A",
            borderwidth=0, highlightthickness=1, highlightcolor="#C8C8C8",
            activestyle="none",
        )
        self.details_list.pack(fill='both', expand=True, side='left')
        self.details_list.bind('<Double-Button-1>', self._on_detail_double_click)
        details_scroll = ttk.Scrollbar(self.details_frame, command=self.details_list.yview)
        self.details_list.config(yscrollcommand=details_scroll.set)
        details_scroll.pack(side='right', fill='y')
        
        # Панель с деревом папок
        self.folder_tree_frame = ttk.LabelFrame(self.main_pane, text='Структура папок', padding=5)
        self.folder_tree = ttk.Treeview(self.folder_tree_frame)
        if stripe_treeview:
            stripe_treeview(self.folder_tree)
        self.folder_tree.pack(fill='both', expand=True, side='left')
        folder_tree_scroll = ttk.Scrollbar(self.folder_tree_frame, command=self.folder_tree.yview)
        self.folder_tree.config(yscrollcommand=folder_tree_scroll.set)
        folder_tree_scroll.pack(side='right', fill='y')
        self.folder_tree.bind('<Double-Button-1>', self._on_folder_tree_double_click)
        self.folder_tree.bind('<Button-3>', self._on_folder_tree_right_click)  # ПКМ
        
        # Контекстное меню для папок
        self.folder_tree_context_menu = tk.Menu(self.folder_tree, tearoff=0)
        self.folder_tree_context_menu.add_command(
            label='Присвоить жанр',
            command=self._assign_genre_to_folder
        )
        
        # Добавляем панели в main_pane в зависимости от режима
        if self.view_mode == 'tree':
            self.main_pane.add(self.folder_tree_frame, weight=1)
        else:
            self.main_pane.add(self.genres_frame, weight=2)
            self.main_pane.add(self.errors_frame, weight=1)
            self.main_pane.add(self.details_frame, weight=3)

    def _toggle_view_mode(self):
        """Переключение между режимами отображения."""
        if self.view_mode == 'listboxes':
            self.view_mode = 'tree'
            self.main_pane.forget(self.genres_frame)
            self.main_pane.forget(self.errors_frame)
            self.main_pane.forget(self.details_frame)
            self.main_pane.add(self.folder_tree_frame, weight=1)
            self._populate_folder_tree()
        else:
            self.view_mode = 'listboxes'
            self.main_pane.forget(self.folder_tree_frame)
            self.main_pane.add(self.genres_frame, weight=2)
            self.main_pane.add(self.errors_frame, weight=1)
            self.main_pane.add(self.details_frame, weight=3)
        
        self.logger.log(f'Переключение режима на: {self.view_mode}')

    def _populate_folder_tree(self):
        """Заполнить дерево иерархией папок."""
        if not hasattr(self, 'folder_tree'):
            return
        
        # Очистить дерево
        for item in self.folder_tree.get_children():
            self.folder_tree.delete(item)
        
        folder = self.selected_folder.get()
        if not folder or not os.path.isdir(folder):
            return
        
        # Добавить корневой элемент
        root_item = self.folder_tree.insert('', 'end', text=os.path.basename(folder), open=True)
        self.folder_tree.item(root_item, tags=(folder,))
        
        # Рекурсивно добавить подпапки
        self._add_tree_items(root_item, folder, levels_to_expand=0, current_level=0)
    
    def _add_tree_items(self, parent_item, folder_path, levels_to_expand=1, current_level=0, max_depth=20):
        """Рекурсивно добавить папки в дерево."""
        if current_level >= max_depth:
            return
        
        try:
            items = sorted(os.listdir(folder_path))
            for item in items:
                item_path = os.path.join(folder_path, item)
                if os.path.isdir(item_path) and not item.startswith('.'):
                    should_open = current_level < levels_to_expand
                    tree_item = self.folder_tree.insert(parent_item, 'end', text=item, open=should_open)
                    self.folder_tree.item(tree_item, tags=(item_path,))
                    self._add_tree_items(tree_item, item_path, levels_to_expand, current_level + 1, max_depth)
        except PermissionError:
            pass

    def _on_folder_tree_double_click(self, event=None):
        """Обработчик двойного клика по дереву папок."""
        if event is None:
            return
        item = self.folder_tree.selection()
        if not item:
            return
        tags = self.folder_tree.item(item[0], 'tags')
        if tags:
            folder_path = tags[0]
            try:
                import subprocess
                subprocess.Popen(['explorer', folder_path])
            except Exception as e:
                self.logger.log(f'Ошибка при открытии папки: {e}')

    def _choose_folder(self):
        """Выбрать папку для обработки."""
        folder = filedialog.askdirectory()
        if folder:
            self.selected_folder.set(folder)
            self.settings.set_last_scan_path(folder)
            self.logger.log(f'Выбрана папка: {folder}')

    def _on_folder_changed(self, *args):
        """Обработчик изменения выбранной папки (дебаунс: 400 мс)."""
        # Отменить предыдущий отложенный вызов, если есть
        if hasattr(self, '_folder_change_after_id') and self._folder_change_after_id:
            self.after_cancel(self._folder_change_after_id)
        self._folder_change_after_id = self.after(400, self._populate_folder_tree_debounced)

    def _populate_folder_tree_debounced(self):
        """Вызывается через 400 мс после последнего изменения пути."""
        self._folder_change_after_id = None
        folder = self.selected_folder.get()
        if folder and self.view_mode == 'tree' and hasattr(self, 'folder_tree'):
            self._populate_folder_tree()

    def _on_genre_selected(self, event=None):
        """Обработчик выбора жанра — заполняет список деталей файлами."""
        sel = self.genres_list.curselection()
        if not sel:
            return
        genre_combo = self.genres_list.get(sel[0])
        files = self._scan_results.get(genre_combo, [])
        self.details_list.delete(0, 'end')
        for fp in sorted(files):
            self.details_list.insert('end', fp)

    def _on_genre_double_click(self, event=None):
        """Обработчик двойного клика по жанру."""
        pass

    def _on_detail_double_click(self, event=None):
        """Обработчик двойного клика по деталям."""
        pass

    def _show_log_window(self):
        """Показать окно логов."""
        from window_persistence import setup_window_persistence
        
        win = tk.Toplevel(self)
        win.title('Лог')
        win.withdraw()  # Скрыть окно изначально
        
        # Настройка сохранения размера и позиции окна
        setup_window_persistence(win, 'log', self.settings, '700x400+100+100')
        
        # Показать окно
        win.deiconify()
            
        frame = ttk.Frame(win)
        frame.pack(fill='both', expand=True, padx=10, pady=10)
        log_list = tk.Listbox(frame, selectmode='extended')
        log_list.pack(fill='both', expand=True, side='left')
        scroll = ttk.Scrollbar(frame, command=log_list.yview)
        log_list.config(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        
        for entry in self.logger.get_entries():
            log_list.insert(tk.END, entry)
        
        btns = ttk.Frame(win)
        btns.pack(fill='x', pady=5)
        ttk.Button(btns, text='Очистить', command=lambda: self._clear_log_and_update(log_list)).pack(side='left', padx=10)
        ttk.Button(btns, text='Копировать выделенное', command=lambda: self._copy_selected_logs(log_list)).pack(side='left', padx=10)
        ttk.Button(btns, text='Закрыть', command=win.destroy).pack(side='left')

    def _clear_log_and_update(self, log_list):
        """Очистить лог."""
        self.logger.clear()
        log_list.delete(0, tk.END)
        self.logger.log('Лог очищен')

    def _copy_selected_logs(self, log_list):
        """Скопировать выделенные строки логов в буфер обмена."""
        try:
            selection = log_list.curselection()
            if selection:
                items = [log_list.get(idx) for idx in selection]
                text = '\n'.join(items)
                self.clipboard_clear()
                self.clipboard_append(text)
                self.update()
                self.logger.log(f'Скопировано {len(items)} строк в буфер обмена')
        except Exception as e:
            self.logger.log(f'Ошибка при копировании: {str(e)}')

    def _open_genres_manager(self):
        """Открыть менеджер жанров."""
        from window_persistence import setup_window_persistence, save_window_geometry
        
        # Принудительно обновляем из файла genres.xml перед открытием окна
        self.genres_manager.load()
        # Create genres manager window directly (avoid extra empty Toplevel)
        genres_window = GenresManagerWindow(self, self.genres_manager, self.logger, self.settings, lambda: None)
        
        # Setup persistence AFTER window is created
        setup_window_persistence(genres_window, 'genres_manager', self.settings, '700x500+200+150')
        
        # Register close callback
        window_manager = get_window_manager()
        
        def on_genres_close():
            save_window_geometry(genres_window, 'genres_manager', self.settings)
        
        window_manager.open_child_window(self, genres_window, on_genres_close)

    def _open_settings(self):
        """Открыть окно настроек."""
        try:
            import gui_settings
            import importlib
            importlib.reload(gui_settings)
            from gui_settings import SettingsWindow
        except Exception:
            from .gui_settings import SettingsWindow
        
        SettingsWindow(self, self.settings)

    def _new_session(self):
        """Новая сессия."""
        self.genres_list.delete(0, tk.END)
        self.errors_list.delete(0, tk.END)
        self.details_list.delete(0, tk.END)
        self.logger.log('Новая сессия')

    def _open_scan(self):
        """Открыть результаты сканирования."""
        file = filedialog.askopenfilename(
            filetypes=[('Результаты сканирования', '*.scan'), ('Все файлы', '*.*')]
        )
        if file:
            self.logger.log(f'Открыт файл: {file}')

    def _save_scan(self):
        """Сохранить результаты сканирования."""
        file = filedialog.asksaveasfilename(
            defaultextension='.scan',
            filetypes=[('Результаты сканирования', '*.scan')]
        )
        if file:
            self.logger.log(f'Сохранено в: {file}')

    def _import_genres(self):
        """Загрузить жанры из XML файла."""
        file = filedialog.askopenfilename(
            filetypes=[('XML файлы жанров', '*.xml'), ('Все файлы', '*.*')]
        )
        if file:
            try:
                # Получаем абсолютный путь к выбранному файлу
                import os
                abs_file = os.path.abspath(file)
                
                # Устанавливаем путь в genres_manager (не копируем файл)
                self.genres_manager.set_xml_path(abs_file)
                
                # Сохраняем путь в конфиг для последующих запусков
                self.settings.set_genres_file_path(abs_file)
                
                self.logger.log(f'Жанры загружены из файла: {abs_file}')
                messagebox.showinfo('Успех', 'Жанры успешно загружены')
            except Exception as e:
                self.logger.log(f'Ошибка при загрузке жанров: {e}')
                messagebox.showerror('Ошибка', f'Не удалось загрузить жанры:\n{e}')

    def _on_scan_action(self):
        """Обработчик действия 'Сканирование'. Извлекает жанры из FB2-файлов."""
        folder = self.selected_folder.get()
        if not folder:
            messagebox.showwarning('Внимание', 'Не выбрана папка для обработки')
            return
        if not os.path.isdir(folder):
            messagebox.showwarning('Внимание', f'Папка не найдена:\n{folder}')
            return

        fb2_count = sum(1 for _ in Path(folder).rglob('*.fb2'))
        if fb2_count == 0:
            messagebox.showwarning('Папка пуста', f'В папке нет FB2-файлов:\n{folder}')
            return
        if self._status_bar:
            self._status_bar.set('Сканирование...', 'busy')
        self.logger.log(f'Начато сканирование: {folder}')

        def _scan_worker():
            try:
                try:
                    from fb2_author_extractor import FB2AuthorExtractor
                except ImportError:
                    from .fb2_author_extractor import FB2AuthorExtractor

                extractor = FB2AuthorExtractor(self.settings.config_path)
                results: Dict[str, list] = {}
                errors: list = []
                folder_path = Path(folder)
                fb2_files = sorted(folder_path.rglob('*.fb2'))
                total = len(fb2_files)

                for idx, fb2_file in enumerate(fb2_files, 1):
                    try:
                        genre_str = extractor._extract_genres_from_fb2(fb2_file)
                        if genre_str and genre_str.strip():
                            key = genre_str.strip()
                        else:
                            key = 'Не определено'
                        try:
                            rel_path = str(fb2_file.relative_to(folder_path))
                        except ValueError:
                            rel_path = str(fb2_file)
                        results.setdefault(key, []).append(rel_path)
                    except Exception as e:
                        errors.append(f'{fb2_file.name}: {e}')

                    if idx % 20 == 0 or idx == total:
                        pct = int(idx * 100 / total) if total else 100
                        self.after(0, lambda p=pct, n=idx, t=total:
                            self.progress_var.set(f'Сканирование... {n}/{t} ({p}%)'))

                self.after(0, lambda: _update_ui(results, errors, total))
            except Exception as e:
                import traceback
                err_text = traceback.format_exc()
                self.after(0, lambda err=e, tb=err_text: (
                    self.logger.log(f'Ошибка сканирования: {tb}'),
                    self.progress_var.set(f'Ошибка сканирования: {err}'),
                    self._status_bar.set(f'Ошибка сканирования', 'error') if self._status_bar else None,
                    messagebox.showerror('Ошибка сканирования', str(err))
                ))

        def _update_ui(results: Dict[str, list], errors: list, total: int):
            self._scan_results = results

            self.genres_list.delete(0, 'end')
            for combo in sorted(results.keys()):
                self.genres_list.insert('end', combo)

            self.errors_list.delete(0, 'end')
            for err in errors:
                self.errors_list.insert('end', err)

            self.details_list.delete(0, 'end')

            if self.view_mode != 'listboxes':
                self._toggle_view_mode()

            genre_count = len(results)
            status_msg = (
                f'Сканирование завершено: {total} файлов, '
                f'{genre_count} уникальных наборов жанров'
            )
            self.progress_var.set(status_msg)
            if self._status_bar:
                self._status_bar.set(status_msg, 'ok')
            self.logger.log(status_msg)
            if errors:
                self.logger.log(f'Ошибок при сканировании: {len(errors)}')

        threading.Thread(target=_scan_worker, daemon=True).start()

    def _on_archive_action(self):
        """Архивировать все FB2-файлы в папке библиотеки в формат fb2.zip."""
        library_path = self.settings.get_library_path()
        if not library_path or not os.path.isdir(library_path):
            messagebox.showwarning(
                'Внимание',
                'Папка библиотеки не задана или не найдена.\n'
                'Укажите её в Файл → Настройки.'
            )
            return

        # Подсчитать файлы для подтверждения
        fb2_files = list(Path(library_path).rglob('*.fb2'))
        if not fb2_files:
            messagebox.showinfo('Информация', 'FB2-файлы в папке библиотеки не найдены.')
            return

        if not messagebox.askyesno(
            'Заархивировать',
            f'Найдено {len(fb2_files)} FB2-файл(ов) в папке библиотеки:\n{library_path}\n\n'
            'Каждый файл будет упакован в ZIP-архив (file.fb2 → file.fb2.zip),\n'
            'оригинал будет удалён.\n\nПродолжить?'
        ):
            return

        self.progress_var.set('Архивирование...')
        if self._status_bar:
            self._status_bar.set('Архивирование...', 'busy')
        self.logger.log(f'Начато архивирование: {library_path} ({len(fb2_files)} файлов)')

        def _archive_worker():
            import zipfile as _zipfile
            done = 0
            errors = []
            total = len(fb2_files)
            size_before = 0
            size_after = 0
            for idx, fb2_path in enumerate(fb2_files, 1):
                try:
                    fb2_size = fb2_path.stat().st_size
                    zip_path = fb2_path.with_name(fb2_path.name + '.zip')
                    # Имя внутри архива — только имя файла (без пути)
                    with _zipfile.ZipFile(
                        zip_path, 'w',
                        compression=_zipfile.ZIP_DEFLATED,
                        compresslevel=6
                    ) as zf:
                        zf.write(fb2_path, arcname=fb2_path.name)
                    zip_size = zip_path.stat().st_size
                    fb2_path.unlink()
                    done += 1
                    size_before += fb2_size
                    size_after += zip_size
                except Exception as e:
                    errors.append(f'{fb2_path.name}: {e}')

                if idx % 50 == 0 or idx == total:
                    pct = int(idx * 100 / total)
                    self.after(0, lambda n=idx, t=total, p=pct:
                        self.progress_var.set(f'Архивирование... {n}/{t} ({p}%)'))

            self.after(0, lambda: _finish(done, errors, total, size_before, size_after))

        def _finish(done, errors, total, size_before, size_after):
            def _fmt(b):
                if b >= 1_073_741_824:
                    return f'{b / 1_073_741_824:.2f} ГБ'
                if b >= 1_048_576:
                    return f'{b / 1_048_576:.1f} МБ'
                return f'{b // 1024} КБ'

            saved = size_before - size_after
            ratio = (saved / size_before * 100) if size_before else 0
            stats = (
                f'Обработано файлов: {done} из {total}\n'
                f'До архивации:   {_fmt(size_before)}\n'
                f'После архивации: {_fmt(size_after)}\n'
                f'Сжато:           {_fmt(saved)} ({ratio:.1f}%)'
            )

            msg = f'Архивирование завершено: {done}/{total} файлов'
            self.progress_var.set(msg)
            if self._status_bar:
                self._status_bar.set(msg, 'ok')
            self.logger.log(msg)
            self.logger.log(stats)
            if errors:
                self.logger.log(f'Ошибок: {len(errors)}')
                for e in errors[:10]:
                    self.logger.log(f'  {e}')
                messagebox.showwarning(
                    'Завершено с ошибками',
                    f'{stats}\n\nОшибок: {len(errors)}\n\nПервые ошибки:\n' +
                    '\n'.join(errors[:5])
                )
            else:
                messagebox.showinfo('Архивирование завершено', stats)

        threading.Thread(target=_archive_worker, daemon=True).start()

    def _on_normalization_action(self):
        """Обработчик действия 'Нормализация'. Открывает окно нормализации."""
        try:
            import gui_normalizer
            import importlib
            importlib.reload(gui_normalizer)
            from gui_normalizer import CSVNormalizerApp
        except Exception:
            from .gui_normalizer import CSVNormalizerApp
        
        from window_persistence import setup_window_persistence, save_window_geometry
        
        # Получаем текущий путь из главного окна
        current_folder = self.selected_folder.get()
        
        # Создаем новое окно для нормализации
        # Полноценное окно (не диалог) — все кнопки хрома: свернуть/развернуть/закрыть
        normalizer_root = tk.Toplevel(self)
        normalizer_root.resizable(True, True)
        
        # Инициализируем app (геометрия будет восстановлена автоматически)
        app = CSVNormalizerApp(normalizer_root, current_folder, self.logger, self.settings)
        
        # Настройка сохранения размера и позиции окна
        setup_window_persistence(normalizer_root, 'normalizer', self.settings, '1400x700+150+100')
        
        self.logger.log('Окно нормализации открыто')
        window_manager = get_window_manager()
        
        # Передаем callback для сохранения позиции при закрытии
        def on_normalizer_close():
            save_window_geometry(normalizer_root, 'normalizer', self.settings)
        
        window_manager.open_child_window(self, normalizer_root, on_normalizer_close)

    def _on_synchronization_action(self):
        """Обработчик действия 'Синхронизация'."""
        # Check if synchronization is already running
        if hasattr(self, '_sync_running') and self._sync_running:
            messagebox.showwarning("Внимание", "Синхронизация уже выполняется")
            return
        
        # Confirm before starting
        if not messagebox.askyesno(
            "Подтверждение",
            "Начать синхронизацию библиотеки?\n\n"
            "Файлы будут перемещены из исходной папки в структурированную библиотеку."
        ):
            return
        
        self._sync_running = True
        self.logger.log('Синхронизация запущена')
        
        # Launch synchronization in background thread
        thread = threading.Thread(
            target=self._synchronize_thread,
            daemon=True
        )
        thread.start()
    
    def _synchronize_thread(self):
        """Execute synchronization in background thread."""
        original_stdout = sys.stdout
        
        try:
            # Create synchronization service
            sync_service = SynchronizationService('config.json')
            
            def progress_callback(current, total, status):
                """Update progress bar in UI."""
                self.after(0, lambda: self.progress_var.set(f"{status} ({current}/{total})"))
                if self._status_bar:
                    self.after(0, lambda: self._status_bar.set(f"{status} ({current}/{total})", 'busy'))
                self.logger.log(f"{status}: {current}/{total}")
            
            def log_callback(message: str):
                """Callback for logging from synchronization service."""
                self.logger.log(f"[SYNC] {message}")
            
            # Run synchronization
            if self._status_bar: self.after(0, lambda: self._status_bar.set("Инициализация синхронизации...", 'busy'))
            stats = sync_service.synchronize(
                progress_callback=progress_callback,
                log_callback=log_callback
            )
            
            # Update final status
            if self._status_bar: self.after(0, lambda: self._status_bar.set("Синхронизация завершена", 'ok'))
            
            # Show statistics popup
            self._show_synchronization_stats(stats)
            
            self.logger.log("Синхронизация успешно завершена")
            
        except Exception as e:
            self.logger.log(f"ОШИБКА при синхронизации: {str(e)}")
            self.after(
                0,
                lambda: messagebox.showerror(
                    "Ошибка",
                    f"Ошибка при синхронизации: {str(e)}"
                )
            )
            if self._status_bar: self.after(0, lambda: self._status_bar.set("ОШИБКА", 'error'))
        
        finally:
            sys.stdout = original_stdout
            self._sync_running = False
    
    def _show_synchronization_stats(self, stats: Dict):
        """Show statistics popup after synchronization.
        
        Args:
            stats: Dictionary with statistics from synchronization
        """
        # Calculate duration
        duration_str = stats.get('duration_str', 'неизвестно')
        
        message = (
            f"Синхронизация завершена\n\n"
            f"Перемещено файлов: {stats['files_moved']}\n"
            f"Найдено дубликатов: {stats['duplicates_found']}\n"
            f"Удалено пустых папок: {stats['folders_deleted']}\n"
            f"Ошибок: {stats['errors']}\n"
            f"Время: {duration_str}"
        )
        
        self.after(
            0,
            lambda: messagebox.showinfo("Статистика синхронизации", message)
        )

    def _open_database_viewer(self):
        """Открыть окно просмотра содержимого базы данных."""
        from window_persistence import restore_window_geometry, save_window_geometry
        import sqlite3
        
        db_window = tk.Toplevel(self)
        db_window.title('База данных - Просмотр')
        db_window.minsize(1000, 500)
        
        # Notebook для вкладок (books и series)
        notebook = ttk.Notebook(db_window)
        notebook.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Вкладка Books
        books_frame = ttk.Frame(notebook)
        notebook.add(books_frame, text='Книги (Books)')
        
        # Treeview для books
        books_tree = ttk.Treeview(books_frame, columns=[
            'id', 'file_path', 'author', 'series', 'title', 'genre'
        ], height=20)
        
        books_tree.heading('#0', text='')
        books_tree.column('#0', width=0)
        books_tree.heading('id', text='ID')
        books_tree.heading('file_path', text='Путь к файлу')
        books_tree.heading('author', text='Автор')
        books_tree.heading('series', text='Серия')
        books_tree.heading('title', text='Название')
        books_tree.heading('genre', text='Жанр')
        
        books_tree.column('id', width=40)
        books_tree.column('file_path', width=300)
        books_tree.column('author', width=150)
        books_tree.column('series', width=150)
        books_tree.column('title', width=200)
        books_tree.column('genre', width=100)
        
        # Scrollbar для books tree
        books_scrollbar_y = ttk.Scrollbar(books_frame, orient='vertical', command=books_tree.yview)
        books_scrollbar_x = ttk.Scrollbar(books_frame, orient='horizontal', command=books_tree.xview)
        books_tree.configure(yscroll=books_scrollbar_y.set, xscroll=books_scrollbar_x.set)
        
        books_tree.grid(row=0, column=0, sticky='nsew')
        books_scrollbar_y.grid(row=0, column=1, sticky='ns')
        books_scrollbar_x.grid(row=1, column=0, sticky='ew')
        
        books_frame.rowconfigure(0, weight=1)
        books_frame.columnconfigure(0, weight=1)
        
        # Вкладка Series
        series_frame = ttk.Frame(notebook)
        notebook.add(series_frame, text='Серии (Series)')
        
        # Treeview для series
        series_tree = ttk.Treeview(series_frame, columns=[
            'id', 'series_name', 'book_count', 'last_updated'
        ], height=20)
        
        series_tree.heading('#0', text='')
        series_tree.column('#0', width=0)
        series_tree.heading('id', text='ID')
        series_tree.heading('series_name', text='Название серии')
        series_tree.heading('book_count', text='Книг в серии')
        series_tree.heading('last_updated', text='Обновлено')
        
        series_tree.column('id', width=40)
        series_tree.column('series_name', width=300)
        series_tree.column('book_count', width=100)
        series_tree.column('last_updated', width=150)
        
        # Scrollbar для series tree
        series_scrollbar_y = ttk.Scrollbar(series_frame, orient='vertical', command=series_tree.yview)
        series_scrollbar_x = ttk.Scrollbar(series_frame, orient='horizontal', command=series_tree.xview)
        series_tree.configure(yscroll=series_scrollbar_y.set, xscroll=series_scrollbar_x.set)
        
        series_tree.grid(row=0, column=0, sticky='nsew')
        series_scrollbar_y.grid(row=0, column=1, sticky='ns')
        series_scrollbar_x.grid(row=1, column=0, sticky='ew')
        
        series_frame.rowconfigure(0, weight=1)
        series_frame.columnconfigure(0, weight=1)
        
        # Нижняя панель с кнопками
        button_frame = ttk.Frame(db_window)
        button_frame.pack(fill='x', padx=5, pady=5)
        
        ttk.Button(button_frame, text='Обновить', command=lambda: self._load_database_data(books_tree, series_tree)).pack(side='left', padx=5)
        ttk.Button(button_frame, text='Закрыть', command=db_window.destroy).pack(side='left', padx=5)
        
        # Загрузить данные
        self._load_database_data(books_tree, series_tree)
        
        # Сохранение geometrии окна
        restore_window_geometry(db_window, 'database_viewer', self.settings, default_geometry='1000x500+200+150')
        
        def on_close():
            save_window_geometry(db_window, 'database_viewer', self.settings)
            db_window.destroy()
        
        db_window.protocol('WM_DELETE_WINDOW', on_close)
    
    # ------------------------------------------------------------------
    # Библиотека menu handlers
    # ------------------------------------------------------------------

    def _open_dashboard(self):
        """Открыть окно статистики библиотеки."""
        try:
            from gui_dashboard import DashboardWindow
        except ImportError:
            from .gui_dashboard import DashboardWindow
        DashboardWindow(parent=self, settings_manager=self.settings)

    def _open_search(self):
        """Открыть окно поиска по метаданным."""
        try:
            from gui_search import SearchWindow
        except ImportError:
            from .gui_search import SearchWindow
        SearchWindow(parent=self, settings_manager=self.settings)

    def _open_new_books(self):
        """Открыть окно новых книг."""
        try:
            from gui_new_books import NewBooksWindow
        except ImportError:
            from .gui_new_books import NewBooksWindow
        NewBooksWindow(parent=self, settings_manager=self.settings)

    def _open_series_gaps(self):
        """Открыть окно серий с пробелами."""
        try:
            from gui_series_gaps import SeriesGapsWindow
        except ImportError:
            from .gui_series_gaps import SeriesGapsWindow
        SeriesGapsWindow(parent=self, settings_manager=self.settings)

    def _open_integrity_check(self):
        """Открыть окно глубокой проверки FB2."""
        try:
            from gui_integrity_check import IntegrityCheckWindow
        except ImportError:
            from .gui_integrity_check import IntegrityCheckWindow
        folder = self.selected_folder.get() or ''
        IntegrityCheckWindow(parent=self, settings_manager=self.settings,
                             initial_folder=folder)

    def _open_opds_generator(self):
        """Открыть окно генератора OPDS-каталога."""
        try:
            from opds_generator import OPDSGeneratorWindow
        except ImportError:
            from .opds_generator import OPDSGeneratorWindow
        OPDSGeneratorWindow(parent=self, settings_manager=self.settings)

    def _open_help(self):
        """Открыть окно справки."""
        try:
            from gui_help import HelpWindow
        except ImportError:
            from .gui_help import HelpWindow
        HelpWindow(parent=self, settings_manager=self.settings)

    # ------------------------------------------------------------------

    def _load_database_data(self, books_tree, series_tree):
        """Загрузить данные из базы и отобразить в таблицах."""
        import sqlite3
        
        try:
            db_path = '.library_cache.db'
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Очистить таблицы
            for item in books_tree.get_children():
                books_tree.delete(item)
            for item in series_tree.get_children():
                series_tree.delete(item)
            
            # Загрузить books
            cursor.execute('SELECT id, author, title, genre, series, file_path FROM books ORDER BY id DESC LIMIT 1000')
            for row in cursor.fetchall():
                books_tree.insert('', 0, values=(
                    row['id'],
                    row['file_path'][:100] if row['file_path'] else '',
                    row['author'][:50] if row['author'] else '',
                    row['series'][:40] if row['series'] else '',
                    row['title'][:50] if row['title'] else '',
                    row['genre'][:30] if row['genre'] else ''
                ))
            
            # Загрузить series
            cursor.execute('SELECT id, series_name, book_count, last_updated FROM series ORDER BY id DESC')
            for row in cursor.fetchall():
                series_tree.insert('', 0, values=(
                    row['id'],
                    row['series_name'][:60] if row['series_name'] else '',
                    row['book_count'] if row['book_count'] else 0,
                    row['last_updated'][:19] if row['last_updated'] else ''
                ))
            
            conn.close()
            self.logger.log(f"[DB] Загружены данные из базы")
            
        except Exception as e:
            self.logger.log(f"[DB] Ошибка при загрузке данных: {str(e)}")
            messagebox.showerror('Ошибка', f'Не удалось загрузить данные из базы:\n{str(e)}')

    def _on_folder_tree_right_click(self, event):
        """Обработчик ПКМ на Treeview элемент."""
        # Выбрать элемент в точке клика
        item = self.folder_tree.identify('item', event.x, event.y)
        if item:
            self.folder_tree.selection_set(item)
            self.selected_tree_item = item
            # Показать контекстное меню
            self.folder_tree_context_menu.post(event.x_root, event.y_root)
    
    def _assign_genre_to_folder(self):
        """Присвоить жанр выбранной папке/файлу."""
        if not hasattr(self, 'selected_tree_item'):
            messagebox.showwarning('Предупреждение', 'Ничего не выбрано')
            return
        
        item = self.selected_tree_item
        
        # Получить путь элемента
        try:
            path_text = self.folder_tree.item(item, 'text')
        except:
            messagebox.showerror('Ошибка', 'Не удалось получить информацию об элементе')
            return
        
        # Показать диалог выбора жанра
        self._open_genre_assignment_dialog(path_text, item)
    
    def _open_genre_assignment_dialog(self, path_text: str, tree_item: str):
        """Открыть диалог присвоения жанра."""
        # Получить список всех доступных жанров
        genres = self.genres_manager.get_all_genres()
        
        if not genres:
            messagebox.showwarning('Внимание', 'Список жанров пуст')
            return
        
        # Получить полный путь к папке из дерева
        try:
            tags = self.folder_tree.item(tree_item, 'tags')
            
            if not tags or len(tags) == 0:
                messagebox.showerror('Ошибка', 'Не удалось получить путь папки')
                return
            
            folder_path = str(tags[0]).strip()
            
            # Убедиться, что путь абсолютный
            if not os.path.isabs(folder_path):
                folder_path = os.path.abspath(folder_path)
        except (IndexError, ValueError, AttributeError) as e:
            messagebox.showerror('Ошибка', 'Не удалось получить путь папки')
            return
        
        # Создать окно выбора
        from window_persistence import setup_window_persistence, save_window_geometry, center_window_on_parent
        
        dialog = tk.Toplevel(self)
        dialog.title('Выбор жанра')
        dialog.transient(self)  # Сделать окно зависимым от главного
        dialog.grab_set()  # Перехватить фокус - окно модальное
        
        ttk.Label(dialog, text=f'Выберите жанр для:\n{path_text}').pack(padx=10, pady=10)
        
        # Listbox для выбора жанра
        listbox_frame = ttk.Frame(dialog)
        listbox_frame.pack(fill='both', expand=True, padx=10, pady=5)
        
        listbox = tk.Listbox(listbox_frame, height=10)
        listbox.pack(side='left', fill='both', expand=True)
        
        scrollbar = ttk.Scrollbar(listbox_frame, command=listbox.yview)
        scrollbar.pack(side='right', fill='y')
        listbox.config(yscrollcommand=scrollbar.set)
        
        # Добавить жанры
        for genre in genres:
            listbox.insert(tk.END, genre)
        
        # Progress window reference
        progress_window = None
        filename_label = None
        counter_label = None
        
        def update_progress(current: int, total: int, filename: str):
            """Обновить прогресс."""
            nonlocal progress_window, filename_label, counter_label
            
            if progress_window:
                if filename_label:
                    filename_label.config(text=f'{filename}')
                if counter_label:
                    counter_label.config(text=f'({current}/{total})')
                progress_window.update()
        
        def on_completion(count: int):
            """Завершение обработки."""
            nonlocal progress_window
            
            if progress_window:
                # Сохранить позицию прогресс окна перед закрытием
                save_window_geometry(progress_window, 'assign_genre_progress', self.settings)
                progress_window.destroy()
                progress_window = None
            
            # Сохранить позицию диалога перед закрытием
            save_window_geometry(dialog, 'genre_select', self.settings)
            
            # Обновить статус бар
            self.progress_var.set(f'Жанр изменен у {count} файлов')
            
            self.logger.log(f'Жанр "{selected_genre}" присвоен {count} файлам в "{path_text}"')
            
            dialog.destroy()
        
        def confirm():
            nonlocal progress_window, filename_label, counter_label, selected_genre
            
            selection = listbox.curselection()
            if not selection:
                messagebox.showwarning('Внимание', 'Выберите жанр из списка')
                return
            
            selected_genre = listbox.get(selection[0])
            
            # Создать окно прогресса
            # ВАЖНО: Создаем как child от main window (self), НЕ от dialog!
            # Так оно останется видимым когда мы скроем dialog
            progress_window = tk.Toplevel(self)
            progress_window.title('Присвоение жанра')
            progress_window.resizable(False, False)
            progress_window.transient(self)  # Сделать окно зависимым от главного
            progress_window.grab_set()  # Перехватить фокус - окно модальное
            
            # Информация
            info_label = ttk.Label(
                progress_window,
                text=f'Присвоение жанра: {selected_genre}',
                font=('Arial', 9)
            )
            info_label.pack(padx=10, pady=(8, 2))
            
            # Название файла (первая строка прогресса)
            filename_label = ttk.Label(
                progress_window,
                text='Инициализация...',
                font=('Arial', 8)
            )
            filename_label.pack(padx=10, pady=2)
            
            # Счетчик (вторая строка прогресса)
            counter_label = ttk.Label(
                progress_window,
                text='(0/0)',
                font=('Arial', 8)
            )
            counter_label.pack(padx=10, pady=(2, 8))
            
            # Отключить закрытие окна во время обработки
            def on_closing():
                messagebox.showwarning('Внимание', 'Пожалуйста, дождитесь завершения обработки')
            
            progress_window.protocol('WM_DELETE_WINDOW', on_closing)
            
            # Настройка сохранения размера и позиции окна (ПОСЛЕ создания всех элементов)
            # Используем деferred callback для правильной работы в мультимониторной среде
            def setup_progress_persistence():
                progress_window.transient(self)
                
                # Получить центрированную позицию (в случае если было сохранено за границами экрана)
                centered_geometry = center_window_on_parent(progress_window, self, width=450, height=120)
                
                setup_window_persistence(progress_window, 'assign_genre_progress', self.settings, centered_geometry)
                
                # Сохранить позицию на закрытие
                def on_progress_close():
                    save_window_geometry(progress_window, 'assign_genre_progress', self.settings)
                    progress_window.destroy()
                
                # Переопределить обработчик закрытия после setup
                progress_window.protocol('WM_DELETE_WINDOW', on_closing)
            
            # Отложить setup до следующей итерации event loop
            progress_window.after(1, setup_progress_persistence)
            
            # Показать окно прогресса
            progress_window.deiconify()
            progress_window.update()
            
            # Скрыть диалог выбора
            dialog.withdraw()
            
            # Запустить присвоение жанра в отдельном потоке
            assign_genre_threaded(
                folder_path,
                selected_genre,
                progress_callback=update_progress,
                completion_callback=on_completion,
                logger=self.logger  # Передаем логгер приложения
            )
        
        selected_genre = None  # Variable для использования в on_completion
        
        # Кнопки
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill='x', padx=10, pady=10)
        
        ttk.Button(btn_frame, text='Присвоить', command=confirm).pack(side='left', padx=5)
        ttk.Button(btn_frame, text='Отмена', command=dialog.destroy).pack(side='left', padx=5)
        
        # Настройка сохранения размера и позиции окна (ПОСЛЕ создания всех элементов)
        # Используем деferred callback для правильной работы в мультимониторной среде
        def setup_dialog_persistence():
            dialog.transient(self)
            dialog.grab_set()
            
            # Получить центрированную позицию (в случае если было сохранено за границами экрана)
            centered_geometry = center_window_on_parent(dialog, self, width=400, height=300)
            
            setup_window_persistence(dialog, 'genre_select', self.settings, centered_geometry)
            
            # Сохранить позицию на закрытие
            def on_dialog_close():
                save_window_geometry(dialog, 'genre_select', self.settings)
                dialog.destroy()
            
            dialog.protocol('WM_DELETE_WINDOW', on_dialog_close)
        
        # Отложить setup до следующей итерации event loop
        dialog.after(1, setup_dialog_persistence)
    
    def _store_genre_for_item(self, tree_item: str, path: str, genre: str):
        """Сохранить выбранный жанр для элемента дерева."""
        # Сохраняем в памяти приложения (можно расширить чтобы сохранять в конфиг)
        if not hasattr(self, 'genre_assignments'):
            self.genre_assignments = {}
        
        self.genre_assignments[path] = genre
        
        # Обновить текст элемента в дереве (добавить жанр)
        try:
            current_text = self.folder_tree.item(tree_item, 'text')
            if ' [' not in current_text:  # Если еще не добавили жанр
                new_text = f"{current_text} [{genre}]"
                self.folder_tree.item(tree_item, text=new_text)
        except:
            pass

    def _on_closing(self):
        """Обработчик закрытия окна."""
        save_window_geometry(self, 'main', self.settings)
        self.destroy()


def main():
    """Точка входа приложения."""
    app = MainWindow()
    app.mainloop()


if __name__ == '__main__':
    main()
