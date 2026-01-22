"""
Модуль для обработки и извлечения информации об авторе из названия файла или пути.

Использует конфигурационные списки паттернов для поиска авторов в:
- Названиях файлов (author_series_patterns_in_files)
- Структурах папок (author_series_patterns_in_folders)
- Отдельных паттернах имён авторов (author_name_patterns)
"""

import re
from typing import Optional, List, Dict, Tuple, Any

try:
    from settings_manager import SettingsManager
    from pattern_converter import compile_patterns
except ImportError:
    from .settings_manager import SettingsManager
    from .pattern_converter import compile_patterns


class AuthorProcessor:
    """Класс для обработки и извлечения авторов из файлов и путей."""
    
    def __init__(self, config_path: str = 'config.json', folder_parse_limit: Optional[int] = None):
        """
        Инициализация процессора авторов.
        
        Args:
            config_path: Путь к файлу конфигурации
            folder_parse_limit: Предел количества папок при парсинге от файла.
                               Если None, загружается из конфигурации.
        """
        self.settings = SettingsManager(config_path)
        
        # Используем переданное значение или загружаем из конфигурации
        if folder_parse_limit is not None:
            self.folder_parse_limit = int(folder_parse_limit)
        else:
            self.folder_parse_limit = self.settings.get_folder_parse_limit()
        
        self.file_patterns = None
        self.folder_patterns = None
        self.author_patterns = None
        self._load_patterns()
    
    def _load_patterns(self):
        """Загрузить паттерны из конфигурации и скомпилировать их."""
        # Загружаем паттерны для поиска в названиях файлов
        file_patterns_raw = self.settings.get_author_series_patterns_in_files()
        self.file_patterns = compile_patterns(file_patterns_raw) if file_patterns_raw else []
        
        # Загружаем паттерны для поиска в структурах папок
        folder_patterns_raw = self.settings.get_author_series_patterns_in_folders()
        self.folder_patterns = compile_patterns(folder_patterns_raw) if folder_patterns_raw else []
        
        # Загружаем паттерны для парсинга имён авторов
        author_patterns_raw = self.settings.get_author_name_patterns()
        self.author_patterns = compile_patterns(author_patterns_raw) if author_patterns_raw else []
    
    def extract_author_from_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь информацию об авторе из названия файла.
        
        Args:
            filename: Название файла (без расширения)
        
        Returns:
            Словарь с информацией об авторе или None
            Структура: {
                'author': str,           # Имя автора
                'pattern': str,          # Использованный паттерн
                'pattern_index': int,    # Индекс паттерна в списке
                'confidence': float,     # Уверенность (0.0-1.0)
                'groups': dict           # Все извлечённые группы из regex
            }
        """
        # TODO: Реализовать логику извлечения автора из названия файла
        # - Применить все паттерны file_patterns
        # - Найти совпадение в названии файла
        # - Извлечь группу 'author' (если есть)
        # - Вернуть результат с уверенностью
        pass
    
    def extract_author_from_filepath(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь информацию об авторе из пути файла (анализ структуры папок).
        
        Args:
            filepath: Полный путь к файлу
        
        Returns:
            Словарь с информацией об авторе или None
        """
        # TODO: Реализовать логику извлечения автора из структуры папок
        # - Разбить путь на составные части
        # - Применить паттерны folder_patterns к названиям папок
        # - Найти совпадение
        # - Вернуть результат с указанием уровня вложенности
        pass
    
    def parse_author_name(self, author_string: str) -> Optional[Dict[str, Any]]:
        """
        Разобрать строку с именем автора используя конфигурационные паттерны.
        
        Args:
            author_string: Строка с именем автора
        
        Returns:
            Словарь с компонентами имени автора или None
            Структура: {
                'full_name': str,        # Полное имя
                'first_name': str,       # Имя (если извлечено)
                'last_name': str,        # Фамилия (если извлечено)
                'initials': str,         # Инициалы (если есть)
                'pattern': str,          # Использованный паттерн
                'groups': dict           # Все извлечённые группы
            }
        """
        # TODO: Реализовать логику парсинга имени автора
        # - Применить паттерны author_patterns
        # - Извлечь компоненты имени
        # - Нормализовать регистр (используя abbreviations_preserve_case)
        # - Вернуть структурированный результат
        pass
    
    def extract_author_combined(self, filename: str, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Попытаться извлечь автора, комбинируя различные методы.
        
        Args:
            filename: Название файла
            filepath: Полный путь к файлу
        
        Returns:
            Словарь с наиболее вероятным вариантом автора
        """
        # TODO: Реализовать комбинированную логику
        # - Попробовать extract_author_from_filename
        # - Попробовать extract_author_from_filepath
        # - Выбрать результат с наибольшей уверенностью
        # - Вернуть результат с указанием источника
        pass
    
    def reload_patterns(self):
        """Перезагрузить паттерны из конфигурации."""
        self._load_patterns()


if __name__ == '__main__':
    # Простой тест
    processor = AuthorProcessor()
    print("AuthorProcessor инициализирован")
    print(f"Паттерны в файлах: {len(processor.file_patterns)}")
    print(f"Паттерны в папках: {len(processor.folder_patterns)}")
    print(f"Паттерны для имён: {len(processor.author_patterns)}")
