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
from pattern_converter import compile_patterns


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
        self.metadata_patterns = self.settings.get_list('series_patterns_in_metadata') or []
        
        # Скомпилировать паттерны в regex (один раз при инициализации)
        # Включает как file_patterns, так и metadata_patterns
        self.compiled_file_patterns = compile_patterns(self.file_patterns)
        self.compiled_metadata_patterns = compile_patterns(self.metadata_patterns)
        
        # Флаг: последний вызов _extract_series_from_brackets вернул иерархическую серию
        # (MainSeries N из "MainSeries N. SubSeries M-K") — не убирать trailing number
        self._last_was_hierarchical = False
    
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
                                extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                                if self._is_valid_series(series, extracted_author=extracted_author_for_validation):
                                    record.proposed_series = series
                                    record.series_source = "metadata"
                            continue  # Переходим к следующему файлу
                        
                        # ПРОВЕРКА 2: Не используем фамилию автора как серию
                        if self._is_author_surname(series_from_patterns, record.proposed_author):
                            # Это фамилия, не серия - пропускаем и используем только metadata
                            if record.metadata_series:
                                series = record.metadata_series.strip()
                                extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                                if self._is_valid_series(series, extracted_author=extracted_author_for_validation):
                                    record.proposed_series = series
                                    record.series_source = "metadata"
                            continue  # Переходим к следующему файлу
                        
                        # Применяем очистку (сохраняем trailing number если иерархическая серия)
                        clean_candidate = self._clean_series_name(series_from_patterns, keep_trailing_number=self._last_was_hierarchical)
                        
                        # ПРОВЕРКА 3: Валидизируем clean_candidate
                        # Передаём информацию об извлечённом авторе чтобы не отвергать series
                        # если она выглядит как фамилия (но это другое слово чем автор)
                        extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                        if self._is_valid_series(clean_candidate, extracted_author=extracted_author_for_validation):
                            # ВСЕГДА используем clean candidate из filename как proposed_series
                            # Это наиболее надёжный источник информации о серии
                            # Валидизация только фильтрует очевидно неправильные значения
                            record.proposed_series = clean_candidate
                            record.series_source = "filename"
                            continue  # Обработка завершена, переходим к следующему файлу
                        
                        # Series не прошёл валидацию - НЕ используем его, fallthrough к bracket/metadata fallback
                        # (не выполняем continue, чтобы дать шанс fallback методам ниже)
                    
                    # ШАГ 2: Fallback - extractжем из скобок если паттерны не сработали
                    name_without_ext = filename.rsplit('.', 1)[0]
                    
                    # ПРИ ОРИТЕТ: сначала пытаемся извлечь серию перед скобками
                    # "Бродяга (СИ)" → пытаемся извлечь "Бродяга"
                    # "Бродяга 2. Звёздные закоулки (СИ)" → пытаемся извлечь "Бродяга"
                    name_before_brackets = re.sub(r'\s*\([^)]*\)\s*$', '', name_without_ext).strip()
                    
                    # Пытаемся применить паттерны к имени ДО скобок
                    # (это может помочь extract "Бродяга" из "Аскеров - Бродяга (СИ)")
                    series_candidate = None
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
                                # Передаём контекст автора при валидации чтобы не отвергать series
                                # если она выглядит как имя человека
                                extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                                if self._is_valid_series(series_candidate, extracted_author=extracted_author_for_validation):
                                    record.proposed_series = series_candidate
                                    record.series_source = "filename"
                    
                    # ШАГ 1.5: Если скобок нет, попробуем config patterns из filename
                    # Это поддерживает "Author - Series.Title" формат
                    if not record.proposed_series:
                        filename = Path(record.file_path).name
                        series_candidate = self._extract_series_from_filename(record.file_path, validate=False)
                        if series_candidate:
                            record.extracted_series_candidate = series_candidate
                            clean_candidate = self._clean_series_name(series_candidate, keep_trailing_number=self._last_was_hierarchical)
                            extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                            if self._is_valid_series(clean_candidate, extracted_author=extracted_author_for_validation):
                                record.proposed_series = clean_candidate
                                record.series_source = "filename"
                    
                    # Если из filename ничего не нашли, но есть metadata - используем её
                    if not record.proposed_series and record.metadata_series:
                        series = self._extract_series_from_metadata(record.metadata_series.strip())
                        extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                        if self._is_valid_series(series, extracted_author=extracted_author_for_validation):
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
                        clean_candidate = self._clean_series_name(series_candidate, keep_trailing_number=self._last_was_hierarchical)
                        extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                        if self._is_valid_series(clean_candidate, extracted_author=extracted_author_for_validation):
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
                            extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                            if self._is_valid_series(series_candidate, extracted_author=extracted_author_for_validation):
                                record.proposed_series = series_candidate
                                record.series_source = "filename"
                
                # ШАГ 3: Финальный fallback - используем metadata если есть
                if record.metadata_series:
                    series = self._extract_series_from_metadata(record.metadata_series.strip())
                    extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                    if self._is_valid_series(series, extracted_author=extracted_author_for_validation):
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
                clean_candidate = self._clean_series_name(series_candidate, keep_trailing_number=self._last_was_hierarchical)
                
                # Проверим валидность (очищенной версии)
                if not self._is_valid_series(clean_candidate):
                    # Candidate заблочен по BL, но оставляем его для consensus
                    # Используем только metadata если есть
                    if record.metadata_series:
                        series = record.metadata_series.strip()
                        extracted_author_for_validation = record.proposed_author if record.proposed_author else None
                        if self._is_valid_series(series, extracted_author=extracted_author_for_validation):
                            record.proposed_series = series
                            record.series_source = "metadata"  # Метаданные как основной источник
                else:
                    # Candidate (очищенный) валиден, применяем его
                    # ШАГ 3: Проверить совпадает ли с metadata
                    if record.metadata_series and record.metadata_series.strip():
                        metadata_series = self._extract_series_from_metadata(record.metadata_series.strip())
                        
                        # СРАВНИВАЕМ ОЧИЩЕННУЮ версию кандидата с очищенной metadata
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
        
        # Commented out: folder pattern consensus was also causing issues  
        # self._apply_series_folder_pattern_consensus(records)
        
        # Commented out: consensus logic was overwriting properly extracted series
        # TODO: Review and fix consensus logic before re-enabling
        # self._apply_cross_file_consensus(records)
    
    def _apply_series_folder_pattern_consensus(self, records: List[BookRecord]) -> None:
        """
        Для файлов в series folder: найти common name patterns и применить consensus.
        
        Логика:
        1. Ищем файлы в папках типа "Серия - ..." (series collection folders)
        2. Для каждого автора в folder анализируем filename patterns
        3. Ищем файлы с common "Author. FirstWord" структурой
        4. Если есть файлы с extracted_series, и файл без series имеет совпадающий FirstWord,
           применяем series из других файлов как consensus
        
        Примеры:
        - File 1: "Жеребьёв. Негоциант 2. Марланский Квест" → extracted = "Негоциант"
        - File 2: "Жеребьёв. Негоциант" → extracted = empty, FirstWord = "Негоциант"
          → Применяем "Негоциант" к File 2 как consensus
        - File 3: "Жеребьёв. Ретранслятор" → extracted = empty, FirstWord = "Ретранслятор"
          → Не совпадает с другими, остается пусто
        """
        from collections import defaultdict
        
        # Группируем файлы по папке (series folder) и автору
        folder_author_files = defaultdict(lambda: defaultdict(list))
        
        for record in records:
            file_path_parts = Path(record.file_path).parts
            
            # Проверяем является ли это series folder структурой
            if len(file_path_parts) >= 2:
                parent_folder = file_path_parts[0]
                
                # Проверяем что это series folder
                is_series_folder = (
                    parent_folder.startswith('Серия') or
                    'Серия' in parent_folder
                )
                
                if is_series_folder and record.proposed_author:
                    # Это файл в series folder - сохраняем в группировку
                    folder_author_files[parent_folder][record.proposed_author].append(record)
        
        # Для каждой папки и автора анализируем файлы
        for folder, authors_dict in folder_author_files.items():
            for author, author_files in authors_dict.items():
                if len(author_files) < 2:
                    continue  # Нужно минимум 2 файла для поиска consensus
                
                # Анализируем структуру имен файлов
                # Ищем файлы с 2-part "Author. Name" структурой
                file_patterns = {}  # { first_word_after_author: [records] }
                
                for record in author_files:
                    filename = Path(record.file_path).name
                    name_without_ext = filename.rsplit('.', 1)[0]
                    
                    # Проверяем 2-part структуру "Author. Name"
                    if '. ' in name_without_ext:
                        parts = name_without_ext.split('. ', 1)  # Split на первую точку
                        if len(parts) == 2:
                            first_part = parts[0].strip()
                            second_part = parts[1].strip()
                            
                            # Проверяем что первая часть это single word (likely author surname)
                            if ' ' not in first_part:
                                # Извлекаем первое слово из второй части
                                first_word = second_part.split()[0] if second_part else ""
                                
                                if first_word:
                                    # Нормализуем для сравнения
                                    first_word_norm = first_word.lower()
                                    
                                    if first_word_norm not in file_patterns:
                                        file_patterns[first_word_norm] = {
                                            'first_word': first_word,
                                            'records': []
                                        }
                                    
                                    file_patterns[first_word_norm]['records'].append(record)
                
                # Для каждой группы файлов с одинаковым first_word прим ем consensus
                for first_word_norm, pattern_info in file_patterns.items():
                    if len(pattern_info['records']) < 2:
                        continue  # Нужно минимум 2 файла с одинаковым first_word
                    
                    # Ищем extracted_series в файлах с этим first_word
                    series_candidates = set()
                    
                    for rec in pattern_info['records']:
                        if rec.proposed_series:
                            # Уже има series - добавляем как candidate
                            series_candidates.add(rec.proposed_series)
                        elif rec.extracted_series_candidate:
                            # Был extracted candidate
                            clean = self._clean_series_name(rec.extracted_series_candidate)
                            if clean:
                                series_candidates.add(clean)
                    
                    # Если нашли series candidates, применяем к файлам без series
                    if series_candidates:
                        # Берем наибольший common prefix или просто первый candidate
                        best_candidate = list(series_candidates)[0]
                        
                        for rec in pattern_info['records']:
                            if not rec.proposed_series:
                                # Файл без series - применяем consensus
                                rec.proposed_series = best_candidate
                                rec.series_source = "consensus"
    
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
                    
                    # ВАЖНО: Не применяем consensus если файл имеет extracted_series_candidate
                    # даже если proposed_series пусто (может быть мы не прошли валидацию)
                    # Consensus применяется ТОЛЬКО к файлам у которых НЕЧЕГО не извлечено
                    if candidate['extracted']:
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
    
    def _analyze_filename_structure(self, filename: str) -> dict:
        """
        Анализировать структуру имена файла и выделить её элементы.
        
        Результат помогает выбрать ЛУЧШИЙ паттерн по соответствию структуре.
        
        Returns:
            {
                'has_brackets': bool,        # Есть ли скобки () в конце
                'has_square_brackets': bool, # Есть ли квадратные скобки []
                'bracket_content': str,      # Содержимое скобок (если есть)
                'has_dots': int,             # Количество точек как разделителей
                'has_dash': bool,            # Есть ли " - " (дефис с пробелами)
                'dashes': int,               # Количество " - "
                'parts_count': int,          # Количество основных частей (по дефисам/точкам)
            }
        """
        structure = {
            'has_brackets': False,
            'has_square_brackets': False,
            'bracket_content': '',
            'has_dots': 0,
            'has_dash': False,
            'dashes': 0,
            'parts_count': 0,
        }
        
        # Проверяем скобки в конце
        bracket_match = re.search(r'\(([^)]+)\)\s*$', filename)
        if bracket_match:
            structure['has_brackets'] = True
            structure['bracket_content'] = bracket_match.group(1)
        
        # Проверяем квадратные скобки
        if '[' in filename and ']' in filename:
            structure['has_square_brackets'] = True
        
        # Считаем точки (как разделители, не в конце как расширение)
        # Исключаем точку в конце для расширения
        text_part = filename.rsplit('.', 1)[0] if filename.endswith('.fb2') else filename
        structure['has_dots'] = text_part.count('. ')
        
        # Проверяем дефисы
        if ' - ' in filename:
            structure['has_dash'] = True
            structure['dashes'] = filename.count(' - ')
        
        # Считаем основные части (по дефисам)
        if structure['has_dash']:
            structure['parts_count'] = structure['dashes'] + 1
        else:
            # Если нет дефисов, считаем по точкам
            structure['parts_count'] = structure['has_dots'] + 1 if structure['has_dots'] > 0 else 1
        
        return structure
    
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
        
        # ВАЖНО: Удалить метатеги из конца filename ПЕРЕД парсингом
        # "(СИ)" - Самиздат/Интернет
        # "(ЛП)" - Лицензионное произведение
        # Эти метатеги не должны влиять на извлечение series
        name_for_parsing = re.sub(r'\s*\([СЛ]И\)\s*$', '', name_without_ext).strip()
        
        # ШАГ 0: Найти ЛУЧШИЙ паттерн на основе оценки соответствия структуре файла
        # Применяем ВСЕ паттерны, не только первый!
        best_series = None
        best_score = -100.0  # Низкий стартовый score
        best_pattern = None
        
        # Анализируем структуру файла один раз
        filename_structure = self._analyze_filename_structure(name_for_parsing)
        
        if self.compiled_file_patterns:
            for pattern_str, compiled_regex, group_names in self.compiled_file_patterns:
                # Применить скомпилированный regex
                match = compiled_regex.match(name_for_parsing)
                
                if match:
                    # Попытаться извлечь группу "series" из match
                    series_candidate = None
                    
                    # Ищем группу "series" среди извлеченных групп
                    # Она может быть названа 'series', 'series_service_words', и т.д.
                    series_group_name = None
                    for g_name in group_names:
                        if 'series' in g_name:
                            series_group_name = g_name
                            break
                    
                    if series_group_name:
                        # Извлекли группу с "series" в имени
                        raw_series = match.group(series_group_name).strip()
                        
                        # Если имя группы содержит "service_words" или паттерн имеет скобки,
                        # это значит что нужна специальная обработка содержимого скобок
                        words = raw_series.split()
                        last_word = words[-1] if words else ""
                        
                        if 'service_words' in series_group_name or '. ' in raw_series or '-' in last_word:
                            # Применяем логику _extract_series_from_brackets для очистки
                            series_candidate = self._extract_series_from_brackets(raw_series)
                        else:
                            # Иначе берем как есть
                            series_candidate = raw_series
                    
                    # Если нет явной группы "series", проверяем есть ли скобки в паттерне
                    # это означает что series информация в скобках
                    if not series_candidate and '(' in pattern_str and ')' in pattern_str:
                        # Используем старую логику _apply_config_pattern для обработки скобок
                        series_candidate = self._apply_config_pattern(pattern_str, name_for_parsing)
                    
                    if series_candidate:
                        # КЛЮЧЕВОЙ МОМЕНТ: ОЦЕНИТЬ соответствие паттерна структуре файла
                        score = self._score_pattern_match(pattern_str, name_for_parsing, series_candidate)
                        
                        # Валидируем series но пропускаем check на автора
                        # (потому что здесь нет контекста об авторе из record)
                        is_valid = not validate or self._is_valid_series(series_candidate, skip_author_check=True)
                        
                        # ВЫБИРАЕМ ЛУЧШИЙ: If score is better AND series is valid
                        # NOTE: используем >= instead of > чтобы более специфичные паттерны (в конце списка)
                        # могли replace earlier patterns if score is the same
                        if is_valid and score >= best_score:
                            best_series = series_candidate
                            best_score = score
                            best_pattern = pattern_str
        
        if best_series:
            # Проверка 1: если best_series - это serve_word, не возвращаем его
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
                # Проверка 2: КРИТИЧНО - проверить blacklist даже если validate=False
                # Blacklist всегда должна проверяться, это не результат валидации
                # а фильтр для явно запрещенных слов
                is_blacklisted = False
                for bl_word in self.filename_blacklist:
                    if bl_word.lower() in best_series_lower:
                        is_blacklisted = True
                        break
                
                if is_blacklisted:
                    # Это запрещенное слово, игнорируем
                    best_series = None
                else:
                    return best_series
        
        # Правило 1: [Серия] в квадратных скобках в начале
        # Из паттернов конфига ищем примеры с [...]
        match = re.search(r'^\[([^\[\]]+)\]', name_for_parsing)
        if match:
            series = match.group(1).strip()
            if not validate or self._is_valid_series(series):
                return series
        
        # Правило 2: Серия в скобках в КОНЦЕ 
        # Из паттернов конфига: "Author - Title (Series. service_words)"
        # Ищем скобку в конце, может быть с сервис-словами перед ней
        if '(' in name_for_parsing and ')' in name_for_parsing:
            # Ищем закрытую скобку в конце, которой предшествует открытая скобка
            match = re.search(r'\(([^)]+)\)\s*$', name_for_parsing)
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
        if '. ' in name_for_parsing:
            potential_series = name_for_parsing.split('. ')[0].strip()
            
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
        
        # Правило 3B: Author. Series N (без второго элемента после точки)
        # "Курилкин. Охотник 1" → "Охотник"
        # Структура: OneWord. MultipleWords N где N это одна или две цифры
        if '. ' in name_for_parsing and ' ' not in name_for_parsing.split('. ')[0]:
            # Первая часть это одно слово (вероятно Author)
            parts = name_for_parsing.split('. ', 1)
            if len(parts) == 2:
                second_part = parts[1].strip()
                # Проверяем, содержит ли вторая часть номер в конце
                # "Охотник 1" → True, "Охотник" → False (но это обработано другими рулами)
                series_match = re.match(r'^(.+?)\s+\d+\s*$', second_part)
                if series_match:
                    potential_series = series_match.group(1).strip()
                    if not validate or self._is_valid_series(potential_series):
                        return potential_series
        
        # Правило 4: Author - Series N (без точки после номера)
        # "Атаманов Михаил - Задача выжить 1" → "Задача выжить"
        # Паттерн: Author - Серия N где N это одна или две цифры в конце
        if ' - ' in name_for_parsing:
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s+\d{1,2}\s*$', name_for_parsing)
            if match:
                potential_series = match.group(2).strip()
                # Убедимся что это не автор (не похоже на имя)
                if not validate or self._is_valid_series(potential_series):
                    return potential_series
        
        # Правило 5: Author - Title. Subtitle (fallback для файлов без номея)
        # "Земляной Андрей - Отморозки. Другим путем" → "Отморозки"
        # Попытаемся извлечь часть после " - " и до первой точки как Title (которая может быть Series)
        if ' - ' in name_without_ext and '. ' in name_without_ext:
            match = re.match(r'^(.+?)\s*-\s*([^.]+)\.\s+(.+)$', name_without_ext)
            if match:
                title_before_dot = match.group(2).strip()
                if "охотник" in name_without_ext.lower():
                    print(f"  [Rule 5 match] title_before_dot='{title_before_dot}'")
                # Это Title (потенциальная Series) если он:
                # 1. Имеет несколько слов ИЛИ 
                # 2. Это нечто более подходящее серии чем фамилия  
                if len(title_before_dot.split()) > 1 or (title_before_dot and len(title_before_dot) > 3):
                    if not validate or self._is_valid_series(title_before_dot):
                        if "охотник" in name_without_ext.lower():
                            print(f"  [RETURNING from Rule 5] '{title_before_dot}'")
                        return title_before_dot
        
        if "охотник" in name_without_ext.lower():
            print(f"  [NO MATCH - returning empty]")
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
            # ВАЖНО: проверяем содержимое скобок чтобы различить:
            # 1) "Author - Series (service_words)" ← скобки содержат ТОЛЬКОслужебные слова/числа
            # 2) "Author - Title (Series info)" ← скобки содержат РЕАЛЬНУЮ серию
            # 
            # Проблема: "Горъ Василий - Чужая кровь (Пророчество 5-7)"
            #   Group 2 = "Чужая кровь" (title, не серия!)
            #   Скобки = "Пророчество 5-7" (реальная серия!)
            #   → НЕ должен совпадать с "Author - Series (service_words)"
            match = re.match(r'^(.+?)\s*-\s*([^()]+?)\s*\(([^)]*)\)', filename)
            if match:
                series_candidate = match.group(2).strip()
                brackets_content = match.group(3).strip()
                
                # Анализируем что в скобках
                service_words_lower = [sw.lower() for sw in self.service_words]
                brackets_lower = brackets_content.lower()
                
                # Проверяем различные случаи:
                skip_keywords = ['сборник', 'авторский', 'собрание', 'антология']
                is_skip_keyword = any(kw in brackets_lower for kw in skip_keywords)
                
                is_pure_service_word = any(
                    brackets_lower.startswith(sw) or brackets_lower == sw
                    for sw in service_words_lower
                )
                
                is_numeric_range = bool(re.match(r'^\d+[-–—]\d+$', brackets_content))
                
                # НОВОЕ: проверяем если в скобках есть текст + числа (смешанный формат)
                # например "Пророчество 5-7" или "Ермак 4-6"
                # Это означает что скобки содержат РЕАЛЬНУЮ СЕРИЮ, а не служебные слова!
                # В этом случае паттерн "Author - Series (service_words)" НЕ СОВПАДАЕТ
                # - скорее всего это "Author - Title (Series)" паттерн
                has_text_and_numbers = bool(re.search(r'[а-яё\w]+\s+\d', brackets_lower)) or \
                                       bool(re.search(r'\d+\s+[а-яё\w]+', brackets_lower))
                
                # Если скобки содержат реальную серию (текст + числа), НЕ совпадаем
                if has_text_and_numbers:
                    # это не паттерн "Series (service_words)", это "Title (Series info)"
                    # Пусть обработает другой паттерн
                    return ""
                
                # Если скобки содержат ТОЛЬКОслужебное слово, число или skip-keyword → это не серия!
                if is_pure_service_word or is_numeric_range or is_skip_keyword:
                    # "Эпоха перемен (Трилогия)" → нет информации о серии в файле
                    # Нужно вернуть пусто и дать возможность fallback на metadata
                    return ""
                
                # Иначе это реальная серия в скобках (случай вроде "Авраменко - Солдат удачи (Наследник)")
                series = series_candidate
                # Удаляем префикс книги: "1. ", "2. ", "3. " и т.д.
                series = re.sub(r'^\s*\d+\s*[.,]\s*', '', series).strip()
                # Также удаляем том номер и название внутри серии: "Солдат удачи 3. Взор Тьмы" → "Солдат удачи"
                series = re.sub(r'\s+\d+[\s\.\:].+$', '', series).strip()
                # Если результат содержит '. ' — берём только часть до точки
                if '. ' in series:
                    before_dot = series.split('. ')[0].strip()
                    series = before_dot
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
            # ВАЖНО: Не применяем если в filename есть скобки - это дело pattern "Author. Title (Series)"
            # "Кумин. Битва за звёзды (Исход. Тетралогия)" не должен обрабатываться так!
            # Наличие скобок означает что реюлярная серия в скобках, а не "Author. Series. Title"
            if '(' in filename:
                # Есть скобки - скорее всего "Author. Title (Series)" паттерн, пропускаем
                return ""
            
            parts = filename.split('. ')
            if len(parts) >= 3:
                # parts[1] должна быть Series
                series = parts[1].strip()
                # Удаляем trailing число (том/выпуск) из серии
                # "Негоциант 2" -> "Негоциант"
                series = re.sub(r'\s+\d+\s*$', '', series).strip()
                return series
        
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
        
        elif pattern == "Author - Series service_words. Title":
            # "Игнатов Михаил - Путь 10. Защитник. Второй пояс (СИ)"
            # Извлекаем Series между " - " и номером
            # Паттерн: Author - Series Number. Title
            # ВАЖНО: Требуем пробелы ДО дефиса чтобы не совпасть с дефисом в серии
            # "Сердитый, Бирюков. Человек-саламандра 1" не должен совпасть
            # (здесь дефис без пробела перед ним)
            match = re.match(r'^(.+?)\s+-\s+(.+?)\s+\d+\.\s+', filename)
            if match:
                series = match.group(2).strip()
                return series
        
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
        # Сбрасываем флаг иерархической серии
        self._last_was_hierarchical = False
        
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
            after_dot = parts[1].strip() if len(parts) > 1 else ''
            after_dot_lower = after_dot.lower()
            
            # Проверка служебных слов + blacklist + collection_keywords
            # "Мир Алекса Королёва. Сборник" → after_dot="сборник" → берём "Мир Алекса Королёва"
            blacklist_words = [w.lower() for w in self.filename_blacklist]
            collection_words = [w.lower() for w in self.collection_keywords]
            service_check_words = ['том', 'дилогия', 'трилогия', 'тетралогия', 'пенталогия', 'роман-эпопея']
            all_check_words = service_check_words + blacklist_words + collection_words
            is_service_word = any(
                after_dot_lower.startswith(sw.lower()) 
                for sw in all_check_words
            )
            
            if is_service_word:
                return parts[0].strip()
            
            # ИЕРАРХИЧЕСКАЯ СЕРИЯ: "Отрок 2. Сотник 1-3"
            # Признаки: parts[0] = "Слова Число", parts[1] = "Слова Число/Диапазон"
            # → это главная серия + подсерия → возвращаем parts[0] КАК ЕСТЬ (с номером тома!)
            # Отличие от обычного случая: after_dot начинается с заглавной буквы (имя подсерии)
            # и содержит число или диапазон
            part0 = parts[0].strip()
            # parts[0] заканчивается числом: "Отрок 2", "Серия 5"
            part0_has_trailing_num = bool(re.search(r'\s+\d+\s*$', part0))
            # parts[1] начинается с заглавной буквы и содержит число: "Сотник 1-3", "Книга 2"
            after_dot_is_subseries = (
                after_dot and
                after_dot[0].isupper() and
                bool(re.search(r'\d', after_dot))
            )
            
            if part0_has_trailing_num and after_dot_is_subseries:
                # Иерархическая серия: возвращаем главную серию С номером тома
                # "Отрок 2. Сотник 1-3" → "Отрок 2"
                # Устанавливаем флаг чтобы _clean_series_name не убирала trailing number
                self._last_was_hierarchical = True
                return part0
        
        # НОВОЕ: Если есть service word в конце БЕЗ точки
        # "Я иду искать! Тетралогия" -> "Я иду искать!"
        # "Демон 1-3" -> "Демон"
        service_markers = {
            'том', 'volume', 'vol', 'т.', 'v.',  # Volume/tome markers
            'часть', 'part', 'п.', 'pt.',  # Part markers
            'выпуск', 'issue', 'вып.',  # Issue markers
            'книга', 'book', 'кн.',  # Book markers
            'дилогия', 'duology', 'трилогия', 'trilogy',  # Series count
            'тетралогия', 'tetralogy', 'пенталогия', 'pentalogy',
            'роман-эпопея', 'epic novel',
        }
        
        # Ищём service words в конце контента (отделённые пробелом или в начале слова)
        # "Я иду искать! Тетралогия" -> parts = ["Я иду искать!", "Тетралогия"]
        # "Демон 1-3" -> parts = ["Демон", "1-3"]
        words = content.split()
        if len(words) > 1:
            last_word_lower = words[-1].lower()
            
            # Проверяем, является ли последнее слово service word
            is_last_service_word = any(
                last_word_lower.startswith(sw.lower()) or 
                last_word_lower == sw.lower()
                for sw in service_markers
            )
            
            # Или это диапазон номеров
            is_numeric_range = bool(re.match(r'^\d+[-–—]\d+$', words[-1]))
            
            if is_last_service_word or is_numeric_range:
                # Возьмём все слова кроме последнего
                series_candidate = ' '.join(words[:-1]).strip()
                if series_candidate:
                    return series_candidate
        
        # Если есть числовой диапазон (1-3, 4-6), берем до него
        series_candidate = re.sub(r'\s*[\d\-]+\s*$', '', content).strip()
        
        return series_candidate if series_candidate else ""
    
    def _is_valid_series(self, text: str, extracted_author: str = None, skip_author_check: bool = False) -> bool:
        """
        Проверить что text выглядит как название серии, не как другое.
        Проверяет против:
        - filename_blacklist (список запрещенных слов)
        - collection_keywords (сборники, антологии)
        - service_words (том, книга, выпуск)
        - AuthorName (не похоже на имя автора) - ЗА ИСКЛЮЧЕНИЕМ случаев когда это иное слово
        
        Args:
            text: Проверяемый текст (название серии)
            extracted_author: Опционально, извлечённый из файла автор. Если passed, не отвергаем
                            series если она не совпадает с author (важно для паттернов "Author - Series")
            skip_author_check: Если True - пропускаем проверку на похожесть на автора (используется при
                            предварительной валидации без контекста об авторе)
        """
        if not text or len(text) < 2:
            return False
        
        text_lower = text.lower()
        
        # ПРОВЕРКА 1: filename_blacklist - запрещенные слова
        # ВАЖНО: проверяем целые слова, не substring!
        # "СИ" в blacklist относится к метатегам "(СИ)" в конце, а не к "Сид"
        for bl_word in self.filename_blacklist:
            bl_word_lower = bl_word.lower()
            # Проверяем как целое слово, отделённое границами
            # Паттерны: "СИ" или "СИ)" или "(СИ)" или в начале/конце
            import re
            # Match bl_word as a whole word or at word boundary
            pattern = r'(?:^|\s|\(|-)' + re.escape(bl_word_lower) + r'(?:\s|\)|$)'
            if re.search(pattern, text_lower):
                return False
        
        # ПРОВЕРКА 2: Исключить очевидные сборники/антологии
        # Эти фразы обычно многословные (сборник, антология, коллекция)
        # поэтому substring check более безопасен
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
        # Если skip_author_check=True - пропускаем эту проверку
        # (используется при предварительной валидации без контекста об авторе)
        if not skip_author_check:
            # КРИТИЧНО: если extracted_author передан, мы уже знаем что это не автор
            # Например в паттерне "Author - Series" мы извлекли series из second part
            # и у нас есть информация об авторе - нет смысла отвергать series
            # только потому что она выглядит как фамилия (может быть совпадение)
            try:
                author = AuthorName(text)
                if author.is_valid:
                    # Это похоже на валийного автора... но есть ли контекст?
                    if extracted_author:
                        # У нас есть информация об извлечённом авторе
                        # Пропускаем проверку на автора если text отличается от автора
                        # "Охотник" != "Янковский Дмитрий" → это не автор, это серия
                        try:
                            extracted_author_obj = AuthorName(extracted_author)
                            extracted_author_normalized = extracted_author_obj.normalized or extracted_author_obj.raw_name
                            
                            # Нормализуем text как если бы это был автор
                            text_as_author_obj = AuthorName(text)
                            text_as_author_normalized = text_as_author_obj.normalized or text_as_author_obj.raw_name
                            
                            # Если normalized версии совпадают - это один и тот же автор
                            if extracted_author_normalized != text_as_author_normalized:
                                # Это РАЗНЫЕ авторы/имена → text это серия, не автор
                                return True
                        except Exception:
                            # Если нормализация не сработала - пытаемся простое сравнение
                            if extracted_author.lower() != text.lower():
                                return True
                    
                    # Если контекста нет или совпадает - отвергаем как автора
                    return False
            except Exception:
                pass  # Если парсинг не сработал - это вероятно серия
        
        return True
    
    def _extract_series_from_metadata(self, metadata_series: str) -> str:
        """
        Применить паттерны из series_patterns_in_metadata для очистки metadata серии.
        
        Паттерн "Series. Title" означает: извлечь всё перед первой точкой.
        Пример: "Рукопись Памяти-3. Забытое грядущее" → "Рукопись Памяти-3"
        
        Args:
            metadata_series:值ание серии из метаданных
        
        Returns:
            Очищенное название серии
        """
        if not metadata_series or not self.metadata_patterns:
            return metadata_series
        
        text = metadata_series.strip()
        
        # Применяем каждый паттерн
        for pattern_obj in self.metadata_patterns:
            pattern = pattern_obj.get('pattern', '')
            
            if pattern == "Series. Title":
                # "Серия. Название" → "Серия"
                # Извлекаем всё перед первой точкой + пробелом
                if '. ' in text:
                    series = text.split('. ')[0].strip()
                    if series:
                        return series
        
        return text
    
    def _clean_series_name(self, text: str, keep_trailing_number: bool = False) -> str:
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
        
        if not keep_trailing_number:
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
    
    def _is_hierarchical_series(self, text: str) -> bool:
        """
        Проверить является ли текст иерархической серией вида "MainSeries N" 
        где N — номер тома в главной серии (не просто trailing number для удаления).
        
        Признак: текст заканчивается числом, и это число — часть имени серии,
        потому что оригинальный контент скобок был "MainSeries N. SubSeries M-K".
        
        Используется чтобы не убирать trailing number в _clean_series_name.
        
        Примеры:
            "Отрок 2" → True (было "Отрок 2. Сотник 1-3")
            "Солдат удачи 3" → False (обычный номер тома)
        
        Простая эвристика: если текст = "Слова Число" и число <= 20 — 
        мы не можем точно знать без контекста. Поэтому этот метод
        должен вызываться только когда контекст известен.
        """
        # Этот метод — заглушка, реальная логика в _extract_series_from_brackets
        # который возвращает результат с флагом через специальный маркер
        return bool(re.match(r'^.+\s+\d+$', text.strip()))

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

        # ── HARD DISQUALIFIERS ──────────────────────────────────────────────────
        # Если паттерн требует структурный элемент, которого нет в имени файла,
        # этот паттерн не может подойти → сразу возвращаем -1.

        # Паттерн требует ' - ' (разделитель-тире), но в имени файла его нет
        if ' - ' in pattern and ' - ' not in filename:
            return -1

        # Паттерн требует запятую (соавторы), но в имени файла её нет
        if ',' in pattern and ',' not in filename:
            return -1

        # Паттерн требует скобки '(', но в имени файла их нет
        if '(' in pattern and '(' not in filename:
            return -1

        # ── POSITIVE SCORING ────────────────────────────────────────────────────
        # Начисляем очки за каждый структурный элемент, который паттерн
        # правильно предсказывает. Также начисляем очки, когда паттерн
        # правильно предсказывает ОТСУТСТВИЕ элемента (двунаправленное).

        score = 0
        max_score = 0

        # Тире ' - '
        max_score += 3
        if ' - ' in pattern:
            if ' - ' in filename:
                score += 3
        else:
            # Паттерн без тире — награждаем, если и в файле нет тире
            if ' - ' not in filename:
                score += 3

        # Запятая (соавторы)
        max_score += 2
        if ',' in pattern:
            if ',' in filename:
                score += 2
        else:
            if ',' not in filename:
                score += 2

        # Скобки '('
        max_score += 2
        if '(' in pattern:
            if '(' in filename:
                score += 2
        else:
            if '(' not in filename:
                score += 2
        
        # КРИТИЧНА ПРОВЕРКА: Если файл имеет скобки с series info, а паттерн 
        # это "Author - Series (...)" то это НЕПРАВИЛЬНЫЙ паттерн!
        # "Author - Series" означает что part после "-" это series.
        # Но если файл имеет "(something in brackets)", то структура это
        # "Author - Title (Series info)", не "Author - Series (number)".
        # Штрафуем такое несоответствие!
        has_brackets = '(' in filename and ')' in filename
        if pattern == 'Author - Series (service_words)' and has_brackets:
            # Большой штраф за неправильное п interpretac паттерна структуры
            score -= 5
            if score < -1:
                return -1

        # service_words в паттерне
        max_score += 1
        if 'service_words' in pattern:
            score += 1

        # Бонус: серия извлечена из скобок — более надёжный источник
        # Паттерны "(Series. service_words)" и "(Series service_words)" надёжнее чем "Author - Series (...)"
        # потому что в скобках явно указана серия, а не Title
        # ВАЖНО: не даём бонус если extracted_series это service_word!
        # Service words (Тетралогия, Дилогия, Трилогия) — это не названия серий,
        # это описания количества книг. Если извлекли service_word из скобок —
        # это не означает что скобки содержали название серии.
        max_score += 3
        bracket_series_patterns = [
            "Author - Title (Series. service_words)",
            "Author - Title (Series service_words)",
            "Author. Title (Series. service_words)",
            "Author. Title (Series. Title. service_words)",
            "Author, Author - Title (Series. service_words)",
            "Author, Author. Title (Series)",
            "Author, Author. Title (Series. Title. service_words)",
            # Patterns with year metadata at the end
            "Author - Title (Series. service_words) - year",
            "Author - Series (service_words) - year",
            "Author - Title (Series service_words) - year",
            "Author. Title (Series. service_words) - year",
            "Author, Author. Title (Series. Title. service_words) - year",
        ]
        if pattern in bracket_series_patterns:
            # Проверяем что extracted_series это не service_word перед начислением бонуса
            extracted_series_lower = extracted_series.lower().strip()
            is_service_word = False
            for sw in self.service_words:
                sw_lower = sw.lower()
                if extracted_series_lower == sw_lower or extracted_series_lower.startswith(sw_lower + ' '):
                    is_service_word = True
                    break
            
            # Только даём бонус если это НЕ service_word
            if not is_service_word:
                score += 3

        # Длина извлечённой серии: больше слов = надёжнее
        word_count = len(extracted_series.split())
        max_score += 6
        if word_count >= 2:
            score += min(6, word_count * 2)
        elif word_count == 0:
            return -1

        if max_score == 0:
            return 0

        return max(0, score)
