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
            
            # Если файл находится на глубине 2: может быть либо Автор/file.fb2, либо SeriesFolder/file.fb2
            # Нужно отличить их по имени папки
            if file_depth == 2:
                parent_folder = file_path_parts[0]  # Первая папка в пути
                
                # Проверить - это папка серии коллекции (т.е. напрямую Series folder без Author subfolder)
                # Такие папки обычно начинаются со слов: "Серия", "Series", "Collection", "Сборник"
                # Или содержат слово в скобках, как "Серия - «Name»"
                is_series_folder = (
                    parent_folder.startswith('Серия') or
                    parent_folder.startswith('Series') or
                    parent_folder.startswith('Collection') or
                    parent_folder.startswith('Сборник') or
                    'Серия' in parent_folder or
                    'Collection' in parent_folder
                )
                
                if is_series_folder:
                    # Это файл в папке-коллекции серий, обрабатываем как depth 1 файл
                    filename = Path(record.file_path).name
                    name_without_ext = filename.rsplit('.', 1)[0]
                    
                    # Ищем скобки - сначала попробуем найти в конце (основной случай)
                    # "Авраменко Александр - Солдат удачи (Солдат удачи. Тетралогия)"
                    # Но также поддерживаем структуру с информацией после скобок
                    # "Проект «Оборотень» (Странник. Пенталогия) - 2010"
                    series_match = re.search(r'\(([^)]+)\)', name_without_ext)
                    if series_match:
                        content_in_brackets = series_match.group(1).strip()
                        
                        # Если в скобках есть слово в конце (типов/дилогия/коллекция)
                        # "Сборник" и подобное - нужно пропустить
                        content_lower = content_in_brackets.lower()
                        skip_keywords = ['сборник', 'сборник', 'авторский', 'собрание', 'антология']
                        if any(kw in content_lower for kw in skip_keywords):
                            # Это сборник, не серия - пропускаем
                            pass
                        else:
                            # Извлекаем series из скобок
                            # "Солдат удачи. Тетралогия" → "Солдат удачи"
                            # "Странник. Пенталогия" → "Странник"
                            # "Страна Арманьяк 1-3" → "Страна Арманьяк"
                            # "Романы + из цикла «Отрок»" → "Отрок"
                            # "Отрок 2. Сотник 1-3" → "Отрок"
                            
                            series_candidate = content_in_brackets.strip()
                            
                            # Сначала проверяем паттерн "из цикла" или "из серии"
                            # "Романы + из цикла «Отрок»" → "Отрок"
                            # "Романы из цикла «Ведьма с Летающей ведьмы»" → "Ведьма с Летающей ведьмы"
                            cycle_match = re.search(r'из\s+(?:цикла|серии)\s+(.+)', content_in_brackets, re.IGNORECASE)
                            if cycle_match:
                                series_candidate = cycle_match.group(1).strip()
                                # Удаляем внешние кавычки в зависимости от структуры
                                # "«Отрок»" → "Отрок" (1 « и 1 »)
                                # "«Ведьма с «Летающей ведьмы»»" → "Ведьма с «Летающей ведьмы»" (2 « и 2 »)  
                                # "«Ведьма с «Летающей ведьмы»" → "Ведьма с «Летающей ведьмы»" (2 « и 1 », первая « это внешняя)
                                open_count = series_candidate.count('«')
                                close_count = series_candidate.count('»')
                                
                                # Если количество кавычек совпадает - удаляем первую и последнюю как парн
                                if (open_count > 0 and open_count == close_count and 
                                    series_candidate.startswith('«') and series_candidate.endswith('»')):
                                    series_candidate = series_candidate[1:-1]
                                # Если открывающих больше чем закрывающих, но первый символ - открывающая
                                # это значит первая « это внешняя, остальные внутренние
                                elif open_count > close_count and series_candidate.startswith('«'):
                                    series_candidate = series_candidate[1:]
                                    
                                series_candidate = series_candidate.strip()
                            # Иначе пытаемся извлечь по точке - но ТОЛЬКО если после точки идет служебное слово
                            # "Солдат удачи. Тетралогия" → "Солдат удачи"
                            # "Отрок 2. Сотник 1-3" → сохраняем как есть (это иерархия серий)
                            elif '. ' in content_in_brackets:
                                parts = content_in_brackets.split('. ')
                                after_dot = parts[1].lower() if len(parts) > 1 else ''
                                # Проверяем, является ли часть после точки служебным словом
                                is_service_word_after_dot = any(
                                    after_dot.startswith(sw.lower()) 
                                    for sw in ['том', 'дилогия', 'трилогия', 'тетралогия', 'пенталогия', 'роман-эпопея']
                                )
                                if is_service_word_after_dot:
                                    # Это служебное слово - берем только первую часть
                                    series_candidate = parts[0].strip()
                                # иначе оставляем всю строку (иерархия: "Отрок 2. Сотник")
                            
                            # Удаляем номер тома в начале: "Отрок 2." или "2. "
                            # Паттерн: "Серия NN." или "Серия NN " в начале
                            series_candidate = re.sub(r'^\s*\d+\s*[.,]?\s*', '', series_candidate).strip()
                            
                            # Удаляем числовые суффиксы (номера томов в конце)
                            # Паттерны: "1-3", "1-6", "01, 02", "№1" и т.д.
                            # ВАЖНО: не удаляем точки, т.к. они разделяют серии ("Отрок 2. Сотник 1-3" → "Отрок 2. Сотник")
                            series_candidate = re.sub(r'\s*[\d\-,•]+\s*$', '', series_candidate).strip()
                            # Удаляем оставшиеся служебные слова в конце (т, т., том и т.д.)
                            for service_word in self.service_words:
                                pattern = r'\s*' + re.escape(service_word.lower()) + r'\s*$'
                                series_candidate = re.sub(pattern, '', series_candidate, flags=re.IGNORECASE).strip()
                            
                            if series_candidate:
                                record.extracted_series_candidate = series_candidate
                                # Для файлов в series коллекции - используем extracted candidate как proposed series
                                if self._is_valid_series(series_candidate):
                                    record.proposed_series = series_candidate
                                    record.series_source = "filename"
                    
                    # Если из filename ничего не нашли, но есть metadata - используем её
                    if not record.proposed_series and record.metadata_series:
                        series = record.metadata_series.strip()
                        if self._is_valid_series(series):
                            record.proposed_series = series
                            record.series_source = "metadata"
                    continue
            
            # Если файл находится на глубине 2 и это папка автора (не папка серии коллекции) - используем ТОЛЬКО metadata
            # Или на остальные случаи depth==2
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
        # Но только если они в начале как отдельное слово, не как часть названия!
        # "том 1" → исключить, "Томск" → сохранить
        for service_word in self.service_words:
            service_word_lower = service_word.lower()
            # Проверяем если service_word это одна буква - только если это слово целиком
            if len(service_word_lower) == 1:
                # Для однобуквенных сокращений требуем точку после них: "т. " или "т."
                if text_lower.startswith(service_word_lower + ' ') or \
                   text_lower.startswith(service_word_lower + '.'):
                    return False
            else:
                # Для многобуквенных слов проверяем начало строки
                if text_lower.startswith(service_word_lower + ' ') or \
                   text_lower.startswith(service_word_lower):
                    # Но требуем чтобы это было целое слово в начале
                    # "том фантастика" → исключить, но "томск" → сохранить
                    words = text_lower.split()
                    if words and words[0] == service_word_lower:
                        return False
        
        # ПРОВЕРКА 4: Убедиться что это НЕ похоже на автора!
        try:
            author = AuthorName(text, [])
            if author.is_valid_author():
                return False  # Это похоже на автора, отвергаем как серию
        except Exception:
            pass  # Если парсинг не сработал - это вероятно серия
        
        return True
