"""
PASS 2 для СЕРИЙ: Извлечение серий из имён файлов.
Аналог pass2_filename.py (для авторов) но специализирован на СЕРИИ.

Обновление: Добавлена УНИФИКАЦИЯ series_source
================================================================
Для файлов одного автора с одинаковой серией но разными sources
(например: File 1-2 с source="metadata", File 3 с source="filename"):
1. Все такие файлы группируются в _apply_cross_file_consensus()
2. Source унифицируется с приоритетом: "filename" > "metadata" > "consensus"
3. Результат: ВСЕ файлы одного автора с одной серией имеют ОДИНАКОВЫЙ source

Пример решения (Бродяга - Аскеров):
  БЫЛО:
    File 1: series_source="metadata"
    File 2: series_source="metadata"  
    File 3: series_source="filename"
  
  СТАЛО:
    File 1: series_source="filename" ✅
    File 2: series_source="filename" ✅
    File 3: series_source="filename" ✅
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
                        
                        # ПРОВЕРКА 1: Не используем запятую - это признак списка авторов
                        # "Демидова, Конторович" → это авторы, не серия!
                        if ',' in series_from_patterns:
                            # Это список авторов, не серия - пропускаем и используем только metadata
                            if record.metadata_series:
                                series = record.metadata_series.strip()
                                if self._is_valid_series(series):
                                    record.proposed_series = series
                                    record.series_source = "metadata"
                            continue  # Переходим к следующему файлу
                        
                        # ПРОВЕРКА 2: Не используем фамилию автора как серию
                        if self._is_author_surname(series_from_patterns, record.proposed_author):
                            # Это фамилия, не серия - пропускаем и используем только metadata
                            if record.metadata_series:
                                series = record.metadata_series.strip()
                                if self._is_valid_series(series):
                                    record.proposed_series = series
                                    record.series_source = "metadata"
                            continue  # Переходим к следующему файлу
                        
                        # Применяем очистку и metadata валидирование
                        clean_candidate = self._clean_series_name(series_from_patterns)
                        
                        # Проверим валидность очищенной версии
                        if not self._is_valid_series(clean_candidate):
                            # Candidate заблочен - используем metadata если есть
                            if record.metadata_series:
                                series = record.metadata_series.strip()
                                if self._is_valid_series(series):
                                    record.proposed_series = series
                                    record.series_source = "metadata"  # Метаданные как основной источник
                        else:
                            # Clean candidate валиден - сравниваем с metadata
                            if record.metadata_series and record.metadata_series.strip():
                                metadata_series = record.metadata_series.strip()
                                
                                # СРАВНИВАЕМ ОЧИЩЕННУЮ версию кандидата с metadata
                                if clean_candidate.lower() == metadata_series.lower():
                                    # Точное совпадение - используем metadata значение, но source = filename
                                    record.proposed_series = metadata_series
                                    record.series_source = "filename"  # Источник - filename (мета только уточнила)
                                
                                elif metadata_series.lower().startswith(clean_candidate.lower()):
                                    # Metadata это расширение clean_candidate
                                    # "Туман" в файле, а в metadata "Туман (Борисов)" - это диспамбiguация, не расширение
                                    # "Солдат удачи" в файле, а в metadata "Солдат удачи. Цикл" - это расширение
                                    
                                    # Проверяем: если metadata = "clean_candidate (something)" это просто диспамбiguация
                                    metadata_after_clean = metadata_series[len(clean_candidate):].strip()
                                    if metadata_after_clean.startswith('(') and metadata_after_clean.endswith(')'):
                                        # Это просто скобки с диспамбiguацией, используем clean_candidate из filename
                                        record.proposed_series = clean_candidate
                                        record.series_source = "filename"
                                    else:
                                        # Это реальное расширение (точка, дополнительные слова)
                                        record.proposed_series = metadata_series
                                        record.series_source = "filename"  # Источник filename (мета расширила)
                                
                                elif clean_candidate.lower().startswith(metadata_series.lower()):
                                    # Clean candidate это расширение metadata
                                    # Используем metadata как более чистый источник
                                    record.proposed_series = metadata_series
                                    record.series_source = "filename"  # Все равно из filename берем основу
                                
                                elif self._matches_with_tolerance(clean_candidate, metadata_series, tolerance=0.80):
                                    # Существенное совпадение с tolerance
                                    record.proposed_series = metadata_series
                                    record.series_source = "filename"  # Источник filename (мета подтвердила)
                                
                                else:
                                    # Они не совпадают - используем очищенную версию из filename
                                    record.proposed_series = clean_candidate
                                    record.series_source = "filename"
                            else:
                                # Нет metadata - используем clean candidate из filename
                                if self._is_valid_series(series_from_patterns):
                                    record.proposed_series = series_from_patterns
                                    record.series_source = "filename"
                        
                        continue  # Обработка завершена, переходим к следующему файлу
                    
                    # ШАГ 2: Fallback - extractжем из скобок если паттерны не сработали
                    name_without_ext = filename.rsplit('.', 1)[0]
                    
                    # ПРИ ОРИТЕТ: сначала пытаемся извлечь серию перед скобками
                    # "Бродяга (СИ)" → пытаемся извлечь "Бродяга"
                    # "Бродяга 2. Звёздные закоулки (СИ)" → пытаемся извлечь "Бродяга"
                    name_before_brackets = re.sub(r'\s*\([^)]*\)\s*$', '', name_without_ext).strip()
                    
                    # Пытаемся применить паттерны к имени ДО скобок
                    # (это может помочь extract "Бродяга" из "Аскеров - Бродяга (СИ)")
                    series_from_before = self._extract_series_from_filename(name_before_brackets, validate=False)
                    if series_from_before:
                        record.extracted_series_candidate = series_from_before
                        series_candidate = series_from_before
                    else:
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
                    
                    # ШАГ 1.5: Если скобок нет, попробуем config patterns из filename
                    # Это поддерживает "Author - Series.Title" формат
                    if not record.proposed_series:
                        filename = Path(record.file_path).name
                        series_candidate = self._extract_series_from_filename(record.file_path, validate=False)
                        if series_candidate:
                            record.extracted_series_candidate = series_candidate
                            clean_candidate = self._clean_series_name(series_candidate)
                            if self._is_valid_series(clean_candidate):
                                record.proposed_series = clean_candidate
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
                
                # ШАГ 1: Попробуем извлечь серию используя новые правила
                series_candidate = self._extract_series_from_filename(record.file_path, validate=False)
                if series_candidate:
                    record.extracted_series_candidate = series_candidate
                    
                    # ПРОВЕРКА: Не используем фамилию автора как серию
                    # Пример: "Белоус. Последний шанс" → "Белоус" это фамилия, не серия
                    if not self._is_author_surname(series_candidate, record.proposed_author):
                        clean_candidate = self._clean_series_name(series_candidate)
                        if self._is_valid_series(clean_candidate):
                            record.proposed_series = clean_candidate
                            record.series_source = "filename"
                            continue  # Нашли из filename - не переписываем с metadata
                
                # ШАГ 2: Fallback - для depth 2 файлов типа "Author. Series/Title" (формат с точками)
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
                        
                        # ПРОВЕРКА 1: Не используем запятую - это признак списка авторов
                        # "Демидова, Конторович" → это авторы, не серия!
                        if ',' in series_candidate:
                            # Это список авторов, не серия - не берем
                            series_candidate = None
                        # ПРОВЕРКА 2: Не используем фамилию автора как серию
                        # Пример: "Белоус. Последний шанс" → "Белоус" это фамилия, не серия
                        elif not self._is_author_surname(series_candidate, record.proposed_author):
                            if self._is_valid_series(series_candidate):
                                record.proposed_series = series_candidate
                                record.series_source = "filename"
                
                # ШАГ 3: Финальный fallback - используем metadata если есть
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
                # СРАЗУ очистим от паразитных символов (томы, названия)
                clean_candidate = self._clean_series_name(series_candidate)
                
                # Проверим валидность (очищенной версии)
                if not self._is_valid_series(clean_candidate):
                    # Candidate заблочен по BL, но оставляем его для consensus
                    # Используем только metadata если есть
                    if record.metadata_series:
                        series = record.metadata_series.strip()
                        if self._is_valid_series(series):
                            record.proposed_series = series
                            record.series_source = "metadata"  # Метаданные как основной источник
                else:
                    # Candidate (очищенный) валиден, применяем его
                    # ШАГ 3: Проверить совпадает ли с metadata
                    if record.metadata_series and record.metadata_series.strip():
                        metadata_series = record.metadata_series.strip()
                        
                        # СРАВНИВАЕМ ОЧИЩЕННУЮ версию кандидата с metadata
                        if clean_candidate.lower() == metadata_series.lower():
                            # Точное совпадение - используем metadata значение, но source = filename
                            record.proposed_series = metadata_series
                            record.series_source = "filename"  # Источник - filename (мета только уточнила)
                        
                        elif metadata_series.lower().startswith(clean_candidate.lower()):
                            # Metadata это расширение cleaned_candidate
                            # "Туман" в файле, а в metadata "Туман (Борисов)" - это НЕ расширение, это диспамбiguация
                            # "Солдат удачи" в файле, а в metadata "Солдат удачи. Цикл" - это расширение
                            
                            # Проверяем: если metadata = "clean_candidate (something)" это просто диспамбiguация
                            metadata_after_clean = metadata_series[len(clean_candidate):].strip()
                            if metadata_after_clean.startswith('(') and metadata_after_clean.endswith(')'):
                                # Это просто скобки с диспамбiguацией, используем clean_candidate
                                record.proposed_series = clean_candidate
                                record.series_source = "filename"
                            else:
                                # Это реальное расширение (точка, дополнительные слова)
                                record.proposed_series = metadata_series
                                record.series_source = "filename"  # Источник filename (мета расширила)
                        
                        elif clean_candidate.lower().startswith(metadata_series.lower()):
                            # Clean_candidate это расширение metadata
                            # Используем metadata как более чистый источник
                            record.proposed_series = metadata_series
                            record.series_source = "filename"  # Все равно из filename берем основу
                        
                        elif self._matches_with_tolerance(clean_candidate, metadata_series, tolerance=0.80):
                            # Существенное совпадение с tolerance
                            # Используем metadata как более надежный источник
                            record.proposed_series = metadata_series
                            record.series_source = "filename"  # Источник filename (мета подтвердила)
                        
                        else:
                            # Они не совпадают даже после очистки и tolerance-check
                            # Используем очищенную версию extracted
                            record.proposed_series = clean_candidate
                            record.series_source = "filename"
                    else:
                        # Нет metadata, берем очищенную версию
                        record.proposed_series = clean_candidate
                        record.series_source = "filename"
            elif record.metadata_series:
                # FALLBACK: Используем metadata_series если в имени файла не найдено
                series = record.metadata_series.strip()
                if self._is_valid_series(series):
                    record.proposed_series = series
                    record.series_source = "metadata"
        
        # ШАГ ФИНАЛЬНЫЙ: Кросс-файловый анализ - находим общие серии между файлами автора
        self._apply_cross_file_consensus(records)
    
    def _apply_cross_file_consensus(self, records: List[BookRecord]) -> None:
        """
        Найти общие последовательности слов в серияхмежду несколькими файлами одного автора.
        
        Логика:
        1. Группируем файлы по автору
        2. Для каждого автора анализируем все его файлы
        3. Находим общие последовательности слов в extracted_series_candidate и metadata_series
        4. Если найдена достаточно очевидная общая серия - применяем её
        5. УНИФИКАЦИЯ: Если несколько файлов одного автора имеют одинаковую серию 
           но с разными series_source - установим для всех одинаковый источник (filename приоритетнее)
        """
        from collections import Counter
        
        # Группируем по автору
        authors_records = {}
        for record in records:
            author = record.proposed_author
            if not author:
                continue
            if author not in authors_records:
                authors_records[author] = []
            authors_records[author].append(record)
        
        # Для каждого автора анализируем его файлы
        for author, author_files in authors_records.items():
            # Пропускаем если у автора только 1 файл
            if len(author_files) < 2:
                continue
            
            # Собираем все кандидаты серий для этого автора
            all_candidates = []
            
            for record in author_files:
                extracted = record.extracted_series_candidate
                metadata = record.metadata_series
                
                # Пропускаем если ничего нет
                if not extracted and not metadata:
                    continue
                
                # Очистим extracted от паразитных символов
                extracted_clean = self._clean_series_name(extracted) if extracted else ""
                
                all_candidates.append({
                    'record': record,
                    'extracted': extracted,
                    'extracted_clean': extracted_clean,
                    'metadata': metadata
                })
            
            # Если есть хотя бы 2 кандидата - анализируем общее
            if len(all_candidates) < 2:
                continue
            
            # АНАЛИЗ: Найти общие последовательности слов
            common_words = self._find_common_series_across_files(all_candidates)
            
            if common_words:
                # Применить найденную общую серию к файлам где её нет
                for candidate in all_candidates:
                    record = candidate['record']
                    
                    # Если у файла уже есть series - не переписываем
                    if record.proposed_series:
                        continue
                    
                    # Если найденные слова совпадают с metadata - применяем
                    if candidate['metadata'] and self._matches_with_tolerance(common_words, candidate['metadata'], tolerance=0.80):
                        record.proposed_series = candidate['metadata']
                        record.series_source = "metadata"
                    # Иначе применяем найденные слова
                    elif common_words:
                        record.proposed_series = common_words
                        record.series_source = "consensus"
            
            # ШАГ УНИФИКАЦИИ: Если несколько файлов имеют одинаковую series - унифицировать series_source
            # Группируем файлы по series
            series_groups = {}
            for record in author_files:
                if not record.proposed_series:
                    continue
                
                # Нормализуем серию для группировки (нижний регистр, без пунктуации)
                series_normalized = re.sub(r'[^\w\s]', '', record.proposed_series).lower().strip()
                
                if series_normalized not in series_groups:
                    series_groups[series_normalized] = {
                        'records': [],
                        'sources': [],
                        'original_series': record.proposed_series
                    }
                
                series_groups[series_normalized]['records'].append(record)
                if record.series_source:
                    series_groups[series_normalized]['sources'].append(record.series_source)
            
            # Для каждой группы серий - если есть конфликт source, унифицируем
            for normalized_series, group_info in series_groups.items():
                if len(group_info['records']) < 2:
                    continue
                
                # Проверяем если есть конфликт источников
                unique_sources = set(group_info['sources'])
                if len(unique_sources) > 1:
                    # Есть конфликт! Унифицируем
                    # ПРИОРИТЕТ: "filename" > "metadata" > "consensus"
                    if "filename" in unique_sources:
                        best_source = "filename"
                    elif "metadata" in unique_sources:
                        best_source = "metadata"
                    else:
                        best_source = "consensus"
                    
                    # Установим best_source для всех файлов этой серии
                    for record in group_info['records']:
                        if record.series_source in unique_sources:
                            # Если он имел другой source - обновляем
                            record.series_source = best_source
    
    def _find_common_series_across_files(self, candidates: list) -> str:
        """
        Найти общую последовательность слов в series кандидатах для нескольких файлов.
        Возвращает строку с найденной общей серией, или пустую строку.
        """
        from collections import Counter
        
        # Собираем все кандидаты (и из extracted, и из metadata)
        all_series_strings = []
        
        for candidate in candidates:
            if candidate['extracted_clean']:
                all_series_strings.append(candidate['extracted_clean'])
            if candidate['metadata']:
                all_series_strings.append(candidate['metadata'])
        
        if not all_series_strings:
            return ""
        
        # Нормализуем для сравнения (нижний регистр, без пунктуации)
        normalized_strings = []
        original_to_normalized = {}  # Маппинг нормализованного на оригинальный
        
        for s in all_series_strings:
            norm = re.sub(r'[^\w\s]', '', s).lower().strip()
            normalized_strings.append(norm)
            if norm not in original_to_normalized:
                original_to_normalized[norm] = s
        
        # Считаем что встречалось > 1 раза
        counter = Counter(normalized_strings)
        most_common = counter.most_common(1)
        
        if most_common:
            norm_series, count = most_common[0]
            # Если встречалось > 1 раза - это наша серия
            if count > 1:
                # Возвращаем оригинальную версию (не нормализованную)
                return original_to_normalized[norm_series]
        
        return ""
    
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
            # ВАЖНО: сравниваем целое слово, не префикс!
            best_series_lower = best_series.lower().strip()
            is_service_word = False
            for sw in self.service_words:
                sw_lower = sw.lower()
                if best_series_lower == sw_lower or best_series_lower.startswith(sw_lower + ' '):
                    is_service_word = True
                    break
            
            if is_service_word:
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
        # ВАЖНО: Не захватываем простые слова (обычно фамилии) перед точкой
        # "Белoус. Последний шанс" - "Белоус" это фамилия, не серия!
        # И не захватываем "Author - Series" паттерны - они обработаны config pattern
        # "Борисов Олег - Туман 1. Золото" должен дать "Туман", не "Борисов Олег - Туман"
        if '. ' in name_without_ext:
            potential_series = name_without_ext.split('. ')[0].strip()
            
            # Если содержит " - ", это скорее всего "Author - Series" паттерн
            # Нужно пропустить и дать обработаться config pattern
            if ' - ' in potential_series:
                pass  # Skip: let config pattern handle "Author - Series.Title"
            # Если это просто одно слово без пробелов и без  специальных символов
            # то это скорее всего фамилия автора, а не название серии
            elif ' ' not in potential_series and len(potential_series) < 50:
                # Single word - likely an author surname, skip it
                # Series names usually have multiple words или специальные символы
                pass
            elif not validate or self._is_valid_series(potential_series):
                return potential_series
        
        # Правило 4: Author - Series N (без точки после номера)
        # "Атаманов Михаил - Задача выжить 1" → "Задача выжить"
        # Паттерн: Author - Серия N где N это одна или две цифры в конце
        if ' - ' in name_without_ext:
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s+\d{1,2}\s*$', name_without_ext)
            if match:
                potential_series = match.group(2).strip()
                # Убедимся что это не автор (не похоже на имя)
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
            # "Авраменко Александр - Солдат удачи 3. Взор Тьмы (Наследник)"
            # Извлекаем: группу 2 (Series) - части до скобок
            match = re.match(r'^(.+?)\s*-\s*([^()]+?)\s*\(', filename)
            if match:
                series = match.group(2).strip()
                # Удаляем префикс книги: "1. ", "2. ", "3. " и т.д.
                series = re.sub(r'^\s*\d+\s*[.,]\s*', '', series).strip()
                # Также удаляем том номер и название внутри серии: "Солдат удачи 3. Взор Тьмы" → "Солдат удачи"
                # Паттерн: слова, потом пробел, потом цифра, потом точка/двоеточие, потом еще слова
                # Захватываем только до первого "число. название"
                series = re.sub(r'\s+\d+[\s\.\:].+$', '', series).strip()
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
            # Извлекаем часть после " - " и до нумерованного тома (N.)
            # Улучшено: теперь захватывает несколько слов перед номером
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s+\d+[\s\.\:]', filename)
            if match:
                series = match.group(2).strip()
                return series
        
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
    
    def _clean_series_name(self, text: str) -> str:
        """
        Очистить название серии от паразитных символов и информации:
        - Номера томов: "Солдат удачи 1", "Солдат удачи 2. Название"
        - Названия книг: "Серия 1. Название книги"
        - Служебные слова: "Трилогия", "Тетралогия"
        
        Примеры:
            "Солдат удачи 3. Взор Тьмы" → "Солдат удачи"
            "Вариант «Бис» 1" → "Вариант «Бис»"
            "Война в Космосе 5" → "Война в Космосе"
            "Странник (Серия 3)" → "Странник" (скобки обработаны)
        
        Args:
            text: Исходный текст
        
        Returns:
            Очищенное название серии
        """
        if not text:
            return text
        
        original = text.strip()
        
        # Правило 0: Удалить скобки с информацией в конце
        # "(к-во, год, описание)" → убрать
        text = re.sub(r'\s*\([^)]*\)\s*$', '', text).strip()
        
        # Правило 1: Удалить всё после "номер. слова" (объективное)
        # Паттерн: "слова цифра. слова" → берем только "слова"
        match = re.match(r'^(.+?)\s+\d+[\.\:]\s+.+$', text)
        if match:
            text = match.group(1).strip()
        
        # Правило 2: Удалить номер тома/выпуска в конце
        # Паттерны: "Серия 1", "Серия 2", "Серия (том) 3", и т.д.
        # Удаляем: пробел + одна или две цифры + конец
        text = re.sub(r'\s+\d{1,2}\s*$', '', text).strip()
        
        # Правило 3: Удалить всё после "номер " (менее строгое)
        # Паттерн: "слова цифра слова" → берем только "слова"
        match = re.match(r'^(.+?)\s+\d+\s+.+$', text)
        if match:
            text = match.group(1).strip()
        
        # Правило 4: Удалить служебные слова в скобках
        # "Серия (Трилогия)" → "Серия"
        text = re.sub(r'\s*\([^)]+\)\s*$', '', text).strip()
        
        # Правило 5: Удалить служебные слова в конце (простые, без скобок)
        # После серии часто идут: "- Трилогия", "- Цикл", и т.д.
        for service_word in self.service_words:
            # ВАЖНО: Используем \b для word boundary чтобы не удалять буквы из конца слова
            # Пример: НЕ удаляем "т" из "Адъютант" даже если "т" в service_words
            pattern = r'\s*[\-–—]?\s*\b' + re.escape(service_word) + r'\b\s*$'
            text = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
        
        return text if text else original

    
    def _matches_with_tolerance(self, text1: str, text2: str, tolerance: float = 0.85) -> bool:
        """
        Проверить что два текста совпадают с учетом опечаток, разницы в регистре и пунктуации.
        
        Args:
            text1: Первый текст
            text2: Второй текст
            tolerance: Минимальная степень совпадения (0.0-1.0)
        
        Returns:
            True если тексты совпадают с достаточной точностью
        """
        # Очистить от пунктуации и привести к нижнему регистру
        clean1 = re.sub(r'[^\w\s]', '', text1).lower().strip()
        clean2 = re.sub(r'[^\w\s]', '', text2).lower().strip()
        
        if not clean1 or not clean2:
            return False
        
        # Точное совпадение
        if clean1 == clean2:
            return True
        
        # Проверить что одна строка содержит другую полностью
        if clean1 in clean2 or clean2 in clean1:
            return True
        
        # Проверить используя Levenshtein distance (приблизительное совпадение)
        # Если совпадает > tolerance % символов
        max_len = max(len(clean1), len(clean2))
        if max_len == 0:
            return False
        
        # Простой подсчет: совпадающие символы / длина более длинной строки
        matches = sum(1 for a, b in zip(clean1, clean2) if a == b)
        similarity = matches / max_len
        
        return similarity >= tolerance
    
    def _is_author_surname(self, series_candidate: str, author: str) -> bool:
        """
        Проверить что extracted series это не просто фамилия автора.
        
        Примеры:
            ("Белоус", "Белоус Олег") → True (это фамилия)
            ("Белоус", "Иванов Сергей") → False (не фамилия)
            ("Солдат удачи", "Авраменко Александр") → False (это серия)
        
        Args:
            series_candidate: Извлеченная серия
            author: Автор в формате "Фамилия Имя"
            
        Returns:
            True если series - это фамилия автора
        """
        if not series_candidate or not author:
            return False
        
        # Парсим автора: обычно "Фамилия Имя"
        author_parts = author.strip().split()
        if not author_parts:
            return False
        
        # Первая часть - фамилия
        author_surname = author_parts[0].lower()
        series_lower = series_candidate.lower()
        
        # Проверяем точное совпадение (нормализованное)
        series_normalized = re.sub(r'[^\w]', '', series_lower)
        surname_normalized = re.sub(r'[^\w]', '', author_surname)
        
        return series_normalized == surname_normalized
    
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
        # ВАЖНО: сравниваем целое слово, не префикс!
        # Пример: "Туман" starts with "т", но "Туман" != "том" или "т."
        extracted_lower = extracted_series.lower().strip()
        
        # Проверяем только точное совпадение или начало строки с пробелом после
        # Это предотвращает ложные срабатывания на "т" для "Туман"
        for sw in self.service_words:
            sw_lower = sw.lower()
            # Только штрафуем если результат = service_word или service_word является отдельным словом
            if extracted_lower == sw_lower or extracted_lower.startswith(sw_lower + ' '):
                # БОЛЬШОЙ штраф - это служебное слово, не серия!
                score = max(0, score - 50)
                break
        
        # УРОВЕНЬ 5: Штраф за single-word результаты
        # Single-word результаты из сложных паттернов = вероятно Title, не Series
        # Например: "Охотник" из файла "Янковский - Охотник (Тетралогия)"
        
        return max(0, score)  # Минимум 0
