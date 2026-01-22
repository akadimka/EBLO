"""
Модуль для обработки и извлечения информации о серии из названия файла или пути.

Использует конфигурационные списки паттернов для поиска серий в:
- Названиях файлов (author_series_patterns_in_files)
- Структурах папок (author_series_patterns_in_folders)
"""

import re
from typing import Optional, List, Dict, Tuple, Any

try:
    from settings_manager import SettingsManager
    from pattern_converter import compile_patterns
except ImportError:
    from .settings_manager import SettingsManager
    from .pattern_converter import compile_patterns


class SeriesProcessor:
    """Класс для обработки и извлечения информации о серии из файлов и путей."""
    
    def __init__(self, config_path: str = 'config.json', folder_parse_limit: Optional[int] = None):
        """
        Инициализация процессора серий.
        
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
        self.sequence_patterns = None
        self._load_patterns()
    
    def _load_patterns(self):
        """Загрузить паттерны из конфигурации и скомпилировать их."""
        # Загружаем паттерны для поиска в названиях файлов
        file_patterns_raw = self.settings.get_author_series_patterns_in_files()
        self.file_patterns = compile_patterns(file_patterns_raw) if file_patterns_raw else []
        
        # Загружаем паттерны для поиска в структурах папок
        folder_patterns_raw = self.settings.get_author_series_patterns_in_folders()
        self.folder_patterns = compile_patterns(folder_patterns_raw) if folder_patterns_raw else []
        
        # Загружаем паттерны для поиска номеров в последовательности
        sequence_patterns_raw = self.settings.get_sequence_patterns()
        self.sequence_patterns = compile_patterns(sequence_patterns_raw) if sequence_patterns_raw else []
    
    def extract_series_from_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь информацию о серии из названия файла.
        
        Args:
            filename: Название файла (без расширения)
        
        Returns:
            Словарь с информацией о серии или None
            Структура: {
                'series': str,           # Название серии
                'pattern': str,          # Использованный паттерн
                'pattern_index': int,    # Индекс паттерна в списке
                'confidence': float,     # Уверенность (0.0-1.0)
                'groups': dict           # Все извлечённые группы из regex
            }
        """
        # TODO: Реализовать логику извлечения серии из названия файла
        # - Применить все паттерны file_patterns
        # - Найти совпадение в названии файла
        # - Извлечь группу 'series' (если есть)
        # - Вернуть результат с уверенностью
        pass
    
    def extract_series_from_filepath(self, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь информацию о серии из пути файла (анализ структуры папок).
        
        Args:
            filepath: Полный путь к файлу
        
        Returns:
            Словарь с информацией о серии или None
        """
        # TODO: Реализовать логику извлечения серии из структуры папок
        # - Разбить путь на составные части
        # - Применить паттерны folder_patterns к названиям папок
        # - Найти совпадение
        # - Вернуть результат с указанием уровня вложенности
        pass
    
    def extract_sequence_number(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Извлечь номер последовательности/книги в серии.
        
        Args:
            text: Текст для поиска номера (обычно часть имени файла или папки)
        
        Returns:
            Словарь с информацией о номере или None
            Структура: {
                'number': int,           # Извлечённый номер
                'pattern': str,          # Использованный паттерн
                'position': tuple,       # (start, end) позиция в тексте
                'confidence': float      # Уверенность (0.0-1.0)
            }
        """
        # TODO: Реализовать логику извлечения номера последовательности
        # - Применить sequence_patterns
        # - Извлечь числовое значение
        # - Вернуть номер и позицию в строке
        pass
    
    def extract_series_combined(self, filename: str, filepath: str) -> Optional[Dict[str, Any]]:
        """
        Попытаться извлечь информацию о серии, комбинируя различные методы.
        
        Args:
            filename: Название файла
            filepath: Полный путь к файлу
        
        Returns:
            Словарь с наиболее вероятной информацией о серии
            Структура: {
                'series': str,           # Название серии
                'number': Optional[int], # Номер в серии (если извлечён)
                'source': str,           # Источник: 'filename' или 'filepath'
                'confidence': float      # Общая уверенность
            }
        """
        # TODO: Реализовать комбинированную логику
        # - Попробовать extract_series_from_filename
        # - Попробовать extract_series_from_filepath
        # - Для каждого результата попробовать extract_sequence_number
        # - Выбрать результат с наибольшей уверенностью
        # - Вернуть результат с указанием источника
        pass
    
    def categorize_series(self, series_name: str) -> Optional[Dict[str, Any]]:
        """
        Определить категорию/жанр серии на основе названия.
        
        Args:
            series_name: Название серии
        
        Returns:
            Словарь с информацией о категории или None
            Структура: {
                'category': str,         # Определённая категория
                'keywords': list,        # Найденные ключевые слова
                'confidence': float      # Уверенность определения
            }
        """
        # TODO: Реализовать логику категоризации
        # - Использовать series_category_words из конфигурации
        # - Найти совпадения в названии серии
        # - Определить категорию
        # - Вернуть результат
        pass
    
    def reload_patterns(self):
        """Перезагрузить паттерны из конфигурации."""
        self._load_patterns()


if __name__ == '__main__':
    # Простой тест
    processor = SeriesProcessor()
    print("SeriesProcessor инициализирован")
    print(f"Паттерны в файлах: {len(processor.file_patterns)}")
    print(f"Паттерны в папках: {len(processor.folder_patterns)}")
    print(f"Паттерны последовательности: {len(processor.sequence_patterns)}")
