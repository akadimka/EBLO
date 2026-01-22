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

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

# Window persistence
from window_persistence import save_window_geometry, restore_window_geometry
from window_manager import get_window_manager

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
    
except Exception as e:
    try:
        from .genres_manager import GenresManager
        from .settings_manager import SettingsManager
        from .logger import Logger
        from .gui_genres import GenresManagerWindow
        from .gui_normalizer import CSVNormalizerApp
    except ImportError:
        from fb2parser.genres_manager import GenresManager
        from fb2parser.settings_manager import SettingsManager
        from fb2parser.logger import Logger
        from fb2parser.gui_genres import GenresManagerWindow
        from fb2parser.gui_normalizer import CSVNormalizerApp


class MainWindow(tk.Tk):
    """Главное окно приложения."""
    
    def __init__(self):
        super().__init__()
        self.title('EBook Library Organizer')
        self.minsize(800, 500)
        
        # Инициализация менеджера окон
        window_manager = get_window_manager()
        window_manager.register_main_window(self)
        
        # Инициализация модулей
        self.logger = Logger()
        self.settings = SettingsManager('config.json')
        
        # Восстановление позиции/размера окна
        restore_window_geometry(self, 'main', self.settings, 
                              default_geometry='1000x700+100+50')

        # Загружаем файл жанров из конфига (если он там сохранен)
        genres_file = self.settings.get_genres_file_path()
        self.genres_manager = GenresManager(genres_file)
        
        # Переменные состояния
        self.selected_folder = tk.StringVar()
        self.progress_var = tk.StringVar(value='Готово')
        self.view_mode = 'tree'  # 'tree' или 'listboxes'

        # Обработчик закрытия окна
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

        # Создание UI
        self._create_menu()
        self._create_main_ui()
        
        # Установка начального значения папки
        default_folder = self.settings.get_last_scan_path() or self.settings.get_library_path() or os.path.expanduser('~')
        self.selected_folder.set(default_folder)
        self.selected_folder.trace('w', self._on_folder_changed)
        
        # Загружаем структуру папок после создания UI
        self.after(100, self._populate_folder_tree)

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
        menubar.add_cascade(label='Действия', menu=self.action_menu)
        
        # Жанры
        genres_menu = tk.Menu(menubar, tearoff=0)
        genres_menu.add_command(label='Менеджер жанров', command=self._open_genres_manager)
        menubar.add_cascade(label='Жанры', menu=genres_menu)
        
        # Лог
        log_menu = tk.Menu(menubar, tearoff=0)
        log_menu.add_command(label='Показать лог', command=self._show_log_window)
        menubar.add_cascade(label='Лог', menu=log_menu)
        
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
        self.status = ttk.Label(self, textvariable=self.progress_var, anchor='w')
        self.status.pack(fill='x', side='bottom', padx=5, pady=2)

        # Основные панели
        self.main_pane = ttk.PanedWindow(self, orient='horizontal')
        self.main_pane.pack(fill='both', expand=True, padx=5, pady=5)

        # Панель жанров
        self.genres_frame = ttk.LabelFrame(self.main_pane, text='Жанры', padding=5)
        self.genres_list = tk.Listbox(self.genres_frame, height=15)
        self.genres_list.pack(fill='both', expand=True, side='left')
        self.genres_list.bind('<Double-Button-1>', self._on_genre_double_click)
        genres_scroll = ttk.Scrollbar(self.genres_frame, command=self.genres_list.yview)
        self.genres_list.config(yscrollcommand=genres_scroll.set)
        genres_scroll.pack(side='right', fill='y')

        # Панель ошибок
        self.errors_frame = ttk.LabelFrame(self.main_pane, text='Ошибки/Замечания', padding=5)
        self.errors_list = tk.Listbox(self.errors_frame, height=15)
        self.errors_list.pack(fill='both', expand=True, side='left')
        errors_scroll = ttk.Scrollbar(self.errors_frame, command=self.errors_list.yview)
        self.errors_list.config(yscrollcommand=errors_scroll.set)
        errors_scroll.pack(side='right', fill='y')

        # Панель деталей
        self.details_frame = ttk.LabelFrame(self.main_pane, text='Детали', padding=5)
        self.details_list = tk.Listbox(self.details_frame, height=15)
        self.details_list.pack(fill='both', expand=True, side='left')
        self.details_list.bind('<Double-Button-1>', self._on_detail_double_click)
        details_scroll = ttk.Scrollbar(self.details_frame, command=self.details_list.yview)
        self.details_list.config(yscrollcommand=details_scroll.set)
        details_scroll.pack(side='right', fill='y')
        
        # Панель с деревом папок
        self.folder_tree_frame = ttk.LabelFrame(self.main_pane, text='Структура папок', padding=5)
        self.folder_tree = ttk.Treeview(self.folder_tree_frame)
        self.folder_tree.pack(fill='both', expand=True, side='left')
        folder_tree_scroll = ttk.Scrollbar(self.folder_tree_frame, command=self.folder_tree.yview)
        self.folder_tree.config(yscrollcommand=folder_tree_scroll.set)
        folder_tree_scroll.pack(side='right', fill='y')
        self.folder_tree.bind('<Double-Button-1>', self._on_folder_tree_double_click)
        
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
                subprocess.Popen(f'explorer "{folder_path}"')
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
        """Обработчик изменения выбранной папки."""
        folder = self.selected_folder.get()
        if folder and self.view_mode == 'tree' and hasattr(self, 'folder_tree'):
            self._populate_folder_tree()

    def _on_genre_double_click(self, event=None):
        """Обработчик двойного клика по жанру."""
        pass

    def _on_detail_double_click(self, event=None):
        """Обработчик двойного клика по деталям."""
        pass

    def _show_log_window(self):
        """Показать окно логов."""
        win = tk.Toplevel(self)
        win.title('Лог')
        
        geometry = self.settings.get_window_geometry('log')
        if geometry:
            win.geometry(geometry)
        else:
            win.geometry('700x400')
            
        frame = ttk.Frame(win)
        frame.pack(fill='both', expand=True, padx=10, pady=10)
        log_list = tk.Listbox(frame)
        log_list.pack(fill='both', expand=True, side='left')
        scroll = ttk.Scrollbar(frame, command=log_list.yview)
        log_list.config(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        
        for entry in self.logger.get_entries():
            log_list.insert(tk.END, entry)
        
        btns = ttk.Frame(win)
        btns.pack(fill='x', pady=5)
        ttk.Button(btns, text='Очистить', command=lambda: self._clear_log_and_update(log_list)).pack(side='left', padx=10)
        ttk.Button(btns, text='Закрыть', command=win.destroy).pack(side='left')
        
        def on_closing():
            geometry = win.geometry()
            self.settings.set_window_geometry('log', geometry)
            win.destroy()
            
        win.protocol("WM_DELETE_WINDOW", on_closing)

    def _clear_log_and_update(self, log_list):
        """Очистить лог."""
        self.logger.clear()
        log_list.delete(0, tk.END)
        self.logger.log('Лог очищен')

    def _open_genres_manager(self):
        """Открыть менеджер жанров."""
        GenresManagerWindow(self, self.genres_manager, lambda: None)

    def _open_settings(self):
        """Открыть окно настроек."""
        try:
            import gui_settings
            import importlib
            importlib.reload(gui_settings)
            from gui_settings import SettingsWindow
        except Exception:
            try:
                from .gui_settings import SettingsWindow
            except ImportError:
                from fb2parser.gui_settings import SettingsWindow
        
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
        """Обработчик действия 'Сканирование'."""
        folder = self.selected_folder.get()
        if not folder:
            messagebox.showwarning('Внимание', 'Не выбрана папка для обработки')
            return
        
        self.progress_var.set('Сканирование...')
        self.logger.log(f'Начато сканирование: {folder}')
        # TODO: Реализовать сканирование

    def _on_normalization_action(self):
        """Обработчик действия 'Нормализация'. Открывает окно нормализации."""
        try:
            import gui_normalizer
            import importlib
            importlib.reload(gui_normalizer)
            from gui_normalizer import CSVNormalizerApp
        except Exception:
            try:
                from .gui_normalizer import CSVNormalizerApp
            except ImportError:
                from fb2parser.gui_normalizer import CSVNormalizerApp
        
        # Создаем новое окно для нормализации
        normalizer_root = tk.Toplevel(self)
        app = CSVNormalizerApp(normalizer_root)
        self.logger.log('Окно нормализации открыто')
        window_manager = get_window_manager()
        window_manager.open_child_window(self, normalizer_root)

    def _on_synchronization_action(self):
        """Обработчик действия 'Синхронизация'."""
        self.logger.log('Синхронизация запущена')
        # TODO: Реализовать синхронизацию

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
