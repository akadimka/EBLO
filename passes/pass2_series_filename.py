"""
PASS 2 для СЕРИЙ: Извлечение серий из имён файлов.
Аналог pass2_filename.py (для авторов) но специализирован на СЕРИИ.
"""

import re
from pathlib import Path
from typing import List

try:
    from BookRecord import BookRecord
except ImportError:
    # Если прямой импорт не работает, попробовать относительный
    from dataclasses import dataclass
    @dataclass
    class BookRecord:
        file_path: str = ""
        metadata_authors: str = ""
        proposed_author: str = ""
        author_source: str = ""
        metadata_series: str = ""
        proposed_series: str = ""
        series_source: str = ""
        file_title: str = ""

from logger import Logger
from settings_manager import SettingsManager
from name_normalizer import AuthorName


class Pass2SeriesFilename:
    """Извлечение серий из имён файлов."""
    
    def __init__(self, logger: Logger = None):
        self.logger = logger or Logger()
        self.settings = SettingsManager('config.json')
        # Получить списки из config.json
        self.collection_keywords = self.settings.get_list('collection_keywords')
        self.service_words = self.settings.get_list('service_words')
    
    def execute(self, records: List[BookRecord]) -> None:
        """
        Попытаться извлечь серию из имена файла.
        
        Пропускает файлы которые уже имеют folder_dataset серию.
        """
        for record in records:
            # Пропускаем если серия уже установлена из папок
            if record.series_source == "folder_dataset":
                continue
            
            # Пропускаем если уже есть какая-то серия
            if record.proposed_series:
                continue
            
            series = self._extract_series_from_filename(record.file_path)
            
            if series:
                record.proposed_series = series
                record.series_source = "filename"
    
    def _extract_series_from_filename(self, file_path: str) -> str:
        """
        Извлечь серию из имени файла по паттернам.
        
        Паттерны (в порядке приоритета):
        1. "[Серия]" или "«Серия»" в маркерах
        2. "Название (Серия №1)" - серия в скобках в конце
        3. "Серия. Название" - серия в начале
        """
        filename = Path(file_path).name
        name_without_ext = filename.rsplit('.', 1)[0]
        
        # Паттерн 1: [Серия] в квадратных скобках
        match = re.search(r'^\[([^\[\]]+)\]', name_without_ext)
        if match:
            series = match.group(1).strip()
            if self._is_valid_series(series):
                return series
        
        # Паттерн 2: Название (Серия) - поиск в скобках в КОНЦЕ
        if '(' in name_without_ext and ')' in name_without_ext:
            # Ищем скобку в конце после сервис-слова (том, книга) или просто скобку
            match = re.search(r'(?:(?:том|книга|выпуск|ч|кн)\s*)?\(?([^)]+)\)\s*$', name_without_ext, re.IGNORECASE)
            
            if match:
                potential_series = match.group(1).strip()
                # Убедиться что это СЕРИЯ, а не описание или автор
                if self._is_valid_series(potential_series):
                    return potential_series
        
        # Паттерн 3: Серия. Название
        if '. ' in name_without_ext:
            potential_series = name_without_ext.split('. ')[0].strip()
            if self._is_valid_series(potential_series):
                return potential_series
        
        return ""
    
    def _is_valid_series(self, text: str) -> bool:
        """
        Проверить что text выглядит как название серии, не как другое.
        Использует AuthorName ТОЛЬКО для проверки что это не автор!
        """
        if not text or len(text) < 2:
            return False
        
        # Исключить очевидные сборники/антологии
        text_lower = text.lower()
        for keyword in self.collection_keywords:
            if keyword.lower() in text_lower:
                return False
        
        # Исключить сервис-слова (том, книга, выпуск)
        for service_word in self.service_words:
            if text_lower.startswith(service_word.lower()):
                return False
        
        # ✅ ПРОВЕРКА: Убедиться что это НЕ похоже на автора!
        try:
            author = AuthorName(text, [])
            if author.is_valid_author():
                return False  # Это похоже на автора, отвергаем как серию
        except Exception:
            pass  # Если парсинг не сработал - это вероятно серия
        
        return True
