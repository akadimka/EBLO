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
        self.filename_blacklist = self.settings.get_list('filename_blacklist')
        
        # Получить паттерны из конфига
        self.file_patterns = self.settings.get_list('author_series_patterns_in_files') or []
    
    def execute(self, records: List[BookRecord]) -> None:
        """
        Попытаться извлечь серию из имена файла.
        
        ОГРАНИЧЕНИЕ: Парсит series только для файлов в подпапках автора (Author/Series/File).
        Для файлов прямо в папке автора (Author/File) используется ТОЛЬКО metadata_series.
        
        Логика приоритета:
        1. Если глубина < 3 (Author/File) → использовать ТОЛЬКО metadata_series 
        2. Если глубина >= 3 (Author/Series/File) → парсить файл + сравнивать с metadata
        3. Если в файле найдено совпадает с началом metadata → берем metadata целиком
        4. Fallback на metadata_series если в имени не найдено
        """
        for record in records:
            # Пропускаем если серия уже установлена из папок
            if record.series_source == "folder_dataset":
                continue
            
            # Пропускаем если уже есть валидная серия
            if record.proposed_series:
                continue
            
            # Проверяем глубину файла в структуре папок
            file_path_parts = Path(record.file_path).parts
            file_depth = len(file_path_parts)
            
            # Если файл прямо в папке автора (глубина 2) - используем ТОЛЬКО metadata временно
            # Но извлекаем candidate из filename для consensus в PASS 4
            if file_depth == 2:
                filename = Path(record.file_path).name
                name_without_ext = filename.rsplit('.', 1)[0]
                
                # Для depth 2 файлов типа "Author. Series/Title/Series NN. Title"
                # Извлекаемый паттерн: вторая часть после первой точки может быть серией
                # Примеры:
                # "Сойер. Неандертальский параллакс (сборник)" -> "Неандертальский параллакс (сборник)"
                # "Сойер. Неандертальский параллакс 01. Гоминиды" -> "Неандертальский параллакс"
                # "Сойер. Ката Бинду" -> "Ката Бинду"
                
                if '. ' in name_without_ext:
                    parts = name_without_ext.split('. ')
                    # parts[0] = Author, rest = title/series parts
                    remaining = '. '.join(parts[1:])  # "Неандертальский параллакс (сборник)" или "Неандертальский параллакс 01. Гоминиды"
                    
                    # Если есть число и точка, это обычно начало номера в серии
                    # Тогда берём всё до первого номера как имя серии
                    match_num = re.search(r'^([^0-9]+?)\s*\d+\s*\.', remaining)
                    if match_num:
                        # Найдена нумерация: "Неандертальский параллакс 01. Гоминиды" -> "Неандертальский параллакс"
                        series_candidate = match_num.group(1).strip()
                    else:
                        # Нет нумерации, но есть скобки в конце - берём всё до скобок
                        # "Неандертальский параллакс (сборник)" -> "Неандертальский параллакс"
                        series_match = re.match(r'^([^\(]+?)\s*\(', remaining)
                        if series_match:
                            series_candidate = series_match.group(1).strip()
                        else:
                            # Просто заголовок без нумерации и скобок
                            # Не очень надёжно, поэтому не берём
                            series_candidate = None
                    
                    if series_candidate:
                        record.extracted_series_candidate = series_candidate
                
                if record.metadata_series:
                    series = record.metadata_series.strip()
                    if self._is_valid_series(series):
                        record.proposed_series = series
                        record.series_source = "metadata"
                continue
            
            # Если файл в подпапке (глубина >= 3) - парсим имя файла
            # ШАГ 1: Попытаться извлечь из имени файла
            series_candidate = self._extract_series_from_filename(record.file_path, validate=False)
            
            # ВСЕГДА сохранять candidate (даже если он не валиден) для PASS 4 consensus
            if series_candidate:
                record.extracted_series_candidate = series_candidate
            
            # ШАГ 2: Проверить валидность и применить
            if series_candidate:
                # Проверим валидность
                if not self._is_valid_series(series_candidate):
                    # Candidate заблочен по BL, но оставляем его для consensus
                    # Используем только metadata если есть
                    if record.metadata_series:
                        series = record.metadata_series.strip()
                        if self._is_valid_series(series):
                            record.proposed_series = series
                            record.series_source = "metadata"
                else:
                    # Candidate валиден, применяем его
                    # ШАГ 3: Проверить совпадает ли с metadata
                    if record.metadata_series and record.metadata_series.strip():
                        metadata_series = record.metadata_series.strip()
                        # Если найденное в файле - это начало metadata, берем metadata целиком (может быть более полной)
                        if metadata_series.lower().startswith(series_candidate.lower()):
                            # Предпочитаем metadata версию (более полная)
                            record.proposed_series = metadata_series
                            record.series_source = "metadata"
                        else:
                            # Они не совпадают, берем то что нашли в файле
                            record.proposed_series = series_candidate
                            record.series_source = "filename"
                    else:
                        # Нет metadata, берем то что нашли в файле
                        record.proposed_series = series_candidate
                        record.series_source = "filename"
            elif record.metadata_series:
                # FALLBACK: Используем metadata_series если в имени файла не найдено
                series = record.metadata_series.strip()
                if self._is_valid_series(series):
                    record.proposed_series = series
                    record.series_source = "metadata"
    
    def _extract_series_from_filename(self, file_path: str, validate: bool = True) -> str:
        """
        Извлечь серию из имени файла, используя паттерны из конфига.
        
        Применяет следующие правила (в порядке приоритета):
        1. [Серия] - квадратные скобки в начале
        2. Серия (лат. буквы/цифры) - скобки в конце с сервис-словами
        3. Серия. Название - точка как разделитель в начале
        
        Args:
            file_path: Путь к файлу
            validate: Если True - проверять валидность; если False - возвращать raw candidate
        """
        filename = Path(file_path).name
        name_without_ext = filename.rsplit('.', 1)[0]
        
        # Правило 1: [Серия] в квадратных скобках в начале
        # Из паттернов конфига ищем примеры с [...]
        match = re.search(r'^\[([^\[\]]+)\]', name_without_ext)
        if match:
            series = match.group(1).strip()
            if not validate or self._is_valid_series(series):
                return series
        
        # Правило 2: Серия в скобках в КОНЦЕ 
        # Из паттернов конфига: "Author - Title (Series. service_words)"
        # Ищем скобку в конце, может быть с сервис-словами перед ней
        if '(' in name_without_ext and ')' in name_without_ext:
            # Сначала ищем простую скобку в конце
            match = re.search(r'\(?([^)]+)\)\s*$', name_without_ext)
            if match:
                potential_series = match.group(1).strip()
                if not validate or self._is_valid_series(potential_series):
                    return potential_series
        
        # Правило 3: Серия. Название (точка как разделитель в начале)
        # Из паттернов конфига: "Series. Title" и "Author - Series.Title"
        if '. ' in name_without_ext:
            potential_series = name_without_ext.split('. ')[0].strip()
            if not validate or self._is_valid_series(potential_series):
                return potential_series
        
        return ""
    
    def _is_valid_series(self, text: str) -> bool:
        """
        Проверить что text выглядит как название серии, не как другое.
        Проверяет против:
        - filename_blacklist (список запрещенных слов)
        - collection_keywords (сборники, антологии)
        - service_words (том, книга, выпуск)
        - AuthorName (не похоже на имя автора)
        """
        if not text or len(text) < 2:
            return False
        
        text_lower = text.lower()
        
        # ПРОВЕРКА 1: filename_blacklist - запрещенные слова
        for bl_word in self.filename_blacklist:
            if bl_word.lower() in text_lower:
                return False
        
        # ПРОВЕРКА 2: Исключить очевидные сборники/антологии
        for keyword in self.collection_keywords:
            if keyword.lower() in text_lower:
                return False
        
        # ПРОВЕРКА 3: Исключить сервис-слова (том, книга, выпуск)
        for service_word in self.service_words:
            if text_lower.startswith(service_word.lower()):
                return False
        
        # ПРОВЕРКА 4: Убедиться что это НЕ похоже на автора!
        try:
            author = AuthorName(text, [])
            if author.is_valid_author():
                return False  # Это похоже на автора, отвергаем как серию
        except Exception:
            pass  # Если парсинг не сработал - это вероятно серия
        
        return True
