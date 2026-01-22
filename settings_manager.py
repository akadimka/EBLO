"""
Settings Manager Module / Модуль управления настройками

Handles configuration and settings management.

/ Работа с конфигом и настройками.
"""
import json
from pathlib import Path
import copy

class SettingsManager:
    """
    Manages application settings and configuration.
    
    / Управляет настройками приложения и конфигурацией.
    """
    
    def __init__(self, config_path):
        """
        Initialize settings manager.
        
        / Инициализация менеджера настроек.
        """
        self.config_path = Path(config_path)
        self.settings = {
            'library_path': '',
            'last_scan_path': '',
            'genres_file_path': 'genres.xml',  # Путь к файлу жанров
            'genre_association_method': 'context_menu',
            'window_sizes': {}  # Для хранения размеров окон
        }
        self._loaded_settings = None  # Для отслеживания оригинальных значений
        self.load()

    def load(self):
        """Load settings from config file / Загрузить настройки из файла конфига."""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.settings = json.load(f)
        # Сохраняем копию загруженных настроек для проверки изменений
        self._loaded_settings = copy.deepcopy(self.settings)

    def _has_changes(self):
        """Проверить, были ли изменения в настройках / Check if settings have changed."""
        if self._loaded_settings is None:
            return True
        return self.settings != self._loaded_settings

    def save(self):
        """Save settings to config file if changed / Сохранить настройки в файл конфига если были изменения."""
        # Проверяем, были ли действительные изменения
        if not self._has_changes():
            return
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.settings, f, ensure_ascii=False, indent=2)
        
        # После сохранения обновляем копию
        self._loaded_settings = copy.deepcopy(self.settings)

    def set_library_path(self, path):
        """Set library path / Установить путь к библиотеке."""
        self.settings['library_path'] = path
        self.save()
        
    def get_genre_association_method(self):
        """Get genre association method / Получить метод ассоциации жанров."""
        return self.settings.get('genre_association_method', 'context_menu')
        
    def set_genre_association_method(self, method):
        """Set genre association method / Установить метод ассоциации жанров."""
        self.settings['genre_association_method'] = method
        self.save()

    def get_library_path(self):
        """Get library path / Получить путь к библиотеке."""
        return self.settings.get('library_path', '')
        
    def set_last_scan_path(self, path):
        """Set last scan path / Установить последний путь сканирования."""
        self.settings['last_scan_path'] = path
        self.save()
        
    def get_last_scan_path(self):
        """Get last scan path / Получить последний путь сканирования."""
        return self.settings.get('last_scan_path', '')

    def get_genres_file_path(self):
        """Get genres file path / Получить путь к файлу жанров."""
        return self.settings.get('genres_file_path', 'genres.xml')
        
    def set_genres_file_path(self, path):
        """Set genres file path / Установить путь к файлу жанров."""
        self.settings['genres_file_path'] = path
        self.save()

    def get_folder_parse_limit(self):
        """Get folder parse limit / Получить предел количества папок при парсинге."""
        return self.settings.get('folder_parse_limit', 5)
        
    def set_folder_parse_limit(self, limit):
        """Set folder parse limit / Установить предел количества папок при парсинге."""
        try:
            self.settings['folder_parse_limit'] = int(limit)
        except (ValueError, TypeError):
            # Если не удаётся преобразовать в int, используем значение по умолчанию
            self.settings['folder_parse_limit'] = 5
        self.save()

    def get_test_window_path(self):
        """
        Get test window saved path.
        
        / Получает сохраненный путь для окна тестирования.
        """
        return self.settings.get('test_window_path', '')
        
    def set_test_window_path(self, path):
        """
        Set test window path.
        
        / Сохраняет путь для окна тестирования.
        """
        self.settings['test_window_path'] = path
        self.save()

    def set_window_size(self, window_name, width, height):
        """
        Save window size.
        
        / Сохраняет размеры окна.
        """
        if 'window_sizes' not in self.settings:
            self.settings['window_sizes'] = {}
        self.settings['window_sizes'][window_name] = {'width': width, 'height': height}
        self.save()

    def get_window_size(self, window_name):
        """
        Get saved window size.
        
        / Получает сохраненные размеры окна.
        """
        sizes = self.settings.get('window_sizes', {})
        return sizes.get(window_name, None)

    def set_window_geometry(self, window_name, geometry):
        """
        Save window geometry (size and position).
        
        / Сохраняет геометрию окна (размеры и позицию).
        """
        if 'window_sizes' not in self.settings:
            self.settings['window_sizes'] = {}
        self.settings['window_sizes'][window_name] = geometry
        self.save()

    def get_window_geometry(self, window_name):
        """
        Get saved window geometry.
        
        / Получает сохраненную геометрию окна.
        """
        sizes = self.settings.get('window_sizes', {})
        return sizes.get(window_name, None)

    def set_genre_tree_state(self, expanded_nodes):
        """
        Save genre tree state (expanded nodes).
        
        / Сохраняет состояние дерева жанров (развернутые узлы).
        """
        if 'genre_tree_state' not in self.settings:
            self.settings['genre_tree_state'] = {}
        self.settings['genre_tree_state']['expanded_nodes'] = list(expanded_nodes)
        self.save()

    def get_genre_tree_state(self):
        """
        Get saved genre tree state.
        
        / Получает сохраненное состояние дерева жанров.
        """
        state = self.settings.get('genre_tree_state', {})
        return set(state.get('expanded_nodes', []))

    # --- Blacklist helpers / Вспомогательные функции черного списка ---
    
    def get_filename_blacklist(self):
        """
        Get filename blacklist tokens.
        
        / Возвращает список токенов, используемых для проверки имени файла.
        """
        lst = self.settings.get('filename_blacklist')
        if lst is None:
            return []
        return list(lst)

    def set_filename_blacklist(self, lst):
        """
        Set filename blacklist and save config.
        
        / Устанавливает список токенов для filename_blacklist и сохраняет конфиг.
        """
        if lst is None:
            self.settings.pop('filename_blacklist', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            # store as list of strings
            self.settings['filename_blacklist'] = unique_list
        self.save()

    # Generic list helpers
    def list_list_keys(self):
        """Return top-level keys in settings whose value is a list."""
        return [k for k, v in self.settings.items() if isinstance(v, list)]

    def get_list(self, key):
        """Get a list value by key (or None if not present or not a list)."""
        v = self.settings.get(key)
        if isinstance(v, list):
            return list(v)
        return None

    def set_list(self, key, lst):
        """Set a top-level list value and save. If lst is None, remove the key.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop(key, None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            self.settings[key] = unique_list
        self.save()

    # --- Female names helpers ---
    def get_female_names(self):
        """Возвращает список женских имён."""
        lst = self.settings.get('female_names')
        if lst is None:
            return []
        return list(lst)

    def set_female_names(self, lst):
        """Устанавливает список женских имён и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('female_names', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            # store as list of strings
            self.settings['female_names'] = unique_list
        self.save()

    def add_female_name(self, name):
        """Добавляет женское имя в список (если его там ещё нет, case-insensitive)."""
        names = self.get_female_names()
        if name and not any(n.lower() == name.lower() for n in names):
            names.append(name)
            self.set_female_names(names)

    # --- Male names helpers ---
    def get_male_names(self):
        """Возвращает список мужских имён."""
        lst = self.settings.get('male_names')
        if lst is None:
            return []
        return list(lst)

    def set_male_names(self, lst):
        """Устанавливает список мужских имён и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('male_names', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            # store as list of strings
            self.settings['male_names'] = unique_list
        self.save()

    def add_male_name(self, name):
        """Добавляет мужское имя в список (если его там ещё нет, case-insensitive)."""
        names = self.get_male_names()
        if name and not any(n.lower() == name.lower() for n in names):
            names.append(name)
            self.set_male_names(names)

    # --- Service words helpers ---
    def get_service_words(self):
        """Возвращает список служебных слов."""
        lst = self.settings.get('service_words')
        if lst is None:
            return []
        return list(lst)

    def set_service_words(self, lst):
        """Устанавливает список служебных слов и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('service_words', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            # store as list of strings
            self.settings['service_words'] = unique_list
        self.save()

    # --- Sequence patterns helpers ---
    def get_sequence_patterns(self):
        """Возвращает список шаблонов поиска серий."""
        lst = self.settings.get('sequence_patterns')
        if lst is None:
            return []
        return list(lst)

    def set_sequence_patterns(self, lst):
        """Устанавливает список шаблонов поиска серий и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('sequence_patterns', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            # store as list of strings
            self.settings['sequence_patterns'] = unique_list
        self.save()





    # --- Abbreviations preserve case helpers ---
    def get_abbreviations_preserve_case(self):
        """Возвращает список аббревиатур для сохранения кейса."""
        lst = self.settings.get('abbreviations_preserve_case')
        if lst is None:
            return []
        return list(lst)

    def set_abbreviations_preserve_case(self, lst):
        """Устанавливает список аббревиатур для сохранения кейса и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('abbreviations_preserve_case', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            self.settings['abbreviations_preserve_case'] = unique_list
        self.save()

    # --- Author initials and suffixes helpers ---
    def get_author_initials_and_suffixes(self):
        """Возвращает список инициалов и суффиксов авторов."""
        lst = self.settings.get('author_initials_and_suffixes')
        if lst is None:
            return []
        return list(lst)

    def set_author_initials_and_suffixes(self, lst):
        """Устанавливает список инициалов и суффиксов авторов и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('author_initials_and_suffixes', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            self.settings['author_initials_and_suffixes'] = unique_list
        self.save()

    # --- Series category words helpers ---
    def get_series_category_words(self):
        """Возвращает список категорийных слов для серий."""
        lst = self.settings.get('series_category_words')
        if lst is None:
            return []
        return list(lst)

    def set_series_category_words(self, lst):
        """Устанавливает список категорийных слов для серий и сохраняет конфиг.
        Removes duplicates (case-insensitive) while preserving order."""
        if lst is None:
            self.settings.pop('series_category_words', None)
        else:
            # Remove duplicates (case-insensitive) while preserving order
            seen = set()
            unique_list = []
            for item in lst:
                item_lower = str(item).lower()
                if item_lower not in seen:
                    seen.add(item_lower)
                    unique_list.append(str(item))
            self.settings['series_category_words'] = unique_list
        self.save()

    def get_author_series_patterns_in_files(self):
        """Возвращает список паттернов для поиска в имени файла."""
        lst = self.settings.get('author_series_patterns_in_files')
        if lst is None:
            return []
        return list(lst)

    def set_author_series_patterns_in_files(self, lst):
        """Устанавливает список паттернов для поиска в имени файла и сохраняет конфиг."""
        if lst is None:
            self.settings.pop('author_series_patterns_in_files', None)
        else:
            self.settings['author_series_patterns_in_files'] = list(lst)
        self.save()

    def get_author_series_patterns_in_folders(self):
        """Возвращает список паттернов для поиска в имени папки."""
        lst = self.settings.get('author_series_patterns_in_folders')
        if lst is None:
            return []
        return list(lst)

    def set_author_series_patterns_in_folders(self, lst):
        """Устанавливает список паттернов для поиска в имени папки и сохраняет конфиг."""
        if lst is None:
            self.settings.pop('author_series_patterns_in_folders', None)
        else:
            self.settings['author_series_patterns_in_folders'] = list(lst)
        self.save()

    def get_author_name_patterns(self):
        """Возвращает список паттернов для парсинга имени автора."""
        lst = self.settings.get('author_name_patterns')
        if lst is None:
            return []
        return list(lst)

    def set_author_name_patterns(self, lst):
        """Устанавливает список паттернов для парсинга имени автора и сохраняет конфиг."""
        if lst is None:
            self.settings.pop('author_name_patterns', None)
        else:
            self.settings['author_name_patterns'] = list(lst)
        self.save()

