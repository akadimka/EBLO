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
import sys
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
from block_level_pattern_matcher import BlockLevelPatternMatcher


class BlockLevelPatternSelector:
    """Выбирает паттерн на основе анализа структурных блоков файла"""
    
    @staticmethod
    def analyze_filename_blocks(filename: str) -> dict:
        """Разбирает файл на структурные блоки"""
        
        # Извлекаем содержимое скобок
        bracket_match = re.search(r'\(([^)]+)\)\s*$', filename)
        
        parts = {
            'filename': filename,
            'has_brackets': bool(bracket_match),
            'content_in_brackets': bracket_match.group(1).strip() if bracket_match else None,
            'before_brackets': filename[:bracket_match.start()].strip() if bracket_match else filename,
        }
        
        # Анализируем "до скобок"
        before = parts['before_brackets']
        parts['before_bracket_parts'] = {
            'has_comma': ',' in before,
            'comma_count': before.count(','),
            'has_dot': '.' in before,
            'has_dash': ' - ' in before,
        }
        
        # Анализируем содержимое скобок - считаем иерархию (точки внутри)
        if parts['has_brackets'] and parts['content_in_brackets']:
            bracket_content = parts['content_in_brackets']
            # Количество точек + 1 = количество уровней
            # "Сид 1. Принцип талиона 1. Геката 1" → 2 точки = 3 уровня
            parts['bracket_levels'] = bracket_content.count('. ') + 1
        else:
            parts['bracket_levels'] = 0
        
        return parts
    
    @staticmethod
    def analyze_pattern_blocks(pattern: str) -> dict:
        """Разбирает что требует паттерн"""
        
        bracket_section = None
        before_brackets = pattern  # По умолчанию весь паттерн перед скобками
        
        if '(' in pattern and ')' in pattern:
            bracket_start = pattern.find('(')
            bracket_section = pattern[bracket_start:]
            before_brackets = pattern[:bracket_start].strip()
        
        # Определяем требуемое количество уровней в скобках
        # "Series" → 1 уровень
        # "Series. service_words" → 2 уровня
        # "Series. Title. service_words" → 3 уровня
        bracket_levels = 0
        if bracket_section:
            # Считаем точки внутри скобок: "Series. Title. service_words" → 2 точки = 3 уровня
            bracket_levels = bracket_section.count('. ') + 1
        
        reqs = {
            'pattern': pattern,
            'requires_comma': ',' in before_brackets,  # Проверяем только ДО скобок
            'requires_dot': '. ' in before_brackets,   # Проверяем только ДО скобок
            'requires_dash': ' - ' in before_brackets,  # Проверяем только ДО скобок
            'requires_brackets': '(' in pattern,
            'bracket_requires_service_words': 'service_words' in (bracket_section or ''),
            'bracket_complexity': (bracket_section or '').count('.') + 1 if bracket_section else 0,
            'bracket_levels': bracket_levels,  # Количество уровней иерархии требуемое паттерном
        }
        
        return reqs
    
    @staticmethod
    def score_blocks(file_blocks: dict, pattern_reqs: dict) -> int:
        """Оценивает соответствие структур файла и паттерна"""
        
        score = 0
        
        # ════ ПРОВЕРКА ОСНОВНОЙ СТРУКТУРЫ ════
        
        # Скобки
        if pattern_reqs['requires_brackets']:
            if not file_blocks['has_brackets']:
                return -999
            score += 15
        else:
            if not file_blocks['has_brackets']:
                score += 10
        
        # Запятая
        before = file_blocks['before_bracket_parts']
        if pattern_reqs['requires_comma']:
            if not before['has_comma']:
                return -999
            score += 10
        else:
            if before['has_comma']:
                score -= 5
            else:
                score += 10
        
        # Точка
        if pattern_reqs['requires_dot']:
            if not before['has_dot']:
                return -999
            score += 10
        else:
            if before['has_dot']:
                score -= 3
            else:
                score += 8
        
        # Тире
        if pattern_reqs['requires_dash']:
            if not before['has_dash']:
                return -999
            score += 10
        else:
            if not before['has_dash']:
                score += 10
        
        # ════ ПРОВЕРКА СОДЕРЖИМОГО СКОБОК ════
        
        if file_blocks['has_brackets'] and pattern_reqs['requires_brackets']:
            # ════ ПРОВЕРКА СОВПАДЕНИЯ ИЕРАРХИИ ════
            # Количество уровней в файле должно совпадать с требуемым паттерном
            # Но это не hard disqualifier - просто штраф в score
            file_levels = file_blocks.get('bracket_levels', 0)
            pattern_levels = pattern_reqs['bracket_levels']
            
            # НАКАЗЫВАЕМ за несовпадение иерархии:
            # файл с 3 уровнями не должен совпадать с паттерном на 1 уровень
            levels_diff = abs(file_levels - pattern_levels)
            if levels_diff > 0:
                # Штраф -5 за каждый уровень разницы
                score -= (5 * levels_diff)
            else:
                # Бонус за совпадение иерархии
                score += 10
            
            bracket_content = file_blocks['content_in_brackets'] or ''
            
            # Проверяем наличие служебных слов (Дилогия, Тетралогия и т.д.), но НЕ числовых диапазонов!
            has_service_word = False
            # Служебные слова: полные слова, не часть другого слова
            service_word_patterns = r'\b(Дилогия|Трилогия|Тетралогия|Пенталогия|Цикл|Серия)\b'
            has_service_word = bool(re.search(service_word_patterns, bracket_content, re.IGNORECASE))
            
            if pattern_reqs['bracket_requires_service_words']:
                if has_service_word:
                    score += 5
                else:
                    # Паттерн требует service_words, но их нет
                    score -= 5
            else:
                # Паттерн НЕ требует service_words
                if has_service_word:
                    # В файле есть, но паттерн не ожидает
                    score -= 3
                else:
                    # Паттерн не ожидает, и их нет
                    score += 5
            
            # Сложность: паттерн требует определённое кол-во уровней точками
            file_complexity = bracket_content.count('.') + 1
            pattern_complexity = pattern_reqs['bracket_complexity']
            
            if file_complexity != pattern_complexity:
                # Штраф за несоответствие сложности
                score -= abs(file_complexity - pattern_complexity) * 3
        
        return score


class Pass2SeriesFilename:
    """Извлечение серий из имён файлов."""
    
    def __init__(self, logger: Logger = None, male_names: set = None, female_names: set = None):
        self.logger = logger or Logger()
        self.settings = SettingsManager('config.json')
        self.block_selector = BlockLevelPatternSelector()
        self.male_names = male_names or set()
        self.female_names = female_names or set()
        # Create block matcher with known author names
        self.block_matcher = BlockLevelPatternMatcher(
            service_words=list(self.settings.get_list('service_words')),
            male_names=self.male_names,
            female_names=self.female_names
        )  # NEW: для точного извлечения серий
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
        ПРОСТАЯ И ПРАВИЛЬНАЯ ЛОГИКА - независима от папок!
        ===================================================
        Логика:
        1. Если series_source == "folder_dataset" → skip (папка дала series)
        2. Если proposed_series не пусто → skip (уже выбрана)  
        3. ВСЕГДА пробовать паттерны (неважно file_depth!)
        4. Fallback на metadata только если паттерны не дали
        """
        for record in records:
            # Special case: depth==4 without series subfolder
            # Pass 1 wrongly sets folder_dataset for depth==4, allowing Pass 2 to override it
            file_depth = len(Path(record.file_path).parts)
            is_depth4_without_real_series = (
                file_depth == 4 and 
                record.series_source == "folder_dataset"
            )
            
            if record.series_source == "folder_dataset" and not is_depth4_without_real_series:
                continue  # Папка дала series (кроме depth==4 ошибки)
            
            if record.proposed_series and not is_depth4_without_real_series:
                continue  # Серия уже установлена (кроме depth==4 ошибки)
            
            # ОБЯЗАТЕЛЬНО пробуем паттерны (глубина НЕ влияет!)
            series_candidate = self._extract_series_from_filename(
                record.file_path, validate=False, metadata_series=record.metadata_series
            )
            
            if series_candidate:
                record.extracted_series_candidate = series_candidate
                
                # Базовые фильтры (НЕ валидация)
                if ',' in series_candidate:
                    series_candidate = None  # Список авторов
                elif self._is_author_surname(series_candidate, record.proposed_author):
                    series_candidate = None  # Фамилия
            
            # Если прошел базовые фильтры → валидация
            if series_candidate:
                clean = self._clean_series_name(
                    series_candidate, 
                    keep_trailing_number=self._last_was_hierarchical
                )
                author_for_validation = record.proposed_author or None
                
                if self._is_valid_series(clean, extracted_author=author_for_validation):
                    record.proposed_series = clean
                    record.series_source = "filename"
                    continue
            
            # Fallback: metadata ТОЛЬКО если паттерны не дали
            if record.metadata_series:
                series = self._extract_series_from_metadata(record.metadata_series.strip())
                author_for_validation = record.proposed_author or None
                if self._is_valid_series(series, extracted_author=author_for_validation):
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
                'bracket_parts': int,        # Количество частей в скобках (по '. ')
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
            'bracket_parts': 0,
            'has_dots': 0,
            'has_dash': False,
            'dashes': 0,
            'parts_count': 0,
        }
        
        # Проверяем скобки - ищем ПОСЛЕДНИЕ скобки в строке
        # (они могут быть в конце или в середине, если потом идет дополнительный текст)
        # Примеры:
        # "Авраменко Александр - Солдат удачи (Солдат удачи. Тетралогия).fb2" → скобки в конце ✓
        # "Посняков Андрей - Вещий князь (Вещий князь 1-4) Др. издание.fb2" → скобки в середине ✓
        bracket_match = re.search(r'\(([^)]+)\)', filename)
        if bracket_match:
            structure['has_brackets'] = True
            structure['bracket_content'] = bracket_match.group(1)
            # Считаем части внутри скобок (разделены на '. ')
            # "Серия (Точка, Точка)" имеет как '. ' (две точки с пробелом)
            structure['bracket_parts'] = structure['bracket_content'].count('. ') + 1
        
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
    
    def _analyze_pattern_structure(self, pattern_str: str) -> dict:
        """
        Анализировать структуру паттерна и выделить его элементы.
        
        Паттерны имеют вид: "Author - Title (Series. service_words)" и т.д.
        
        Returns:
            {
                'has_brackets': bool,        # Есть ли скобки () в паттерне
                'has_square_brackets': bool, # Есть ли квадратные скобки []
                'bracket_parts': int,        # Сколько частей в скобках (по '. ')
                'has_dash': bool,            # Есть ли " - " в паттерне
                'dashes': int,               # Количество " - "
                'main_parts': int,           # Количество основных блоков вне скобок
            }
        """
        structure = {
            'has_brackets': False,
            'has_square_brackets': False,
            'bracket_parts': 0,
            'has_dash': False,
            'dashes': 0,
            'main_parts': 0,
        }
        
        # Проверяем скобки
        if '(' in pattern_str and ')' in pattern_str:
            structure['has_brackets'] = True
            # Извлекаем содержимое скобок
            bracket_match = re.search(r'\(([^)]+)\)', pattern_str)
            if bracket_match:
                bracket_content = bracket_match.group(1)
                # Считаем части внутри скобок (разделены на '. ')
                # "Series. service_words" → 2 части
                # "Series service_words. SubSeries service_words. SubSubSeries" → 3 части
                structure['bracket_parts'] = bracket_content.count('. ') + 1
        
        # Проверяем квадратные скобки
        if '[' in pattern_str and ']' in pattern_str:
            structure['has_square_brackets'] = True
        
        # Проверяем дефисы
        if ' - ' in pattern_str:
            structure['has_dash'] = True
            structure['dashes'] = pattern_str.count(' - ')
        
        # Считаем основные части (блоки вне скобок)
        # Удаляем содеримое скобок и считаем оставшиеся части
        pattern_without_brackets = re.sub(r'\([^)]*\)', '', pattern_str)
        if ' - ' in pattern_without_brackets:
            structure['main_parts'] = pattern_without_brackets.count(' - ') + 1
        else:
            structure['main_parts'] = 1 if pattern_without_brackets.strip() else 0
        
        return structure
    
    def _structures_match(self, file_structure: dict, pattern_structure: dict) -> bool:
        """
        Сравнить структуру файла со структурой паттерна.
        
        Паттерн подходит файлу если:
        - Both have/don't have brackets
        - If both have brackets: number of parts inside brackets should match
        - Dash count should match
        
        Args:
            file_structure: Результат _analyze_filename_structure()
            pattern_structure: Результат _analyze_pattern_structure()
            
        Returns:
            True если структуры совпадают
        """
        # ОСНОВНОЙ КРИТЕРИЙ: Структуры должны совпадать
        
        # 1. Скобки: beide или обе есть, nebo обе нет
        if file_structure['has_brackets'] != pattern_structure['has_brackets']:
            return False
        
        # 2. Если есть скобки - проверяем, сколько уровней (по точкам внутри скобок)
        # Файл: "Сид 1. Принцип талиона 1. Геката 1" → 2 точки = 3 уровня
        # Паттерн: "Series. SubSeries. SubSubSeries" → две точки, описывает 3 уровня → bracket_parts=3
        if file_structure['has_brackets'] and pattern_structure['has_brackets']:
            # Считаем точки в содеримом скобок файла
            bracket_content = file_structure['bracket_content']
            file_bracket_parts = bracket_content.count('. ') + 1 if bracket_content else 0
            pattern_bracket_parts = pattern_structure['bracket_parts']
            
            # Если в файле есть точки (многоуровневая структура), требуем точное совпадение
            # Например, если файл имеет "Серия 1. Подсерия 2. Подподсерия 3" (3 уровня),
            # паттерн ДОЛЖЕН быть для 3 уровней, а не для 2 уровней
            if file_bracket_parts > 1:
                # Требуем точное совпадение для многоуровневых структур
                if file_bracket_parts != pattern_bracket_parts:
                    return False
            else:
                # Для простых одноуровневых структур допускаем небольшой допуск
                if abs(file_bracket_parts - pattern_bracket_parts) > 1:
                    return False
        
        # 3. Дефисы: количество должно совпадать (или быть близко)
        if abs(file_structure['dashes'] - pattern_structure['dashes']) > 1:
            return False
        
        return True
    
    def _extract_series_from_filename(self, file_path: str, validate: bool = True, metadata_series: str = "") -> str:
        """
        Извлечь серию из имени файла, используя паттерны из конфига.
        
        ОБНОВЛЕНО: Теперь использует BlockLevelPatternMatcher для точного извлечения!
        + ДОБАВЛЕНО: Подтверждение результата с помощью metadata_series
        
        Применяет (в порядке приоритета):
        1. BlockLevelPatternMatcher (структурный анализ блоков) + подтверждение metadata
        2. Паттерны из конфига (author_series_patterns_in_files)
        3. [Серия] - квадратные скобки в начале
        4. Серия (лат. буквы/цифры) - скобки в конце с сервис-словами
        5. Серия. Название - точка как разделитель в начале
        
        Args:
            file_path: Путь к файлу
            validate: Если True - проверять валидность; если False - возвращать raw candidate
            metadata_series: Метаинформация о серии из FB2 (для подтверждения результата BlockLevelPatternMatcher)
        """
        filename = Path(file_path).name
        name_without_ext = filename.rsplit('.', 1)[0]
        
        # ВАЖНО: Удалить метатеги из конца filename ПЕРЕД парсингом
        # "(СИ)" - Самиздат/Интернет
        # "(ЛП)" - Лицензионное произведение
        # Эти метатеги не должны влиять на извлечение series
        name_for_parsing = re.sub(r'\s*\([СЛ]И\)\s*$', '', name_without_ext).strip()
        
        # 🔑 Флаг: найден паттерн БЕЗ Series информации
        pattern_found_without_series = False
        
        # ══════════════════════════════════════════════════════════════════
        # ШАГ 1 (NEW): Попробовать BlockLevelPatternMatcher 🎯
        # ══════════════════════════════════════════════════════════════════
        try:
            series_from_block = None
            file_patterns = self.settings.get_author_series_patterns_in_files() or []
            
            if file_patterns:
                best_score, best_pattern, _, series_from_block = self.block_matcher.find_best_pattern_match(
                    name_for_parsing, file_patterns
                )
                
                # 🔑 КРИТИЧНО: Проверить что паттерн содержит информацию о серии!
                # Если паттерн не содержит слова "Series", то это не формат с серией
                # Примеры БЕЗ серии: "Title (Author)", "Author - Title", "Author. Title"
                # Примеры С серией: "Title (Author. Series)", "Author - Title (Series)", "Author - Series. Title"
                pattern_str = best_pattern.get('pattern', '') if isinstance(best_pattern, dict) else str(best_pattern or '')
                if 'Series' not in pattern_str:
                    # Паттерн не содержит Series - игнорируем результат BlockLevelPatternMatcher
                    pattern_found_without_series = True  # ← ЗАПОМНИТЬ что паттерн БЕЗ Series!
                    series_from_block = None
                
                # Проверяем что это валидная серия
                if series_from_block and (not validate or self._is_valid_series(series_from_block, skip_author_check=True)):
                    # ✅ ДОБАВЛЕНО: Подтверждение результата с помощью metadata
                    # Если есть metadata_series - проверяем совпадает ли она с найденной
                    if metadata_series:
                        # Очищаем оба значения для сравнения
                        metadata_cleaned = self._extract_series_from_brackets(
                            self._extract_main_series_from_multi_level(metadata_series)
                        ).strip()
                        series_from_block_cleaned = self._extract_main_series_from_multi_level(series_from_block).strip()
                        
                        # Если НЕ совпадают - это сигнал, что BlockLevelPatternMatcher ошибся
                        # Не возвращаем результат, продолжаем со старыми методами
                        if metadata_cleaned.lower() != series_from_block_cleaned.lower():
                            # ВНИМАНИЕ: Результат BlockLevelPatternMatcher не совпадает с metadata!
                            # Это может быть ошибка распознавания (例: "1-2 книги" вместо "Император из стали")
                            # Продолжаем без этого результата
                            pass
                        else:
                            # ✅ Metadata подтвердила результат BlockLevelPatternMatcher!
                            processed_series = self._extract_main_series_from_multi_level(series_from_block)
                            if processed_series:
                                return processed_series
                            return series_from_block
                    else:
                        # Нет metadata для проверки, используем результат BlockLevelPatternMatcher как есть
                        # Обработать через _extract_main_series_from_multi_level() для удаления номеров томов/иерархии
                        # Examples:
                        #   "Сид 1. Принцип талиона 1. Геката 1" → "Сид\Принцип талиона\Геката"
                        #   "Варлок 1-3" → "Варлок"
                        processed_series = self._extract_main_series_from_multi_level(series_from_block)
                        if processed_series:
                            return processed_series
                        # Не проверяем blacklist для series из блок-матчера, т.к. это надёжный метод
                        return series_from_block
        except Exception as e:
            # Если случится ошибка, продолжаем со старым методом
            pass
        
        # ══════════════════════════════════════════════════════════════════
        # ШАГ 2 (OLD): Резервный метод - старые паттерны
        # ══════════════════════════════════════════════════════════════════
        
        # Анализируем структуру файла один раз
        file_blocks = self.block_selector.analyze_filename_blocks(name_for_parsing)
        
        best_series = None
        best_score = -999
        best_pattern = None
        
        if self.compiled_file_patterns:
            for idx, (pattern_str, compiled_regex, group_names) in enumerate(self.compiled_file_patterns, 1):
                # Проверяем regex совпадение
                match = compiled_regex.match(name_for_parsing)
                if not match:
                    continue
                
                # Извлекаем series из match
                series_candidate = None
                series_group_name = None
                
                # ✅ ДОБАВЛЕНО: Проверить что Title не состоит только из точек (это false-match)
                title_candidate = None
                for g_name in group_names:
                    if 'title' in g_name:
                        title_candidate = match.group(g_name).strip() if g_name in group_names else None
                        break
                
                # Если Title это только точки - skip this pattern (it's a false match)
                if title_candidate and all(c == '.' for c in title_candidate):
                    continue
                
                for g_name in group_names:
                    if 'series' in g_name:
                        series_group_name = g_name
                        break
                
                if series_group_name:
                    raw_series = match.group(series_group_name).strip()
                    
                    # ✅ ДОБАВЛЕНО: Отвергнуть если series это только точки
                    # Это часто бывает false-match когда многоточие в конце файла интерпретируется как разделитель
                    # Пример: "Авраменко Александр - Я не сдаюсь..." → паттерн видит ".." как "Title"
                    if raw_series and all(c == '.' for c in raw_series):
                        # Это только точки, не серия
                        series_candidate = None
                    else:
                        # Применяем соответствующую обработку
                        if 'subseries' in series_group_name or 'subsubseries' in series_group_name:
                            series_candidate = self._extract_main_series_from_multi_level(raw_series)
                        elif 'service_words' in series_group_name or '. ' in raw_series or (raw_series.split() and '-' in raw_series.split()[-1]):
                            series_candidate = self._extract_series_from_brackets(raw_series)
                        else:
                            series_candidate = raw_series
                
                if not series_candidate and '(' in pattern_str and ')' in pattern_str:
                    series_candidate = self._apply_config_pattern(pattern_str, name_for_parsing)
                
                if not series_candidate:
                    continue
                
                # БЛОЧНОЕ СРАВНЕНИЕ: Оцениваем соответствие структур
                pattern_blocks = self.block_selector.analyze_pattern_blocks(pattern_str)
                block_score = self.block_selector.score_blocks(file_blocks, pattern_blocks)
                
                # Валидируем series
                is_valid = not validate or self._is_valid_series(series_candidate, skip_author_check=True)
                
                # Выбираем лучший паттерн
                if is_valid and block_score > best_score:
                    best_series = series_candidate
                    best_score = block_score
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
                # ВАЖНО: проверяем ПОЛНОЕ совпадение целого слова, не подстроку!
                # "СИ" не должна совпадать с "Сид" - это разные слова
                is_blacklisted = False
                for bl_word in self.filename_blacklist:
                    bl_word_lower = bl_word.lower().strip()
                    
                    # Проверяем только полные совпадения целого слова:
                    # 1. Полное совпадение: "Тетралогия" == "Тетралогия"
                    # 2. Слово в начале: "Тетралогия и еще" → "Тетралогия" match
                    # 3. Слово в конце: "что-то Тетралогия" → "Тетралогия" match
                    # 4. Слово в середине: "то Тетралогия то" → "Тетралогия" match
                    # НО НЕ: "СИ" не совпадает с "Сид" (это не целое слово)
                    
                    if (best_series_lower == bl_word_lower or
                        best_series_lower.startswith(bl_word_lower + ' ') or
                        best_series_lower.endswith(' ' + bl_word_lower) or
                        ' ' + bl_word_lower + ' ' in ' ' + best_series_lower + ' '):
                        is_blacklisted = True
                        break
                
                if is_blacklisted:
                    # Это запрещенное слово, игнорируем
                    best_series = None
                else:
                    return best_series
        
        # 🔑 ВАЖНО: Если паттерн явно БЕЗ Series - не применяем fallback правила!
        # Если паттерн "Title (Author)", то в нём НЕТ информации о серии
        # Fallback правила (скобки, точка, и т.д.) не должны использоваться
        if pattern_found_without_series:
            # Паттерн явно БЕЗ серии - возвращаем пусто или metadata (если есть)
            if metadata_series:
                return metadata_series if validate else ""
            return ""
        
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
                
                # 🔑 ПРОВЕРКА: это не должна быть фамилия автора или список авторов!
                # Используем _is_author_surname() для проверки
                # NOTE: В этом контексте record.proposed_author может не быть доступна
                # поэтому мы не можем вызвать _is_author_surname() здесь напрямую
                # ВРЕМЕННОЕ РЕШЕНИЕ: проверяем на точку (инициал), запятую (список авторов) или небольшую длину
                looks_like_author = False
                if ',' in potential_series:
                    # Содержит запятую - это список авторов, не серия
                    looks_like_author = True
                elif '.' in potential_series or (len(potential_series) < 15 and ' ' not in potential_series):
                    # Содержит точку - для русских имён это часто инициал+фамилия
                    # "А.Михайловский" → это явно инициал в скобках
                    # Или просто одно слово менее 15 символов - вероятно фамилия
                    looks_like_author = True
                
                if not looks_like_author and (not validate or self._is_valid_series(potential_series)):
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
            # КЛЮЧЕВОЙ МОМЕНТ: мы уже ПЫТАЛИСЬ с config pattern! 
            # Если config pattern не вернул результат (best_series = None), 
            # то это не работает для этого файла - не нужно возвращать неправильный результат!
            # Лучше вернуть пусто чем неправильно
            if ' - ' in potential_series:
                pass  # Skip: config pattern was first priority, don't fall back to Rule 3
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
                is_skip_keyword = any(kw.lower() in brackets_lower for kw in self.collection_keywords)
                
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
        
        elif pattern == "Author, Author. Title (Series)":
            # "Зурков, Черепнев. Бешеный прапорщик (Бешеный прапорщик 1-3)"
            # Извлекаем Series из скобок
            match = re.search(r'\(\s*([^)]+)\)', filename)
            if match:
                content_in_brackets = match.group(1).strip()
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
    
    def _extract_main_series_from_multi_level(self, content: str) -> str:
        """
        Извлечь иерархию сери из многоуровневой группы.
        
        Обрабатывает паттерны вроде:
        - "Сид 1. Принцип талиона 1. Геката 1" → "Сид\Принцип талиона\Геката"
        - "Сид 1. Принцип талиона 1" → "Сид\Принцип талиона"
        - "Сид 1" → "Сид"
        - "Мир Вечного 2. Вечный. Тетралогия" → "Мир Вечного\Вечный"
        - "След Фафнира. Дилогия + внецикл. роман" → "След Фафнира"
        - "Дракон 1-3" → "Дракон"
        
        Args:
            content: Содержимое группы (может быть Series. SubSeries. SubSubSeries или Series. ServiceWords)
            
        Returns:
            Иерархия серий разделенная backslash (без номеров и без служебных слов)
        """
        if not content:
            return ""
        
        # Служебные слова, которые обозначают конец иерархии серий
        # Используем \b для границ слов, чтобы не путать "Серия Альфа" со служебным "Серия"
        service_words_pattern = r'\b(?:Дилогия|Трилогия|Тетралогия|Пентагония|внецикл|дополнение|прелюдия|эпилог)\b'
        
        # Разделяем по точке+пробел (это разделитель уровней или служебной информации)
        parts = content.split('. ')
        
        if not parts:
            return ""
        
        # Обрабатываем каждую часть
        # "Сид 1" → "Сид"
        # "Принцип талиона 1" → "Принцип талиона"
        # Но ОСТАНАВЛИВАЕМСЯ, когда встречаем служебное слово
        hierarchy = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            
            # Проверяем, содержит ли эта часть служебные слова
            # Если содержит - это КОНЕЦ иерархии, не добавляем дальше
            if re.search(service_words_pattern, part, flags=re.IGNORECASE):
                # Может быть, это последняя часть с номерами и служебными словами
                # Попытаемся извлечь имя серии перед служебным словом
                # "Дилогия + внецикл" - не содержит имена серии, пропускаем
                # "Вечный. Тетралогия" - первая часть "Вечный" уже обработана, останавливаемся
                break
            
            # Ищем только последовательность чисел/диапазонов в конце
            # Удаляем числа, но НЕ служебные слова (они должны остановить процесс)
            series_name = re.sub(
                r'\s*[\d\-\,\–]+\s*$',  # Только числа/диапазоны в конце
                '',
                part
            ).strip()
            
            if series_name:  # Добавляем только непустые части
                hierarchy.append(series_name)
        
        # Объединяем через backslash
        return '\\'.join(hierarchy) if hierarchy else ""

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
        
        # IMMEDIATE CHECK: Если содержимое скобок содержит запятую - это вероятно список авторов, не серия
        if ',' in content:
            # Это список (авторов, соавторов и т.д.), не серия
            return ""
        
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
            all_check_words = self.service_words + self.filename_blacklist + self.collection_keywords
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
        # service_markers используются для проверки последнего слова
        service_markers = self.service_words
        
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
                for sw in self.service_words
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
        # ВАЖНО: Отвергаем ТОЛЬКО если это просто service_word или service_word + число!
        # НЕ отвергаем легитимные названия серий типа "Цикл Скорпиона" или "Серия Огня"!
        # 
        # Примеры что отвергаем ("том 1", "выпуск", "книга 3", "цикл")
        # Примеры что СОХРАНЯЕМ ("Цикл Скорпиона", "Том Риддл", "Серия Огня")
        import re
        for service_word in self.service_words:
            service_word_lower = service_word.lower()
            words = text_lower.split()
            
            if not words:
                continue
            
            first_word = words[0]
            
            # 1. Отвергаем если текст это РОВНО service_word ("том", "выпуск")
            if first_word == service_word_lower and len(words) == 1:
                return False
            
            # 2. Отвергаем если это service_word + число ("том 1", "выпуск 5", "книга 2")
            if first_word == service_word_lower and len(words) >= 2:
                second_word = words[1]
                # Проверяем что второе слово это число, римская цифра или "и" (для "и т.д.")
                if re.match(r'^\d+$', second_word) or \
                   re.match(r'^[IVX]+$', second_word, re.IGNORECASE) or \
                   second_word in ['и', '-']:
                    return False
            
            # 3. Специальная проверка для однобуквенных сокращений типа "т."
            # Отвергаем "т. 1" или "т. " но не "т.сервис-слово-другое"
            if len(service_word_lower) == 1:
                if text_lower.startswith(service_word_lower + '.'):
                    # Это может быть "т. 1" или просто "т."
                    remainder = text_lower[2:].strip()
                    if not remainder or re.match(r'^\d+', remainder):
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
            ("А.Белоус", "Алексей Белоус") → True (сокращенное - инициал + фамилия)
            ("Белоус", "Иванов Сергей") → False (не фамилия)
            ("Солдат удачи", "Авраменко Александр") → False (это серия)
        
        Args:
            series_candidate: Извлеченная серия
            author: Автор в формате "Фамилия Имя" или "Имя Фамилия"
            
        Returns:
            True если series - это фамилия автора
        """
        if not series_candidate or not author:
            return False
        
        author_parts = author.strip().split()
        if not author_parts:
            return False
        
        series_lower = series_candidate.lower()
        series_normalized = re.sub(r'[^\w]', '', series_lower)
        
        # Проверяем КАЖДУЮ часть автора (может быть "Фамилия Имя" или "Имя Фамилия")
        for part in author_parts:
            part_lower = part.lower()
            part_normalized = re.sub(r'[^\w]', '', part_lower)
            
            # Точное совпадение целой части (например: "Белоус" = "Белоус")
            if part_normalized == series_normalized:
                return True
            
            # Для сокращенного формата (А.Фамилия), проверяем совпадение в конце
            # Например: "А.Белоус" содержит "Белоус" (последняя часть после последней точки)
            if '.' in series_lower:
                # Извлекаем последний слог после крайней точки  (А. → А, В.К. → К, Белоус → Белоус)
                # Разбиваем по точке и берем последнюю часть, которая содержит кириллицу
                match = re.search(r'([А-Яа-яЁё]+)\.?$', series_lower)
                if match:
                    surname_part = match.group(1).lower()
                    surname_part_normalized = re.sub(r'[^\w]', '', surname_part)
                    
                    # Проверяем, совпадает ли эта часть с частью автора
                    if part_normalized == surname_part_normalized:
                        return True
        
        return False
    
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
        # это "Author - Series (...)" - нужно проверить ЧТО в скобках!
        # 
        # ПРАВИЛЬНО: "Author - Series (service_word)" 
        #   пример: "Горе победителям (Дилогия)" - в скобках ТОЛЬКО служебное слово
        # 
        # НЕПРАВИЛЬНО: "Author - Title (Series. Details)"
        #   пример: "Заголовок (Серия 1-3)" - в скобках сложная структура
        #
        has_brackets = '(' in filename and ')' in filename
        if pattern == 'Author - Series (service_words)' and has_brackets:
            # Проверяем что находится в скобках
            bracket_match = re.search(r'\(([^)]+)\)\s*$', filename)
            if bracket_match:
                bracket_content = bracket_match.group(1).strip().lower()
                
                # Проверяем наличие сложной структуры (точки, запятые и т.д.)
                has_complex_structure = '.' in bracket_content or ',' in bracket_content
                
                # Проверяем: это ТОЛЬКО service_word (одно слово из списка)?
                is_only_service_word = False
                for sw in self.service_words:
                    if bracket_content == sw.lower():
                        is_only_service_word = True
                        break
                
                if is_only_service_word and not has_complex_structure:
                    # ✓ ПРАВИЛЬНО: в скобках только служебное слово (Дилогия, Трилогия и т.д.)
                    # Это РОВНО соответствует паттерну "Author - Series (service_words)"
                    # Даём БОНУС за правильное распознавание структуры
                    score += 3
                elif has_complex_structure:
                    # ✗ НЕПРАВИЛЬНО: в скобках сложная структура с точками/запятыми
                    # Это структура "Author - Title (info)", не "Author - Series (service_word)"
                    # Штрафуем за неправильный паттерн
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
            "Author - Series (service_words)",  # Добавлен: "Author - Series (service_word)"
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
            # Multi-level series patterns (главная серия. подсерия. подподсерия)
            "Author - Title (Series service_words. SubSeries service_words. SubSubSeries service_words)",
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
