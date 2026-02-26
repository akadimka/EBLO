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
                    # ПРИОРИТЕТ: папка > файл > метаданные
                    
                    filename = Path(record.file_path).name
                    
                    # ШАГ 1: Попробуем использовать паттерны из конфига
                    series_from_patterns = self._extract_series_from_filename(record.file_path, validate=False)
                    
                    if series_from_patterns:
                        record.extracted_series_candidate = series_from_patterns
                        
                        # Используем то что нашли в filename
                        if self._is_valid_series(series_from_patterns):
                            record.proposed_series = series_from_patterns
                            record.series_source = "filename"
                        continue  # Обработка завершена, переходим к следующему файлу
                    
                    # ШАГ 2: Fallback - извлекаем из скобок если паттерны не сработали
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
        
        Применяет (в порядке приоритета):
        1. Паттерны из конфига (author_series_patterns_in_files)
        2. [Серия] - квадратные скобки в начале
        3. Серия (лат. буквы/цифры) - скобки в конце с сервис-словами
        4. Серия. Название - точка как разделитель в начале
        
        Args:
            file_path: Путь к файлу
            validate: Если True - проверять валидность; если False - возвращать raw candidate
        """
        filename = Path(file_path).name
        name_without_ext = filename.rsplit('.', 1)[0]
        
        # ШАГ 0: Найти ЛУЧШИЙ паттерн на основе оценки соответствия
        best_series = None
        best_score = -1
        
        if self.file_patterns:
            for pattern_obj in self.file_patterns:
                pattern_str = pattern_obj.get('pattern', '')
                series_candidate = self._apply_config_pattern(pattern_str, name_without_ext)
                
                if series_candidate:
                    # Оценить соответствие паттерна структуре файла
                    score = self._score_pattern_match(pattern_str, name_without_ext, series_candidate)
                    
                    # Если это лучший результат - запомнить
                    if score > best_score:
                        if not validate or self._is_valid_series(series_candidate):
                            best_series = series_candidate
                            best_score = score
        
        if best_series:
            # Проверка: если best_series - это serve_word, не возвращаем его
            # Serve_words это служебные слова, не названия серий
            best_series_lower = best_series.lower().strip()
            if any(best_series_lower.startswith(sw.lower()) for sw in self.service_words):
                # Это serve_word, игнорируем этот результат
                best_series = None
            else:
                return best_series
        
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
            # Ищем закрытую скобку в конце, которой предшествует открытая скобка
            match = re.search(r'\(([^)]+)\)\s*$', name_without_ext)
            if match:
                content_in_brackets = match.group(1).strip()
                # Используем логику из _extract_series_from_brackets для cleanup
                potential_series = self._extract_series_from_brackets(content_in_brackets)
                if not validate or self._is_valid_series(potential_series):
                    return potential_series
        
        # Правило 3: Серия. Название (точка как разделитель в начале)
        # Из паттернов конфига: "Series. Title" и "Author - Series.Title"
        if '. ' in name_without_ext:
            potential_series = name_without_ext.split('. ')[0].strip()
            if not validate or self._is_valid_series(potential_series):
                return potential_series
        
        return ""
    
    def _apply_config_pattern(self, pattern: str, filename: str) -> str:
        """
        Применить паттерн из конфига к имени файла и извлечь Series.
        
        Паттерны используют метаметки: (Author), (Series), (Title) и т.д.
        
        Args:
            pattern: Паттерн из конфига, напр. "Author - Series (service_words)"
            filename: Имя файла без расширения
            
        Returns:
            Извлеченное имя серии или пустая строка
        """
        # Основные шаблоны
        if pattern == "Author - Series (service_words)":
            # "Садов Сергей - Горе победителям (Дилогия)"
            # "Валериев Игорь - 2. Ермак. Поход (Ермак 4-6)"
            # Извлекаем: группу 2 (Series) - части до скобок
            match = re.match(r'^(.+?)\s*-\s*([^()]+?)\s*\(', filename)
            if match:
                series = match.group(2).strip()
                # Удаляем префикс книги: "1. ", "2. ", "3. " и т.д.
                series = re.sub(r'^\s*\d+\s*[.,]\s*', '', series).strip()
                return series
        
        elif pattern == "Author - Title (Series. service_words)":
            # "Авраменко Александр - Солдат удачи (Солдат удачи. Тетралогия)"
            # Нужно извлечь Series из скобок
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s*\(\s*([^)]+)\)', filename)
            if match:
                content_in_brackets = match.group(3).strip()
                # From "(Солдат удачи. Тетралогия)" extract "Солдат удачи"
                return self._extract_series_from_brackets(content_in_brackets)
        
        elif pattern == "Author - Series.Title":
            # "Авраменко Александр - Солдат удачи 1. Солдат удачи"
            # Извлекаем часть после " - " и до цифры/точки
            match = re.match(r'^(.+?)\s*-\s*([^0-9\(\)]+?)[\s\.\d]', filename)
            if match:
                return match.group(2).strip()
        
        elif pattern == "Author. Series. Title":
            # "Анисимов. Вариант «Бис» 2. Год мертвой змеи"
            # Формат: Author. Series. Title
            parts = filename.split('. ')
            if len(parts) >= 3:
                # parts[1] должна быть Series
                return parts[1].strip()
        
        elif pattern == "Author, Author - Title (Series. service_words)":
            # "Земляной Андрей, Орлов Борис - Академик (Странник 4-5)"
            # Извлекаем Series из скобок
            match = re.search(r'\(\s*([^)]+)\)', filename)
            if match:
                content_in_brackets = match.group(1).strip()
                return self._extract_series_from_brackets(content_in_brackets)
        
        elif pattern == "Author. Title (Series. service_words)":
            # "Демченко. Хольмградские истории (Хольмградские истории. Трилогия)"
            # Извлекаем Series из скобок
            match = re.search(r'\(\s*([^)]+)\)', filename)
            if match:
                content_in_brackets = match.group(1).strip()
                return self._extract_series_from_brackets(content_in_brackets)
        
        elif pattern == "Author - Title (Series service_words)":
            # "Валериев Игорь - 2. Ермак. Поход (Ермак 4-6)"
            # Similar to "Author - Title (Series. service_words)" but without dot
            # Content in brackets: "Ермак 4-6" (space before number)
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s*\(\s*([^)]+)\)', filename)
            if match:
                content_in_brackets = match.group(3).strip()
                return self._extract_series_from_brackets(content_in_brackets)
        
        return ""
    
    def _extract_series_from_brackets(self, content: str) -> str:
        """
        Извлечь имя серии из содержимого скобок.
        Обрабатывает:
        - "Серия. service_words" → "Серия"
        - "Серия N-M" → "Серия"
        - "Романы из цикла «Серия»" → "Серия"
        
        Args:
            content: Содержимое скобок без скобок
            
        Returns:
            Извлеченное имя серии
        """
        # Сначала попробуем паттерн "из цикла" или "из серии"
        # "Романы из цикла «Отрок»" → "Отрок"
        cycle_match = re.search(r'из\s+(?:цикла|серии)\s+(.+)', content, re.IGNORECASE)
        if cycle_match:
            series_candidate = cycle_match.group(1).strip()
            # Удаляем внешние кавычки
            open_count = series_candidate.count('«')
            close_count = series_candidate.count('»')
            
            if (open_count > 0 and open_count == close_count and 
                series_candidate.startswith('«') and series_candidate.endswith('»')):
                series_candidate = series_candidate[1:-1]
            elif open_count > close_count and series_candidate.startswith('«'):
                series_candidate = series_candidate[1:]
                
            return series_candidate.strip()
        
        # Если есть точка - берем до неё (это Series. service_words)
        if '. ' in content:
            parts = content.split('. ')
            after_dot = parts[1].lower() if len(parts) > 1 else ''
            
            # Проверка служебных слов
            is_service_word = any(
                after_dot.startswith(sw.lower()) 
                for sw in ['том', 'дилогия', 'трилогия', 'тетралогия', 'пенталогия', 'роман-эпопея']
            )
            
            if is_service_word:
                return parts[0].strip()
        
        # Если есть числовой диапазон (1-3, 4-6), берем до него
        series_candidate = re.sub(r'\s*[\d\-]+\s*$', '', content).strip()
        
        return series_candidate if series_candidate else ""
    
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
    
    def _score_pattern_match(self, pattern: str, filename: str, extracted_series: str) -> int:
        """
        Оценить степень соответствия паттерна структуре файла.
        Выбирает ЛУЧШИЙ паттерн из нескольких кандидатов.
        
        Критерии оценки:
        1. Специфичность паттерна (более специфичные выше)
        2. Совпадение структурных элементов с файлом
        3. Качество результата (количество слов в серии)
        
        Args:
            pattern: Паттерн из конфига
            filename: Имя файла без расширения
            extracted_series: Извлеченная серия
            
        Returns:
            Оценка (чем выше, тем лучше совпадение). -1 = нет результата.
        """
        if not extracted_series:
            return -1
        
        score = 0
        
        # УРОВЕНЬ 1: Специфичность паттерна (более специфичные = более надежные)
        # Паттерны со скобками и serve_words очень специфичные
        if 'service_words' in pattern:
            score += 20  # Наивысший приоритет - это точный паттерн
        
        # Паттерны со скобками хорошие
        if '(' in pattern and ')' in pattern:
            score += 10
        
        # Паттерны с тире
        if ' - ' in pattern:
            score += 5
        
        # Паттерны с точкой
        if '. ' in pattern:
            score += 3
        
        # УРОВЕНЬ 2: Совпадение структуры файла с паттерном структурой
        # Если в файле есть то же что в паттерне - это хороший знак
        if ' - ' in pattern and ' - ' in filename:
            score += 8
        
        if '(' in pattern and '(' in filename and ')' in filename:
            score += 8
        
        if '. ' in pattern and '. ' in filename:
            score += 4
        
        # УРОВЕНЬ 3: Качество результата
        word_count = len(extracted_series.split())
        if word_count > 1:
            score += word_count * 2  # Мультисловные результаты ценятся выше
        elif word_count == 0:
            score -= 30  # Пустой результат = плохо
        
        # Штраф за слишком короткие результаты из многомерных паттернов
        if word_count == 1 and ' - ' in pattern and ' - ' in filename and len(filename) > 30:
            score -= 3  # Вероятно мы неправильно разпарсили
        
        # УРОВЕНЬ 4: КРИТИЧНО - если результат сам является служебным словом
        # Это ловушка: паттерн может извлечь "Тетралогия" вместо реальной серии
        # Нужно отдавать предпочтение результатам, которые НЕ serve_words
        extracted_lower = extracted_series.lower().strip()
        if any(extracted_lower.startswith(sw.lower()) for sw in self.service_words):
            # БОЛЬШОЙ штраф - это служебное слово, не серия!
            score = max(0, score - 50)
        
        # УРОВЕНЬ 5: Штраф за single-word результаты
        # Single-word результаты из сложных паттернов = вероятно Title, не Series
        # Например: "Охотник" из файла "Янковский - Охотник (Тетралогия)"
        
        return max(0, score)  # Минимум 0
