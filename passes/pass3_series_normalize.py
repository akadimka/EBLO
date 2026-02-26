"""
PASS 3 для СЕРИЙ: Нормализация названий серий.
Аналог pass3_normalize.py (для авторов) но для СЕРИЙ.
"""

import re
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


class Pass3SeriesNormalize:
    """Нормализация названий серий."""
    
    def __init__(self, logger: Logger = None):
        self.logger = logger or Logger()
        self.settings = SettingsManager('config.json')
        # Get series conversions from config.json if available
        try:
            # Try to access the settings directly
            self.series_conversions = self.settings.settings.get('series_conversions', {})
        except (AttributeError, KeyError):
            self.series_conversions = {}
    
    def execute(self, records: List[BookRecord]) -> None:
        """
        Нормализовать названия серий:
        - Убрать номера выпусков в конце (Серия (1-3) → Серия)
        - Привести к стандартному capitalizations
        - Применить преобразования из config.json
        """
        for record in records:
            if not record.proposed_series:
                continue
            
            normalized = self._normalize_series_name(record.proposed_series)
            
            if normalized != record.proposed_series:
                record.proposed_series = normalized
    
    def _normalize_series_name(self, series: str) -> str:
        """Нормализовать формат названия серии."""
        
        # Шаг 1: Убрать лишние пробелы
        series = ' '.join(series.split())
        
        # Шаг 2: Убрать номер в скобках если есть
        # "Война в Космосе (1-3)" → "Война в Космосе"
        # "Странник (тетралогия)" → "Странник"
        series = re.sub(r'\s*\([^)]*\d[^)]*\)\s*$', '', series)
        
        # Шаг 3: Убрать лишние служебные слова в конце
        # "Война и Мир том 1" → "Война и Мир"
        # ВАЖНО: Использовать word boundaries \b чтобы "т" не совпадал с последней буквой слова
        service_words = self.settings.get_list('service_words')
        for word in service_words:
            # Используем \b для word boundaries - требует полного слова
            pattern = r'\s*\b' + re.escape(word) + r'\b(\s+\d+)?\s*$'
            series = re.sub(pattern, '', series, flags=re.IGNORECASE)
        
        # Шаг 4: Применить conversions из config (если настроены)
        for old_name, new_name in self.series_conversions.items():
            if series.lower() == old_name.lower():
                series = new_name
                break
        
        return series.strip()
