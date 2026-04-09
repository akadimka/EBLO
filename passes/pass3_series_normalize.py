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
    
    def __init__(self, logger: Logger = None, settings=None):
        self.logger = logger or Logger()
        self.settings = settings or SettingsManager('config.json')
        # Get series conversions from config.json if available
        try:
            # Try to access the settings directly
            self.series_conversions = self.settings.settings.get('series_conversions', {})
        except (AttributeError, KeyError):
            self.series_conversions = {}
        
        # Load cleanup patterns from config
        try:
            self.cleanup_patterns = self.settings.settings.get('series_cleanup_patterns', [])
        except (AttributeError, KeyError):
            self.cleanup_patterns = []

        # Pre-compile service-word patterns once — avoids re-compiling per record
        import re as _re
        raw_service_words = self.settings.get_list('service_words') or []
        self._service_word_patterns = [
            _re.compile(r'\s*\b' + _re.escape(w) + r'\b(\s+\d+)?\s*$', _re.IGNORECASE)
            for w in raw_service_words if w
        ]
    
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
            normalized = self._sanitize_for_folder(normalized)
            
            if normalized != record.proposed_series:
                record.proposed_series = normalized
    
    def _normalize_series_name(self, series: str) -> str:
        """Нормализовать формат названия серии."""
        
        # Шаг 1: Убрать лишние пробелы
        series = ' '.join(series.split())
        
        # Шаг 1.1: Обработать двоеточия (в т.ч. китайское «：» U+FF1A).
        # Если перед двоеточием стоит имя из 1–2 слов (напр. «Байши Сюсянь: Название»),
        # берём часть ПОСЛЕ двоеточия — это и есть реальное название серии.
        # Иначе просто убираем двоеточие (чтобы не ломать «Война: год первый»).
        for colon_char in ('：', ':'):
            if colon_char in series:
                before, after = series.split(colon_char, 1)
                before = before.strip()
                after = after.strip()
                # Считаем «before» именем-префиксом если это 1–2 слова с заглавной буквы
                _words = before.split()
                _is_name_prefix = (
                    len(_words) in (1, 2) and
                    all(w and w[0].isupper() for w in _words)
                )
                if _is_name_prefix and after:
                    series = after
                else:
                    series = series.replace(colon_char, '')
                break
        
        # Шаг 1.5: Заменить ё на е для унификации
        # "Тёмный век" → "Темный век"
        # "Чужие звёзды" → "Чужие звезды"
        # "Ёлка" → "Елка"
        series = series.replace('ё', 'е').replace('Ё', 'Е')
        
        # Шаг 1.7: Убрать суффикс-дизамбигуатор в квадратных скобках
        # "Золотой век[Иггульден]" → "Золотой век"
        # "Пастух[Кросс]" → "Пастух"
        # В названиях серий квадратные скобки всегда служат меткой автора, не частью имени.
        series = re.sub(r'\s*\[[^\]]*\]\s*$', '', series).strip()

        # Шаг 1.8: Убрать суффикс-дизамбигуатор в круглых скобках (одно слово без цифр)
        # "Дракон (Трофимов)" → "Дракон"
        # "Адмирал (Поселягин)" → "Адмирал"
        # Признак: одно слово, начинается с заглавной кириллической буквы, без цифр и пробелов.
        series = re.sub(r'\s*\([А-ЯЁA-Z][А-Яа-яёЁA-Za-z]+\)\s*$', '', series).strip()

        # Шаг 2: Убрать номер в скобках если есть
        # "Война в Космосе (1-3)" → "Война в Космосе"
        # "Странник (тетралогия)" → "Странник"
        series = re.sub(r'\s*\([^)]*\d[^)]*\)\s*$', '', series)
        
        # Шаг 3: Убрать скобки с информацией об авторстве/сотрудничестве
        # "Лорд Системы (соавтор Яростный Мики)" → "Лорд Системы"
        # "Title (with author X)" → "Title"
        for pattern in self.cleanup_patterns:
            series = re.sub(pattern, ' ', series, flags=re.IGNORECASE)
        
        # Уберем несколько пробелов если они появились после удаления скобок
        series = ' '.join(series.split())
        
        # Шаг 4: Убрать лишние служебные слова в конце
        # "Война и Мир том 1" → "Война и Мир"
        # НО: не убирать если остаток — одно слово ("Каирский цикл" → не strip, т.к. "цикл" — часть названия)
        for pat in self._service_word_patterns:
            candidate = pat.sub('', series).strip()
            if len(candidate.split()) >= 2:
                series = candidate
        
        # Шаг 5: Применить conversions из config (если настроены)
        for old_name, new_name in self.series_conversions.items():
            if series.lower() == old_name.lower():
                series = new_name
                break
        
        return series.strip()

    def _sanitize_for_folder(self, value: str) -> str:
        """Убрать символы, недопустимые в именах папок Windows/Linux, и случайные '='."""
        import re
        return re.sub(r'[/:*?<>=|]', '', value).strip()
