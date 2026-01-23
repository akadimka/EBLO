"""
Модуль для парсинга FB2 файлов и извлечения информации об авторах.

Реализует многоуровневую стратегию извлечения авторов:
1. Структура папок (FOLDER_STRUCTURE)
2. Название файла (FILENAME)
3. Метаданные FB2 (FB2_METADATA)

Использует приоритезацию из extraction_constants.AuthorExtractionPriority
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

try:
    from author_processor import AuthorProcessor
    from extraction_constants import (
        AuthorExtractionPriority,
        ConfidenceLevel,
        FilterReason,
        ExtractionResult
    )
    from settings_manager import SettingsManager
except ImportError:
    from .author_processor import AuthorProcessor
    from .extraction_constants import (
        AuthorExtractionPriority,
        ConfidenceLevel,
        FilterReason,
        ExtractionResult
    )
    from .settings_manager import SettingsManager


class FB2AuthorExtractor:
    """Извлечение информации об авторах из FB2 файлов."""
    
    def __init__(self, config_path: str = 'config.json'):
        """
        Инициализация экстрактора авторов FB2.
        
        Args:
            config_path: Путь к файлу конфигурации
        """
        self.settings = SettingsManager(config_path)
        self.author_processor = AuthorProcessor(config_path)
    
    def extract_all_authors(
        self,
        fb2_filepath: str,
        apply_priority: bool = True
    ) -> Dict[str, Any]:
        """
        Комбинированное извлечение авторов из всех источников.
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
            apply_priority: Применять ли приоритизацию результатов
        
        Returns:
            Структурированный результат с авторами и метаданными:
            {
                'primary_author': {
                    'name': str,
                    'priority': int,
                    'source': str,
                    'confidence': float,
                    ...
                },
                'alternative_authors': [...],
                'all_results_by_priority': {
                    priority: [ExtractionResult, ...],
                    ...
                },
                'processing_info': {
                    'fb2_path': str,
                    'file_name': str,
                    'folder_path': str,
                    ...
                }
            }
        """
        # TODO: Реализовать полный процесс извлечения
        # 1. Получить информацию о пути к файлу
        # 2. Вызвать extract_from_folder_structure()
        # 3. Вызвать extract_from_filename()
        # 4. Вызвать extract_from_fb2_metadata()
        # 5. Слить результаты используя merge_results_by_priority()
        # 6. Вернуть структурированный результат
        pass
    
    def extract_from_folder_structure(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из структуры папок.
        
        Приоритет: AuthorExtractionPriority.FOLDER_STRUCTURE (1)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из структуры папок
        # - Получить папку файла
        # - Применить author_processor.extract_author_from_filepath()
        # - Проверить результаты против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FOLDER_STRUCTURE
        pass
    
    def extract_from_filename(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из названия файла.
        
        Приоритет: AuthorExtractionPriority.FILENAME (2)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из названия файла
        # - Получить имя файла без расширения
        # - Применить author_processor.extract_author_from_filename()
        # - Проверить результаты против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FILENAME
        pass
    
    def extract_from_fb2_metadata(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из метаданных FB2 файла.
        
        Приоритет: AuthorExtractionPriority.FB2_METADATA (3)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из метаданных FB2
        # - Прочитать и спарсить XML FB2 файла
        # - Найти раздел <description>/<title-info>/<author>
        # - Извлечь first-name, last-name, nickname
        # - Применить автора_processor для нормализации
        # - Проверить против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FB2_METADATA
        pass
    
    def _parse_fb2_xml(self, fb2_filepath: str) -> Optional[ET.Element]:
        """
        Прочитать и спарсить FB2 файл.
        
        Args:
            fb2_filepath: Путь к FB2 файлу
        
        Returns:
            Корневой элемент дерева XML или None при ошибке
        """
        # TODO: Реализовать парсинг FB2
        # - Обработать кодировку (обычно UTF-8 или иная)
        # - Обработать ошибки парсинга
        # - Вернуть корневой элемент
        pass
    
    def merge_results_by_priority(
        self,
        results_by_priority: Dict[int, List[ExtractionResult]]
    ) -> Tuple[Optional[ExtractionResult], List[ExtractionResult]]:
        """
        Слить результаты с учетом приоритетов.
        
        Логика:
        - Итерировать по AuthorExtractionPriority.ORDER
        - Первый найденный результат (не отфильтрованный) становится основным
        - Остальные результаты становятся альтернативами
        - Результаты с более низким приоритетом идут в конец
        
        Args:
            results_by_priority: Словарь {priority: [ExtractionResult, ...]}
        
        Returns:
            (primary_result, alternative_results)
        """
        # TODO: Реализовать слияние по приоритетам
        # - Пройти по AuthorExtractionPriority.ORDER
        # - Найти первый не отфильтрованный результат
        # - Этот становится основным
        # - Остальные - альтернативы
        pass
    
    def _apply_blacklist_filter(
        self,
        value: str
    ) -> Tuple[bool, List[str]]:
        """
        Применить фильтр черного списка к значению.
        
        Args:
            value: Значение для фильтрации
        
        Returns:
            (is_filtered, reasons) - был ли отфильтрован и почему
        """
        # TODO: Реализовать фильтрацию
        # - Получить filename_blacklist из конфигурации
        # - Проверить точное совпадение (case-insensitive)
        # - Проверить совпадение подстроки
        # - Вернуть результат
        pass
    
    def reload_config(self):
        """Перезагрузить конфигурацию и паттерны."""
        self.settings.load()
        self.author_processor.reload_patterns()


if __name__ == '__main__':
    # Простой тест
    extractor = FB2AuthorExtractor()
    print("FB2AuthorExtractor инициализирован")
    print(f"AuthorProcessor: {extractor.author_processor}")
    print(f"Приоритеты извлечения:")
    for priority in AuthorExtractionPriority.ORDER:
        print(f"  {priority}: {AuthorExtractionPriority.get_name(priority)}")
