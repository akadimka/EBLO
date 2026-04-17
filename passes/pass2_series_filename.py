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
    from extraction_constants import FILE_EXTENSION_FOLDER_NAMES, is_no_series_folder
except ImportError:
    from ..extraction_constants import FILE_EXTENSION_FOLDER_NAMES, is_no_series_folder


def _author_matches_folder(proposed_author: str, folder_part: str) -> bool:
    """Проверить, является ли folder_part папкой автора proposed_author.

    Обрабатывает:
    - Вхождение строки (быстрый путь)
    - Любое значимое слово автора как подстрока папки (для "Питер Ф. Гамильтон" в "...Гамильтон)")
    - Форму множественного числа фамилии: "Живовы" ↔ "Живов" (startswith)
    - Несколько авторов с союзом "и": "Живовы Георгий и Геннадий" ↔
      "Живов Геннадий, Живов Георгий" (все уникальные фамилии есть в папке)
    """
    if not proposed_author or not folder_part:
        return False

    proposed_lower = proposed_author.lower().replace('ё', 'е')
    folder_lower = folder_part.lower().replace('ё', 'е')

    # Быстрый путь: вхождение строки
    if proposed_lower in folder_lower or folder_lower in proposed_lower:
        return True

    # Дополнительный быстрый путь: любое значимое слово автора (≥4 букв)
    # присутствует как подстрока в имени папки.
    # Это покрывает случай когда автор ещё не нормализован (формат "Имя Фамилия"),
    # а папка содержит "(Питер Гамильтон)" — "гамильтон" найдётся как подстрока.
    for word in proposed_lower.split():
        word = word.strip('.').strip(',')
        if len(word) >= 4 and word in folder_lower:
            return True

    # Извлечь уникальные фамилии (первое слово каждого автора после split по , ;)
    surnames = []
    for author in re.split(r'[,;]', proposed_author):
        words = author.strip().replace('ё', 'е').split()
        if words:
            surnames.append(words[0].lower())
    unique_surnames = list(dict.fromkeys(surnames))
    if not unique_surnames:
        return False

    folder_words = [w for w in re.split(r'[\s,;\-\(\)]+', folder_lower) if w]

    # Каждая уникальная фамилия должна совпадать с хотя бы одним словом папки
    # (startswith для формы мн. числа: живов → живовы)
    for surname in unique_surnames:
        if not any(fw == surname or fw.startswith(surname) for fw in folder_words):
            return False

    return True

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

try:
    from logger import Logger
except ImportError:
    from ..logger import Logger

try:
    from settings_manager import SettingsManager
except ImportError:
    from ..settings_manager import SettingsManager

try:
    from name_normalizer import AuthorName
except ImportError:
    from ..name_normalizer import AuthorName

try:
    from pattern_converter import compile_patterns
except ImportError:
    from ..pattern_converter import compile_patterns

try:
    from block_level_pattern_matcher import BlockLevelPatternMatcher
except ImportError:
    from ..block_level_pattern_matcher import BlockLevelPatternMatcher


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
        self.variant_folder_keywords = [kw.lower() for kw in (self.settings.get_list('variant_folder_keywords') or [])]
        self.service_words = self.settings.get_list('service_words')
        self.filename_blacklist = self.settings.get_list('filename_blacklist')
        # Пользовательский список папок «без серии» (дополняет встроенный NO_SERIES_FOLDER_NAMES)
        self.no_series_names = self.settings.get_no_series_folder_names()
        
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
    
    def _extract_series_from_folder_name(self, folder_name: str) -> str:
        """
        Извлечь название серии из имени папки.
        Убирает ведущие номера ("1. ", "2) " и т.д.)
        и всё перед скобками ("1941 (Иван Байбаков)" → "1941")
        
        Args:
            folder_name: Имя папки
            
        Returns:
            Очищенное название серии
        """
        # Убрать ведущие номера ("1. ", "2) " и т.д.)
        cleaned = re.sub(r'^\d+[\.\)\-]\s+', '', folder_name).strip()
        if cleaned and cleaned != folder_name:
            folder_name = cleaned
        
        # Fallback - всё перед скобками это серия
        match = re.match(r'^(.+?)\s*\([^)]+\)\s*$', folder_name)
        if match:
            folder_name = match.group(1).strip()

        # По правилам русского языка после запятой всегда должен идти пробел
        folder_name = re.sub(r',(\S)', r', \1', folder_name)

        return folder_name.strip()
    
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
        # 🔑 СНАЧАЛА: Распространяем автора из папки-предка ДО основного цикла серий.
        # Это необходимо чтобы основной цикл мог корректно сопоставить папку автора
        # даже для файлов у которых proposed_author был "Соавторство"/"Сборник".
        self._propagate_ancestor_folder_authors(records)

        # Кэш Path.parts: один и тот же file_path встречается в нескольких проходах
        _parts_cache: dict = {}

        def _is_strong_match(author: str, folder: str) -> bool:
            a = author.lower().replace('ё', 'е')
            f = folder.lower().replace('ё', 'е')
            if a in f or f in a:
                return True
            # Handle name-order variation (metadata "Имя Фамилия" vs folder "Фамилия Имя")
            # and multi-author strings: check if all folder words match any single author
            f_words = set(re.sub(r'[^\w]', ' ', f).split())
            if f_words:
                for single_author in re.split(r'[;,]', a):
                    sa_words = set(single_author.strip().split())
                    if sa_words and f_words == sa_words:
                        return True
            return False

        for record in records:
            # Приоритет из config.json: FOLDER_STRUCTURE=3 > FILENAME=2 > FB2_METADATA=1
            # Поиск по папкам применяется всегда, используя любой известный автор:
            # proposed_author (из папки или файла) или metadata_authors (из FB2).
            # Это гарантирует соблюдение приоритета независимо от author_source.
            author_name = record.proposed_author or record.metadata_authors or None
            if author_name:
                path_parts = _parts_cache.get(record.file_path)
                if path_parts is None:
                    raw = Path(record.file_path).parts
                    path_parts = tuple(
                        p for i, p in enumerate(raw)
                        if i == len(raw) - 1 or p.lower() not in FILE_EXTENSION_FOLDER_NAMES
                    )
                    _parts_cache[record.file_path] = path_parts

                author_folder_idx = None
                for i, part in enumerate(path_parts[:-1]):
                    if _is_strong_match(author_name, part):
                        author_folder_idx = i
                        break
                if author_folder_idx is None:
                    for i, part in enumerate(path_parts[:-1]):
                        if _author_matches_folder(author_name, part):
                            author_folder_idx = i
                            break

                if author_folder_idx is not None:
                    i = author_folder_idx
                    part = path_parts[i]
                    # Папка подтвердила автора — если источник был только мета, обновляем
                    if record.author_source == "metadata":
                        record.author_source = "metadata_folder_confirmed"

                    # Найдена папка автора на позиции i
                    # Следующая папка (i+1) это серия (если это не файл)
                    if i + 1 < len(path_parts) - 1:  # -1 чтобы исключить сам файл
                        series_folder = path_parts[i + 1]
                        if not series_folder.endswith('.fb2'):
                            # Папка «Вне серий» / «Без серии» — явный признак отсутствия серии
                            if is_no_series_folder(series_folder, self.no_series_names):
                                record.proposed_series = ""
                                record.series_source = "no_series_folder"

                            # Если подпапка — это "вариант" / "альт. перевод" / "СИ" и т.п.,
                            # она НЕ является названием серии — серия берётся из папки автора.
                            elif self._is_variant_folder(series_folder):
                                series_name = self._extract_series_from_folder_name(part)
                                if series_name:
                                    record.proposed_series = series_name
                                    record.series_source = "folder_hierarchy"

                            else:
                                # Проверяем: папка-автор сама является циклом?
                                # Признак: "Серия (Автор)" — _extract_series_from_folder_name вернёт
                                # что-то отличное от исходного имени папки.
                                author_folder_series = self._extract_series_from_folder_name(part)
                                has_parent_series = (
                                    bool(author_folder_series) and
                                    author_folder_series.strip().lower() != part.strip().lower()
                                )

                                if has_parent_series:
                                    # Б) Иерархия: {цикл}\{N. Подсерия} (без пробелов вокруг разделителя)
                                    # Убираем только суффикс "(Автор)" из подпапки, но СОХРАНЯЕМ
                                    # ведущий номер ("1. ", "2. " и т.д.) для очерёдности чтения.
                                    subfolder_display = re.sub(r'\s*\([^)]*\)\s*$', '', series_folder).strip()
                                    record.proposed_series = f"{author_folder_series}\\{subfolder_display}"
                                else:
                                    # Обычная папка автора → только подсерия (старое поведение)
                                    subseries_name = self._extract_series_from_folder_name(series_folder)
                                    record.proposed_series = subseries_name or series_folder

                                record.series_source = "folder_hierarchy"
                    else:
                        # Папка i содержит автора И является папкой серии одновременно
                        # (формат: "Сборник\Серия (Автор)\Файл.fb2" — нет подпапки серии)
                        # Папка имеет ВЫСШИЙ приоритет. Но если metadata_series — вариация
                        # того же названия (напр. "Барраярский цикл" и "Барраяр"), то
                        # сохраняем более точное название из FB2 тегов.

                        # ЗАЩИТА: "Издательская папка с фамилией" — папка вида
                        # "Fanzon. Наш выбор. Куанг" содержит фамилию автора как ПОСЛЕДНЕЕ слово.
                        # Такие папки — организационные, а не серийные.
                        # Серию ищем сначала по имени файла, мета только подтверждает.
                        # ИСКЛЮЧЕНИЕ: "Серия (Автор)" — фамилия в скобках является лишь дизамбигуатором,
                        # такая папка — это серия; проверяем только хвост БЕЗ скобок.
                        _part_no_parens = re.sub(r'\s*\([^)]*\)\s*$', '', part.strip()).strip()
                        _part_words = re.split(r'[\s.\-]+', _part_no_parens) if _part_no_parens else re.split(r'[\s.\-]+', part.strip())
                        _part_last_word = _part_words[-1].lower().replace('ё', 'е') if _part_words else ''
                        _author_words = set(w.lower().replace('ё', 'е') for w in author_name.split() if len(w) > 2)
                        # Check if ANY word in the folder (>2 chars) matches an author word.
                        # This covers "Таннер А" where the FIRST word "Таннер" is the surname,
                        # not just the last word (the old check only caught endings like "Куанг").
                        _folder_contains_author = any(
                            w.lower().replace('ё', 'е') in _author_words
                            for w in _part_words if len(w) > 2
                        )
                        if _folder_contains_author:
                            pass  # Не устанавливаем серию из папки → идём дальше к filename extraction
                        else:
                            series_name = self._extract_series_from_folder_name(part)
                            if series_name:
                                if record.metadata_series:
                                    meta_l = record.metadata_series.lower().replace('ё', 'е')
                                    folder_l = series_name.lower().replace('ё', 'е')
                                    # Если одно является префиксом другого — это одна серия,
                                    # просто разные формы названия → оставляем более точную.
                                    if not (folder_l.startswith(meta_l) or meta_l.startswith(folder_l)):
                                        # Разные названия → папка имеет высший приоритет
                                        record.proposed_series = series_name
                                        record.series_source = "folder_hierarchy"
                                    else:
                                        # Та же серия, разная форма.
                                        # Если meta_l начинается с folder_l → мета добавляет лишнее
                                        # (напр. "Ацтек (RedDetonator)" vs "Ацтек") → берём folder_name.
                                        # Если folder_l начинается с meta_l → папка добавляет описание
                                        # (напр. "Барраярский цикл" vs "Барраяр") → берём мету.
                                        if meta_l.startswith(folder_l) and len(meta_l) > len(folder_l):
                                            record.proposed_series = series_name
                                        else:
                                            record.proposed_series = record.metadata_series
                                        record.series_source = "folder_metadata_confirmed"
                                else:
                                    record.proposed_series = series_name
                                    record.series_source = "folder_hierarchy"
            
            # Special case: depth==4 without series subfolder
            # Pass 1 wrongly sets folder_dataset for depth==4, allowing Pass 2 to override it
            file_depth = len(Path(record.file_path).parts)
            # Учитываём если в пути есть extension-папки (они прозрачны, не считаются как уровень)
            raw_parts = Path(record.file_path).parts
            file_depth = len(tuple(
                p for i, p in enumerate(raw_parts)
                if i == len(raw_parts) - 1 or p.lower() not in FILE_EXTENSION_FOLDER_NAMES
            ))
            is_depth4_without_real_series = (
                file_depth == 4 and 
                record.series_source == "folder_dataset"
            )
            
            if record.series_source == "folder_dataset" and not is_depth4_without_real_series:
                if record.proposed_series:
                    continue  # Папка дала series (кроме depth==4 ошибки)
            
            if record.series_source == "folder_hierarchy":
                continue  # Иерархия папок определила серию - готово!

            if record.series_source == "no_series_folder":
                continue  # Папка «Вне серий» — серии нет, дальше не ищем

            if record.proposed_series and not is_depth4_without_real_series:
                continue  # Серия уже установлена (кроме depth==4 ошибки)
            
            # ОБЯЗАТЕЛЬНО пробуемы паттерны (глубина НЕ влияет!)
            # Если series уже установлена из папок → пропускаем extraction
            # Но если folder_dataset дал пустую серию — продолжаем extraction из filename
            if record.series_source == "folder_dataset" and record.proposed_series:
                continue  # Folder extraction already set hierarchical series
            
            # Если папка НЕ дала series → пробуем extraction из filename
            series_candidate = self._extract_series_from_filename(
                record.file_path, validate=False, metadata_series=record.metadata_series
            )

            if series_candidate:
                # Базовые фильтры (НЕ валидация) — ДО записи в extracted_series_candidate
                # Запятая-разделитель авторов стоит перед словом с заглавной буквы
                # ("Иванов, Петров"), грамматическая — перед строчной ("Игрок, забравшийся").
                if ',' in series_candidate:
                    # ИСКЛЮЧЕНИЕ: если кандидат совпадает с metadata_series →
                    # запятая является частью настоящего названия серии ("Мы, Мигель Мартинес")
                    _meta_confirms_comma = (
                        record.metadata_series and
                        series_candidate.lower().replace('ё', 'е') ==
                        record.metadata_series.strip().lower().replace('ё', 'е')
                    )
                    if not _meta_confirms_comma:
                        # Считаем это списком авторов только если после каждой запятой
                        # идёт слово с заглавной буквы (или инициал)
                        parts_after_comma = [p.strip() for p in series_candidate.split(',')[1:]]
                        all_capitalized = all(
                            p and (p[0].isupper() or (len(p) >= 2 and p[1] == '.'))
                            for p in parts_after_comma
                        )
                        if all_capitalized:
                            series_candidate = None  # Список авторов
                # ВАЖНО: проверки ниже — независимые (не elif), чтобы срабатывать
                # даже когда кандидат прошёл comma-check (например "о том, как")
                if series_candidate and self._is_author_surname(series_candidate, record.proposed_author):
                    series_candidate = None  # Фамилия или полное имя автора
                if series_candidate and record.file_title:
                    # TITLE-AS-SERIES GUARD: если кандидат совпадает с названием книги,
                    # это ложный матч (например "Книга" в service_words увела нас не туда).
                    # Очищаем file_title от мусора [litres] и сравниваем.
                    import re as _re
                    _title_clean = _re.sub(r'\s*\[.*?\]\s*$', '', record.file_title.strip())
                    # Также убрать (ЛП), (альт. перевод) и т.п. скобочные суффиксы
                    _title_no_parens = _re.sub(r'\s*\([^)]*\)\s*$', '', _title_clean).strip()
                    _cand_lower = series_candidate.lower()
                    _title_lower = _title_clean.lower()
                    _title_np_lower = _title_no_parens.lower()
                    # Прямое совпадение ИЛИ кандидат является началом названия книги
                    # (ловит обрезанные кандидаты типа "Спасение (альт" от "Спасение (альт. перевод)")
                    # ИЛИ кандидат начинается с базового названия (без скобок) — "спасение (альт" startswith "спасение"
                    # ИСКЛЮЧЕНИЕ 1: если кандидат совпадает с metadata_series → это подтверждённая серия,
                    # название книги просто совпадает (1-я книга серии называется так же, как серия)
                    # ИСКЛЮЧЕНИЕ 2: если кандидат явно присутствует в скобках в имени файла —
                    # "(Серый. Трилогия)" → серия "Серый" надёжна даже если title="Серый"
                    # ИСКЛЮЧЕНИЕ 3: если в имени файла кандидат стоит перед номером тома
                    # "Чисто шведские убийства 1. Отпуск в раю" → кандидат явно является серией,
                    # даже если file_title тоже начинается с него (1-я книга = имя серии + подзаголовок)
                    _meta_raw = (record.metadata_series or '').replace('\u2026', '...')
                    _meta_lower = _meta_raw.lower().replace('ё', 'е') if _meta_raw else ''
                    _cand_lower_norm = _cand_lower.replace('ё', 'е').replace('\u2026', '...')
                    _is_confirmed_by_meta = bool(_meta_lower and _cand_lower_norm == _meta_lower)
                    # ИСКЛЮЧЕНИЕ: кандидат является ПРЕФИКСОМ metadata_series
                    # "Воронцов" → metadata "Воронцов. Перезагрузка" → кандидат реальная серия,
                    # title просто начинается с первого слова серии.
                    _is_meta_prefix = bool(
                        _meta_lower and not _is_confirmed_by_meta and
                        (_meta_lower.startswith(_cand_lower_norm + '.') or
                         _meta_lower.startswith(_cand_lower_norm + ' '))
                    )
                    # ИСКЛЮЧЕНИЕ: кандидат = metadata_series + суффикс из служебных слов
                    # "Честное пионерское! Часть" → meta "Честное пионерское!" → кандидат начинается
                    # с подтверждённой серии, хвост — только мусор/служебные слова.
                    # Проверяем: candidates начинается с meta И хвост = только \W + цифры/SW-слова.
                    _is_meta_with_service_suffix = bool(
                        _meta_lower and not _is_confirmed_by_meta and not _is_meta_prefix and
                        _cand_lower_norm.startswith(_meta_lower) and
                        _re.match(r'^[\W\s]*(|(\w+\s*)+)$',
                                  _cand_lower_norm[len(_meta_lower):].strip())
                        and all(
                            w in self.service_words or w.isdigit()
                            for w in _cand_lower_norm[len(_meta_lower):].split()
                            if w.isalpha()
                        )
                    )
                    _fn_stem_lower = Path(record.file_path).stem.lower()
                    _is_in_parens = bool(_re.search(r'\(\s*' + _re.escape(_cand_lower), _fn_stem_lower))
                    # ИСКЛЮЧЕНИЕ 4: серия получена блок-матчером с score=1.0 — это структурное совпадение,
                    # title в FB2 просто совпадает с названием серии (omnibus или 1-я книга)
                    _is_block_matcher_confident = getattr(self, '_last_from_block_matcher', False)
                    # Кандидат + номер в имени файла: "... - Серия N." или "... - Серия N "
                    _is_numbered_series = bool(_re.search(
                        _re.escape(_cand_lower.replace('ё', 'е')) + r'[\s.]+\d+[\s.]',
                        _fn_stem_lower.replace('ё', 'е')
                    ))
                    if not _is_confirmed_by_meta and not _is_meta_prefix and not _is_meta_with_service_suffix and not _is_in_parens and not _is_numbered_series and not _is_block_matcher_confident and (
                       (_title_lower and _cand_lower == _title_lower) or \
                       (_title_np_lower and _cand_lower == _title_np_lower) or \
                       (_title_lower and _title_lower.startswith(_cand_lower) and len(_cand_lower) >= 4) or \
                       # ИСКЛЮЧЕНИЕ: однословный кандидат без подтверждённой metadata_series,
                       # а заголовок начинается с этого слова → это первое слово заголовка, не серия.
                       # Пример: "Куонг Валери Тонг - Бей. Беги. Замри" → candidate="Бей", title="Бей. Беги. Замри"
                       (not record.metadata_series and
                        ' ' not in _cand_lower and
                        _title_lower and _title_lower.startswith(_cand_lower)) or \
                       (_title_np_lower and len(_title_np_lower) >= 4 and _cand_lower.startswith(_title_np_lower)) or \
                       # ИСКЛЮЧЕНИЕ guard: кандидат является хвостом заголовка (subtitle-суффикс).
                       # Пример: candidate="Правдивая история о том, как студентка исчезла у всех на виду"
                       # title="Пропавшая: Исчезновение Лорен Спирер. Правдивая история..."
                       # → title.endswith(candidate) → это подзаголовок, не серия.
                       (_title_lower and _title_lower.endswith(_cand_lower) and len(_cand_lower) >= 10) or \
                       # ИСКЛЮЧЕНИЕ guard: кандидат является подстрокой заголовка (фрагмент в середине).
                       # Пример: candidate="Рязань, год" (блок из "Время умирать. Рязань, год 1237")
                       # title="Время умирать. Рязань, год 1237" → candidate in title → не серия.
                       (_title_lower and _cand_lower in _title_lower and len(_cand_lower) >= 8)):
                        series_candidate = None  # Название книги ≠ серия

                # Сохраняем только если прошёл фильтры (иначе Pass4 может распространить имя автора)
                if series_candidate:
                    record.extracted_series_candidate = series_candidate
            
            # Если прошел базовые фильтры → валидация
            if series_candidate:
                clean = self._clean_series_name(
                    series_candidate, 
                    keep_trailing_number=self._last_was_hierarchical
                )
                
                # ✅ НОВОЕ: Удалить слова из blacklist вместо полного отвергания
                # Пример: "Господин следователь (СИ)" → удаляем "(СИ)" → "Господин следователь"
                clean = self._remove_blacklist_words(clean)
                
                if clean:  # Проверяем что что-то осталось после очистки
                    author_for_validation = record.proposed_author or None
                    
                    if self._is_valid_series(clean, extracted_author=author_for_validation):
                        # ✅ Если extracted series является частью metadata_series
                        # (например "Амур" ⊂ "Амур. Лицом к лицу") → расширяем до полного имени.
                        # Это покрывает серии с точкой в названии, которые токенайзер разбивает.
                        if record.metadata_series:
                            meta_clean = record.metadata_series.strip()
                            meta_lower = meta_clean.lower().replace('ё', 'е')
                            clean_lower_norm = clean.lower().replace('ё', 'е')
                            if (meta_lower != clean_lower_norm and
                                    (meta_lower.startswith(clean_lower_norm + '.') or
                                     meta_lower.startswith(clean_lower_norm + ' ') or
                                     clean_lower_norm in meta_lower)):
                                clean = self._fix_russian_grammar(meta_clean)
                                record.proposed_series = clean
                                record.series_source = "filename+meta_confirmed"
                                continue
                        # Исправляем грамматику русского языка (добавляем запятую перед "что")
                        clean = self._fix_russian_grammar(clean)
                        record.proposed_series = clean
                        record.series_source = "filename"
                        if (record.metadata_series and
                                record.metadata_series.strip().lower() == clean.lower()):
                            record.series_source = "filename+meta_confirmed"
                        continue
            
            # Fallback: metadata ТОЛЬКО если паттерны не дали
            if not series_candidate:
                file_name = Path(record.file_path).stem  # Имя без расширения
                
                # ✅ ВАЖНО: Удалить метатеги из конца чтобы fallback правила работали!
                # "(СИ)" - Самиздат/Интернет
                # "(ЛП)" - Лицензионное произведение
                file_name_for_fallback = re.sub(r'\s*\([СЛ]И\)\s*$', '', file_name).strip()
                
                # Перед fallback к metadata попробуем простое правило: Author. Series RomanNumeral
                # "Яманов Александр. Бесноватый Цесаревич I.fb2" → "Бесноватый Цесаревич"
                if '. ' in file_name_for_fallback:
                    parts = file_name_for_fallback.split('. ', 1)
                    if len(parts) == 2:
                        first_part = parts[0].strip()
                        second_part = parts[1].strip()
                        
                        # Проверяем что первая часть это автор (< 50 символов, без цифр)
                        looks_like_author = (
                            len(first_part) < 50 and
                            not any(digit in first_part for digit in '0123456789')
                        )
                        
                        if looks_like_author:
                            # Диапазон N-M: "Совок 1-5", "Попаданец в Дракона 1-8"
                            match = re.search(r'^(.+?)\s+\d+[-\u2013\u2014]\d+\s*$', second_part)
                            if not match:
                                # Одиночное арабское число: "Охотник 1"
                                match = re.search(r'^(.+?)\s+\d+\s*$', second_part)
                            if not match:
                                # Римские цифры: "Бесноватый Цесаревич I"
                                match = re.search(r'^(.+?)\s+[IVX]+\s*$', second_part)
                            if match:
                                simple_series = match.group(1).strip()
                                _ftitle = (record.file_title or '').lower()
                                _in_title = bool(_ftitle and simple_series.lower() in _ftitle)
                                if not _in_title and self._is_valid_series(simple_series, extracted_author=record.proposed_author):
                                    series_candidate = simple_series
                
                # ✅ НОВОЕ: Попробуем "Author - Series NUM или N-M" паттерн
                # "Шалашов Евгений - Господин следователь 2" → "Господин следователь"
                if not series_candidate and ' - ' in file_name_for_fallback:
                    match = re.match(r'^(.+?)\s*-\s*(.+?)\s+(?:\d+[-\u2013\u2014]\d+|\d+|[IVX]+)\s*$', file_name_for_fallback)
                    if match:
                        first_part = match.group(1).strip()
                        series_part = match.group(2).strip()
                        
                        # Проверяем что первая часть это автор/авторы
                        looks_like_author = (
                            len(first_part) < 50 and
                            not any(digit in first_part for digit in '0123456789')
                        )
                        
                        if looks_like_author:
                            _ftitle = (record.file_title or '').lower()
                            _in_title = bool(_ftitle and series_part.lower() in _ftitle)
                            if not _in_title and self._is_valid_series(series_part, extracted_author=record.proposed_author):
                                series_candidate = series_part
            
            if series_candidate:
                # Из filename extraction найдена серия
                record.extracted_series_candidate = series_candidate
                clean = self._clean_series_name(
                    series_candidate, 
                    keep_trailing_number=self._last_was_hierarchical
                )
                # ✅ НОВОЕ: Удалить слова из blacklist вместо полного отвергания
                clean = self._remove_blacklist_words(clean)
                
                if clean:  # Проверяем что что-то осталось после очистки
                    author_for_validation = record.proposed_author or None
                    
                    if self._is_valid_series(clean, extracted_author=author_for_validation):
                        # Исправляем грамматику русского языка (добавляем запятую перед "что")
                        clean = self._fix_russian_grammar(clean)
                        record.proposed_series = clean
                        record.series_source = "filename"
                        if (record.metadata_series and
                                record.metadata_series.strip().lower() == clean.lower()):
                            record.series_source = "filename+meta_confirmed"
            elif record.metadata_series:
                # ✅ ЗАЩИТА: Перед использованием metadata - проверяем наличие слов из blacklist
                # ТРЕБОВАНИЕ: "если мета содержит слово или слова из BL, полностью ее игнорируем в качестве значения"
                # Пример: "Шедевры фантастики (продолжатели)" содержит "фантастики" → отклоняем целиком
                # ВАЖНО: word-boundary matching, не substring — "попаданец" не должен блокировать
                # легитимное "Попаданец в Дракона" является реальной серией
                meta_lower = record.metadata_series.lower()
                has_blacklist_word = False
                for bl in self.filename_blacklist:
                    bl_lower = bl.lower().strip()
                    if not bl_lower:
                        continue
                    # Для коротких слов (≤3 символа) — word-boundary; для длинных — word-boundary тоже
                    pat = r'(?<![а-яёa-z])' + re.escape(bl_lower) + r'(?![а-яёa-z])'
                    if re.search(pat, meta_lower):
                        has_blacklist_word = True
                        break
                
                if has_blacklist_word:
                    # metadata содержит слова из blacklist → игнорируем целиком, не используем как series
                    pass
                else:
                    # ✅ ДОПОЛНИТЕЛЬНО: Проверяем целиком ли она в blacklist
                    # Пример: "Современный фантастический боевик (АСТ)" → без "(АСТ)" = "Современный фантастический боевик"
                    metadata_base = record.metadata_series.replace(' (АСТ)', '').replace('(АСТ)', '').strip()
                    is_pure_blacklist = any(
                        metadata_base.lower() == bl.lower() 
                        for bl in self.filename_blacklist
                    )
                    
                    if is_pure_blacklist:
                        # Весь metadata это blacklist → пропускаем (series остаётся пустой)
                        pass
                    else:
                        # Fallback к metadata - только если из filename ничего не нашли
                        series = self._extract_series_from_metadata(record.metadata_series.strip())
                        
                        # ✅ Удалить слова из blacklist также из metadata серии
                        series = self._remove_blacklist_words(series)
                        
                        author_for_validation = record.proposed_author or None
                        if series and self._is_valid_series(series, extracted_author=author_for_validation):
                            # Исправляем грамматику русского языка (добавляем запятую перед "что")
                            series = self._fix_russian_grammar(series)
                            record.proposed_series = series
                            
                            # 🔑 Папка уже была проверена выше. Если мы здесь → это просто metadata series (не совпадает с папкой)
                            record.series_source = "metadata"
        
        # 🔑 НОВОЕ: Папочный консенсус
        # Если папка содержит файлы с series_source = "folder_dataset",
        # то ВСЕ файлы в этой папке должны получить одинаковую серию из папки
        self._apply_folder_consensus(records)
        
        # 🔑 УНИФИКАЦИЯ АВТОРА внутри папки
        # Если в папке есть файлы с folder_dataset — их автор применяется ко всем
        # файлам в папке с source='metadata_folder_confirmed' (исправляет файлы
        # с испорченными метаданными, которые не смогли пройти валидацию propagate).
        self._unify_folder_author_source(records)

        # 🔑 УНИФИКАЦИЯ источника серии внутри папки
        # Если хотя бы один файл в папке получил folder_hierarchy — значит папка
        # является авторитетом для всей папки. Все metadata_folder_confirmed файлы
        # в той же папке должны получить folder_hierarchy с той же серией.
        self._unify_folder_series_source(records)

        # (автор из папки уже распространён в начале execute(), до основного цикла)

        # ✅ ПОСЛЕДНИЙ ШАНС: если proposed_series пусто, metadata_series задана,
        # не совпадает с автором и не содержит чисто blacklist-слов — использовать напрямую.
        # Покрывает случаи, когда валидация отвергла серию из-за отсутствия контекста автора
        # или когда имя серии выглядит как формат "(Фамилия (Имя))", но НЕ является автором.
        for record in records:
            if record.proposed_series or not record.metadata_series:
                continue
            meta = record.metadata_series.strip()
            # Пропускаем если значение совпадает с именем автора
            if record.proposed_author and meta.lower() == record.proposed_author.lower():
                continue
            # Word-boundary blacklist check (как в основном блоке)
            meta_lower = meta.lower()
            _has_bl = False
            for bl in self.filename_blacklist:
                bl_lower = bl.lower().strip()
                if not bl_lower:
                    continue
                pat = r'(?<![а-яёa-z])' + re.escape(bl_lower) + r'(?![а-яёa-z])'
                if re.search(pat, meta_lower):
                    _has_bl = True
                    break
            if _has_bl:
                continue
            # Применяем те же серийные паттерны и валидацию что и в основном блоке
            series = self._extract_series_from_metadata(meta)
            series = self._remove_blacklist_words(series)
            if not series:
                continue
            author_for_validation = record.proposed_author or None
            if not self._is_valid_series(series, extracted_author=author_for_validation):
                continue
            series = self._fix_russian_grammar(series)
            # Используем как серию с источником "metadata"
            record.proposed_series = series
            record.series_source = "metadata"

        # ✅ ФИНАЛЬНОЕ: Восстановить парные кавычки во всех series
        # Если в series_кандидате есть открывающиеся кавычки без закрывающихся,
        # автоматически добавляем закрывающиеся
        for record in records:
            if record.proposed_series:
                record.proposed_series = self._balance_quotes(record.proposed_series)
                
                # ✅ ФИНАЛЬНОЕ: Удалить завершающий backslash
                # Некоторые значения могут заканчиваться на "\", это ошибка обработки иерархий
                # Пример: "Мир Алекса Королева\" должно быть "Мир Алекса Королева"
                record.proposed_series = record.proposed_series.rstrip('\\')
        
        # Commented out: folder pattern consensus was also causing issues  
        # self._apply_series_folder_pattern_consensus(records)
        
        # Commented out: consensus logic was overwriting properly extracted series
        # TODO: Review and fix consensus logic before re-enabling
        # self._apply_cross_file_consensus(records)

    def _is_variant_folder(self, folder_name: str) -> bool:
        """Вернуть True если имя подпапки указывает на альтернативную версию текста.

        Примеры: "Вариант с СИ (Ватный Василий)", "Альтернативный перевод",
                 "Черновик (автор)", "ЛП", "СИ" и т.п.
        В таких случаях серия наследуется от родительской папки.
        """
        folder_lower = folder_name.lower().replace('ё', 'е')
        for kw in self.variant_folder_keywords:
            kw_lower = kw.lower()
            # Для коротких ключевых слов (≤3 символа, напр. "ЛП", "СИ", "alt")
            # используем word-boundary, чтобы не срабатывать на подстроки
            # ("си" в "псионик" не должно давать True).
            # Для длинных — простое вхождение достаточно.
            if len(kw_lower) <= 3:
                if re.search(r'(?<![а-яёa-z])' + re.escape(kw_lower) + r'(?![а-яёa-z])',
                             folder_lower):
                    return True
            else:
                if kw_lower in folder_lower:
                    return True
        return False

    def _propagate_ancestor_folder_authors(self, records: List[BookRecord]) -> None:
        """
        Распространение автора из папки-предка на все файлы под ней.

        Принцип: папка — самый надёжный источник автора (100% датасет).
        Если имя любой папки-предка файла парсится как имя автора
        (через folder_author_parser), то все файлы под этой папкой
        получают этого автора с source='folder_dataset'.

        Правила:
        - Используем ВЫСШУЮ (ближе к корню) папку, которая парсится как автор.
        - Файлы с уже установленным author_source='folder_dataset' НЕ трогаем
          (они уже получили правильного автора из Pass 1 или более точного подпути).
        - "и др", "et al." и подобные суффиксы из имени автора убираются.
        - Работает для любых вложенных структур (Коллекция / СерияАвтор / Подсерия / Файл).
        """
        from passes.folder_author_parser import parse_author_from_folder_name

        # Список суффиксов-заменителей соавторов, которые нужно убирать
        _ET_AL_PATTERN = re.compile(
            r'\s*(и\s+др\.?|и\s+другие|et\s+al\.?|and\s+others)\s*$',
            re.IGNORECASE
        )

        def _parse_folder_author(folder_name: str) -> str:
            """Попытаться распознать автора из имени папки, вернуть '' если не удалось."""
            # Быстрая проверка через filename_blacklist — слова издателей/серий.
            # Используем word-boundary matching чтобы короткие записи ("СИ", "ЛП" и т.п.)
            # не давали ложных срабатываний внутри слов (напр. "СИ" в "макСИм").
            folder_lower = folder_name.lower()
            for bl in self.filename_blacklist:
                bl_lower = bl.lower()
                if re.search(r'(?<![а-яёa-z])' + re.escape(bl_lower) + r'(?![а-яёa-z])',
                             folder_lower):
                    return ''
            author = parse_author_from_folder_name(
                folder_name,
                male_names=self.male_names,
                female_names=self.female_names,
            )
            if not author:
                return ''
            # Валидация: убеждаемся что извлечённое имя содержит реальное имя человека.
            # Это отсеивает коллекционные папки вроде «Романы МИФ. Один момент - целая жизнь»,
            # которые parse_author_from_folder_name может неверно распознать как автора.
            # Используем ту же логику что и precache._contains_valid_name, с корректным
            # lookbehind чтобы «Ф» в «МИФ.» не считался инициалом.
            author_valid = False
            # 1. Проверка по спискам имён
            for word in author.split():
                word_clean = word.strip('.,;:!?').lower()
                if word_clean in self.male_names or word_clean in self.female_names:
                    author_valid = True
                    break
            # 2. Паттерн инициала: "А.Фамилия" — инициал не должен быть частью слова (МИ<Ф>)
            if not author_valid:
                if re.search(r'(?<![а-яёА-Я])[А-Я]\.*\s*[А-Я][а-яё]+', author):
                    author_valid = True
            if not author_valid:
                return ''
            # Убираем "и др", "et al." в конце
            author = _ET_AL_PATTERN.sub('', author).strip()
            return author

        propagated = 0
        for record in records:
            if record.author_source == "folder_dataset":
                continue  # Уже точно определён — не трогаем

            path_parts = Path(record.file_path).parts[:-1]  # все папки без самого файла
            # Прозрачно исключаем технические папки (fb2, epub и т.п.)
            path_parts = tuple(
                p for p in path_parts
                if p.lower() not in FILE_EXTENSION_FOLDER_NAMES
            )

            # Идём от корня (самая высокая папка) к файлу, останавливаемся на первом совпадении
            for part in path_parts:
                parsed_author = _parse_folder_author(part)
                if parsed_author:
                    # ВАЛИДАЦИЯ ПРОТИВ МЕТАДАННЫХ: если у файла есть metadata_authors,
                    # проверяем что хотя бы одно слово из parsed_author присутствует в мете.
                    # Это отсекает ложные «авторы» вроде «Питер» (издательство в скобках),
                    # когда мета однозначно указывает на других людей.
                    # ВАЛИДАЦИЯ ПРОТИВ МЕТАДАННЫХ пропускается когда мета содержит только
                    # коллективный термин («Соавторство», «Сборник» и т.п.) — папка является
                    # единственным авторитетным источником в таких случаях.
                    _COLLECTIVE_TERMS = {"соавторство", "сборник", "[unknown]", "коллектив авторов"}
                    _meta_is_collective = (
                        record.metadata_authors and
                        record.metadata_authors.strip().lower().replace('ё', 'е') in _COLLECTIVE_TERMS
                    )
                    _proposed_is_collective = (
                        record.proposed_author and
                        record.proposed_author.strip().lower().replace('ё', 'е') in _COLLECTIVE_TERMS
                    )
                    if record.metadata_authors and not _meta_is_collective and not _proposed_is_collective:
                        author_words = set(parsed_author.lower().split())
                        meta_words = set(re.sub(r'[;,]', ' ', record.metadata_authors.lower()).split())
                        if author_words and meta_words and not (author_words & meta_words):
                            break  # Папка не подтверждена метой — не перезаписываем
                    if parsed_author != record.proposed_author or record.author_source != "folder_dataset":
                        record.proposed_author = parsed_author
                        record.author_source = "folder_dataset"
                        propagated += 1
                    break  # Высшая папка найдена — дальше не ищем

        if propagated:
            self.logger.log(f"[PASS 2 Series] Propagated ancestor folder author to {propagated} records")

    def _unify_folder_author_source(self, records: List[BookRecord]) -> None:
        """
        Унификация автора внутри одной папки по аналогии с _unify_folder_series_source.

        Правило: если хотя бы один файл в папке получил author_source='metadata_folder_confirmed',
        значит папка подтвердила автора. Все остальные файлы в той же папке, у которых
        author_source='metadata' (но ещё не подтверждён папкой), получают того же автора
        с source='metadata_folder_confirmed'.
        """
        from collections import defaultdict

        folder_groups = defaultdict(list)
        for record in records:
            folder_groups[str(Path(record.file_path).parent)].append(record)

        for folder, group in folder_groups.items():
            # Ищем файлы, подтверждённые папкой
            # Наивысший приоритет: folder_dataset — явно распознанная папка автора.
            # Если в папке есть хотя бы один такой файл, используем его автора как канонического.
            folder_dataset_records = [
                r for r in group
                if r.author_source == "folder_dataset" and r.proposed_author
            ]
            confirmed_records = [
                r for r in group
                if r.author_source == "metadata_folder_confirmed" and r.proposed_author
            ]
            if folder_dataset_records:
                # Большинство среди folder_dataset
                author_counts: dict = {}
                for r in folder_dataset_records:
                    author_counts[r.proposed_author] = author_counts.get(r.proposed_author, 0) + 1
                canonical_author = max(author_counts, key=author_counts.get)
            else:
                # Fallback: большинство среди metadata_folder_confirmed
                if not confirmed_records:
                    continue
                author_counts = {}
                for r in confirmed_records:
                    author_counts[r.proposed_author] = author_counts.get(r.proposed_author, 0) + 1
                canonical_author = max(author_counts, key=author_counts.get)

            # Применяем ко всем файлам в папке с source='metadata', 'metadata_folder_confirmed'
            # или 'filename' (если канонический автор из folder_dataset или из большинства
            # metadata_folder_confirmed — это тоже авторитетный источник).
            # folder_dataset не трогаем — они уже точно определены.
            # 'filename': автор мог быть ошибочно извлечён из имени файла (напр. из названия
            # серии в паттерне "Серия - Подсерия"), переопределяем авторитетным источником.
            _overrideable = {"metadata", "metadata_folder_confirmed"}
            if folder_dataset_records or confirmed_records:
                _overrideable.add("filename")
            for record in group:
                if record.author_source in _overrideable and record.proposed_author:
                    record.proposed_author = canonical_author
                    record.author_source = "metadata_folder_confirmed"

    def _unify_folder_series_source(self, records: List[BookRecord]) -> None:
        """
        Унификация series_source внутри одной папки.

        Правило: папка — единица доверия. Если хотя бы один файл в папке получил
        series_source='folder_hierarchy', значит именно папка является источником
        серии для ВСЕЙ папки. Все остальные файлы в папке получают ту же серию,
        если только у них нет собственного folder_hierarchy/folder_dataset источника
        с другой серией.

        ИСКЛЮЧЕНИЕ: если в папке файлы от НЕСКОЛЬКИХ авторов — это коллекция,
        унификация не применяется (иначе имя коллекции становится «серией»).
        """
        from collections import defaultdict

        folder_groups = defaultdict(list)
        for record in records:
            folder_groups[str(Path(record.file_path).parent)].append(record)

        for folder, group in folder_groups.items():
            # Если в папке файлы от нескольких авторов → коллекция, пропускаем
            authors_in_folder = {r.proposed_author.strip() for r in group if r.proposed_author}
            if len(authors_in_folder) > 1:
                continue

            # Ищем файлы, у которых папка переопределила мету (авторитетные источники).
            # folder_metadata_confirmed также считается авторитетным: папка и мета согласны.
            STRONG_SOURCES = {"folder_hierarchy", "folder_dataset", "folder_metadata_confirmed"}
            folder_hierarchy_records = [
                r for r in group
                if r.series_source in STRONG_SOURCES and r.proposed_series
            ]
            if not folder_hierarchy_records:
                continue

            # Каноническая серия — из авторитетных источников (мажоритарное голосование)
            series_counts: dict = {}
            for r in folder_hierarchy_records:
                series_counts[r.proposed_series] = series_counts.get(r.proposed_series, 0) + 1
            canonical_series = max(series_counts, key=series_counts.get)

            # Применяем ко ВСЕМ файлам в папке, у которых источник не является авторитетным.
            for record in group:
                if record.series_source not in STRONG_SOURCES:
                    record.proposed_series = canonical_series
                    record.series_source = "folder_hierarchy"

    def _apply_folder_consensus(self, records: List[BookRecord]) -> None:
        """
        Папочный консенсус: если папка содержит файлы с series_source = "folder_dataset",
        то ВСЕ файлы в этой папке должны получить одинаковую серию.
        
        ВАЖНО: Применяется ТОЛЬКО к папкам ОДНОГО автора!
        Если папка содержит файлы РАЗНЫХ авторов → это коллекция, consensusне применяется.
        
        Логика:
        1. Группируем файлы по папке (parent directory)
        2. Проверяем: все ли файлы от ОДНОГО автора? Если нет → skip (это коллекция)
        3. Ищем файлы с series_source = "folder_dataset"
        4. Берем серию из первого такого файла (обычно это название папки)
        5. Применяем эту серию ко ВСЕМ остальным файлам в папке
        
        Пример коллекции (skip consensus):
        Папка: "Боевая фантастика. Циклы"
        - Авраменко. Цикл «Солдат удачи» (АВТОР: Авраменко) 
        - Анисимов. Цикл «Вариант «Бис» (АВТОР: Анисимов) ← РАЗНЫЕ АВТОРЫ!
        → Consensus NOT applied (это коллекция)
        
        Пример папки-серии (apply consensus):
        Папка: "Авраменко Александр/Солдат удачи"
        - 1. Солдат удачи (АВТОР: Авраменко)
        - 2. Князь Терранский (АВТОР: Авраменко) ← ОДИН АВТОР!
        - 3. Взор Тьмы (АВТОР: Авраменко)
        → Consensus applied
        """
        from collections import defaultdict
        
        # Группируем файлы по папке
        folder_files = defaultdict(list)
        for record in records:
            folder_path = str(Path(record.file_path).parent)
            folder_files[folder_path].append(record)
        
        # Для каждой папки применяем консенсус
        for folder_path, files_in_folder in folder_files.items():
            # ПРОВЕРКА 1: все ли файлы в папке от ОДНОГО автора?
            # Извлекаем уникальные авторов в этой папке
            authors_in_folder = set()
            for f in files_in_folder:
                if f.proposed_author:
                    # Нормализуем для сравнения (без разрывов строк и пробелов)
                    author = f.proposed_author.strip()
                    if author:
                        authors_in_folder.add(author)
            
            # Если авторов больше одного → это коллекция, skip consensus
            if len(authors_in_folder) > 1:
                continue
            
            # Ищем файлы с series_source = "folder_dataset"
            folder_dataset_files = [
                f for f in files_in_folder 
                if f.series_source == "folder_dataset" and f.proposed_series
            ]
            
            if not folder_dataset_files:
                continue  # В этой папке нет файлов с folder_dataset
            
            # Берем серию из первого файла (они должны быть одинаковые)
            canonical_series = folder_dataset_files[0].proposed_series
            
            # Применяем эту серию ко ВСЕМ файлам в папке
            for record in files_in_folder:
                if record.series_source != "folder_dataset":
                    # Переопределяем серию на основе папочного консенсуса
                    record.proposed_series = canonical_series
                    record.series_source = "folder_dataset"

        # ДОПОЛНИТЕЛЬНЫЙ КОНСЕНСУС: папки с metadata-серией.
        # Если большинство файлов одного автора в папке имеют одинаковую серию
        # из любого источника — применяем её к аутсайдерам (файлам с другой серией).
        # Это исправляет случаи когда часть файлов имеет правильную серию из metadata,
        # а остальные — издательскую мета-серию («Военная фантастика (АСТ)»).
        for folder_path, files_in_folder in folder_files.items():
            if len(files_in_folder) < 2:
                continue
            authors_in_folder = {f.proposed_author.strip() for f in files_in_folder if f.proposed_author}
            if len(authors_in_folder) > 1:
                continue  # Разные proposed_author — не трогаем
            # Главное правило: если в папке книги РАЗНЫХ реальных авторов —
            # это жанровая коллекция или издательская серия, а не авторская серия.
            # Имя папки (например, «МИФ Проза», «Клуб убийств») = ярлык, не серия.
            # Проверяем metadata_authors, т.к. folder_dataset назначает имя папки
            # как proposed_author для всех файлов, маскируя реальное разнообразие.
            real_meta_authors = {
                f.metadata_authors.strip()
                for f in files_in_folder
                if f.metadata_authors and f.metadata_authors.strip() not in ('[unknown]', '')
            }
            if len(real_meta_authors) > 1:
                continue  # Многоавторная коллекция — не трогаем
            # Считаем голоса за каждую серию (источниками выше metadata)
            from collections import Counter
            series_votes = Counter(
                f.proposed_series
                for f in files_in_folder
                if f.proposed_series and f.series_source != "folder_dataset"
            )
            if not series_votes:
                continue
            top_series, top_count = series_votes.most_common(1)[0]
            if top_count <= 1:
                continue
            # Нормализованная база top_series для сравнения
            import re as _re_ac
            def _norm_base(s: str) -> str:
                s = _re_ac.sub(r'\s*\([^)]*\)\s*$', '', s).strip()
                s = _re_ac.sub(r'\s*\[[^\]]*\]\s*$', '', s).strip()
                s = _re_ac.sub(r'\s+\d+[\s\.\:].*$', '', s).strip()
                s = _re_ac.sub(r'\s+\d+\s*$', '', s).strip()
                return s.lower().replace('ё', 'е')
            top_base = _norm_base(top_series)
            # Применяем только к файлам без серии или с низкоприоритетным источником.
            # Не трогаем то, что уже надёжно определено из имени файла.
            for record in files_in_folder:
                if record.proposed_series != top_series:
                    if record.series_source not in ('filename', 'filename+meta_confirmed'):
                        # Не навязываем серию файлу, у которого нет metadata_series —
                        # он скорее всего не принадлежит этой серии (просто тот же автор).
                        if not record.metadata_series:
                            continue
                        # Не навязываем серию если metadata_series указывает на ДРУГУЮ серию.
                        if _norm_base(record.metadata_series) != top_base:
                            continue
                        record.proposed_series = top_series
                        record.series_source = "author-consensus"
                    else:
                        # Файл уже имеет серию из имени файла.
                        # Исправляем если его серия является суффиксом/частью top_series —
                        # это признак того, что парсер обрезал префикс через " - ".
                        # Пример: "Миха" ⊂ "Я - Миха" → исправить до "Я - Миха".
                        rec_series = (record.proposed_series or '').lower().replace('ё', 'е')
                        top_lower = top_series.lower().replace('ё', 'е')
                        if (rec_series and rec_series != top_lower
                                and top_lower.endswith(rec_series)
                                and not record.metadata_series):
                            record.proposed_series = top_series
                            record.series_source = "author-consensus"

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
                                best_candidate = self._fix_russian_grammar(best_candidate)
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
                        candidate_metadata = self._fix_russian_grammar(candidate['metadata'])
                        record.proposed_series = candidate_metadata
                        record.series_source = "metadata"
                    # Иначе применяем найденные слова
                    elif common_words:
                        common_words = self._fix_russian_grammar(common_words)
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
        # "(др. изд.)" / "(другое издание)" - ссылки на другое издание
        # Эти метатеги не должны влиять на извлечение series
        name_for_parsing = re.sub(r'\s*\([СЛ]И\)\s*$', '', name_without_ext).strip()
        name_for_parsing = re.sub(r'\s*\([^)]*(?:издание|изд\.)[^)]*\)\s*$', '', name_for_parsing, flags=re.IGNORECASE).strip()
        

        
        # 🔑 Флаг: найден паттерн БЕЗ Series информации
        pattern_found_without_series = False
        # 🔑 Флаг: блок-матчер нашёл серию с высокой уверенностью (score=1.0)
        # При таком score title-as-series guard не должен отбрасывать результат
        block_matcher_high_confidence = False
        self._last_from_block_matcher = False
        
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
                    # Но сначала отбрасываем metadata_series если это blacklist-слово (издатель/серия-обёртка)
                    _effective_metadata_series = metadata_series.replace('\u2026', '...') if metadata_series else metadata_series
                    if _effective_metadata_series and self.filename_blacklist:
                        _ms_lower = _effective_metadata_series.lower()
                        if any(bl.lower() in _ms_lower for bl in self.filename_blacklist):
                            _effective_metadata_series = None
                    if _effective_metadata_series:
                        # Очищаем оба значения для сравнения
                        metadata_cleaned = self._extract_series_from_brackets(
                            self._extract_main_series_from_multi_level(_effective_metadata_series)
                        ).strip()
                        series_from_block_cleaned = self._extract_main_series_from_multi_level(series_from_block).strip()
                        
                        # Если НЕ совпадают - это сигнал, что BlockLevelPatternMatcher ошибся
                        # Не возвращаем результат, продолжаем со старыми методами
                        if metadata_cleaned.lower() != series_from_block_cleaned.lower():
                            # Проверяем: может metadata совпадает с КОМПОНЕНТОМ иерархии
                            # Пример: metadata="Хроники Кайлара", hierarchy="Кодекс ка'кари\Хроники Кайлара"
                            hierarchy_components = [c.strip().lower() for c in series_from_block_cleaned.split('\\') if c.strip()]
                            if metadata_cleaned.lower() in hierarchy_components:
                                # ✅ Metadata подтвердила один уровень иерархии
                                # Если metadata = ROOT компонент → возвращаем только root (безопасно)
                                # Если metadata = более глубокий уровень → полная цепочка подтверждена
                                # Пример (root): metadata="Третий Рим", hierarchy="Третий Рим\Последний натиск..."
                                #   → root подтверждён, но subseries не подтверждена → вернуть "Третий Рим"
                                # Пример (deep): metadata="Хроники Кайлара", hierarchy="Кодекс ка'кари\Хроники Кайлара"
                                #   → глубокий уровень подтверждён → вернуть полную цепочку
                                if series_from_block_cleaned:
                                    root_cmp = hierarchy_components[0] if hierarchy_components else ''
                                    if metadata_cleaned.lower() == root_cmp:
                                        # Root совпадает → subseries не подтверждена, возвращаем только root
                                        return series_from_block_cleaned.split('\\')[0].strip()
                                    else:
                                        return series_from_block_cleaned
                            elif best_score >= 0.85 and series_from_block_cleaned:
                                # Высокий score, но metadata не подтвердила иерархию
                                # Без подтверждения subseries опасно — возвращаем только root
                                # Пример: metadata="Джони" (мусор), hierarchy="Флибер\Другая жизнь" → "Флибер"
                                if '\\' in series_from_block_cleaned:
                                    root = series_from_block_cleaned.split('\\')[0].strip()
                                    if root:
                                        return root
                                return series_from_block_cleaned
                            # ВНИМАНИЕ: Результат BlockLevelPatternMatcher не совпадает с metadata!
                            # Это может быть ошибка распознавания (例: "1-2 книги" вместо "Император из стали")
                            # Продолжаем без этого результата
                        else:
                            # ✅ Metadata подтвердила результат BlockLevelPatternMatcher!
                            processed_series = self._extract_main_series_from_multi_level(series_from_block)
                            if processed_series:
                                return processed_series
                            # processed_series пуст (напр. аббревиатура О.Р.З.) → не возвращаем сырое значение
                    else:
                        # Нет metadata для проверки, используем результат BlockLevelPatternMatcher как есть
                        # Обработать через _extract_main_series_from_multi_level() для удаления номеров томов/иерархии
                        # Examples:
                        #   "Сид 1. Принцип талиона 1. Геката 1" → "Сид\Принцип талиона\Геката"
                        #   "Варлок 1-3" → "Варлок"
                        processed_series = self._extract_main_series_from_multi_level(series_from_block)
                        if processed_series:
                            # Без metadata нельзя подтвердить многоуровневую иерархию.
                            # Исключение: паттерн явно содержит SubSeries — иерархия описана
                            # намеренно, доверяем всей строке даже без подтверждения metadata.
                            # Пример: "Author - Series. SubSeries (service_words)" при score=1.0
                            pattern_has_subseries = 'SubSeries' in pattern_str
                            if '\\' in processed_series and not pattern_has_subseries:
                                root = processed_series.split('\\')[0].strip()
                                if root:
                                    processed_series = root
                            # Mark: this result came from block matcher with high confidence (score=1.0)
                            # so title-as-series guard in caller should not discard it
                            self._last_from_block_matcher = (best_score >= 0.99)
                            return processed_series
                        # processed_series пуст → аббревиатура или мусор, не возвращаем сырое значение
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

                # Если Title начинается с "- " — паттерн захватил разделитель автор/название
                # как часть Title; это признак ложного совпадения (напр. К.Дж. → Series="Дж", Title="- Доминион")
                if title_candidate and title_candidate.startswith(('- ', '– ', '— ')):
                    continue

                for g_name in group_names:
                    if 'series' in g_name:
                        series_group_name = g_name
                        break
                
                # ✅ ЗАЩИТА: Если паттерн содержит service_words группу,
                # проверить что захваченное значение — действительно служебное слово.
                # Иначе паттерн "Author. service_words «Series»" сработает на любом тексте
                # перед «», например "Легенда о «Ночном дозоре»" → service_words="Легенда о" (не служебное!)
                if 'service_words' in group_names:
                    try:
                        sw_value = match.group('service_words').strip().rstrip('.').strip()
                        sw_value_lower = sw_value.lower()
                        is_real_service_word = any(
                            sw_value_lower == sw.lower() or sw_value_lower.startswith(sw.lower())
                            for sw in self.service_words
                        )
                        if not is_real_service_word:
                            continue  # "Легенда о" — не служебное, пропустить этот паттерн
                    except IndexError:
                        pass

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
                            # Structural check: if pattern expects "Series. service_words" (dot inside parens),
                            # the captured value must also contain a dot. Otherwise the filename structure
                            # doesn't match the pattern — e.g. "(весь цикл)" has no dot, so it can't be
                            # "Series. service_words" — skip this pattern.
                            if 'service_words' in series_group_name and '.' not in raw_series:
                                series_candidate = None
                                continue
                            series_candidate = self._extract_series_from_brackets(raw_series)
                        else:
                            series_candidate = raw_series
                
                if not series_candidate and '(' in pattern_str and ')' in pattern_str:
                    series_candidate = self._apply_config_pattern(pattern_str, name_for_parsing)
                
                # 🔑 НОВОЕ: Отвергнуть если series это только цифры (скорее всего год, не серия)
                # "2021", "2020", "1999" → отвергаем, это годы
                # "Год 2021" → оставляем, это может быть название серии
                if series_candidate and series_candidate.strip().isdigit():
                    # Это только цифры - скорее всего год, не название серии!
                    series_candidate = None
                
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
        
        # 🔑 ВАЖНО: Если паттерн явно БЕЗ Series - не применяем fallback правила скобок/точки!
        # НО: если в конце имени файла явный числовой суффикс (N или N-M), это признак серии —
        # Rule 3B/4 должны попробовать его найти независимо от паттерна.
        _has_numeric_suffix = bool(re.search(r'\s+\d+(?:[-–—]\d+)?\s*$', name_for_parsing))
        if pattern_found_without_series and not _has_numeric_suffix:
            # Паттерн явно БЕЗ серии и нет числового суффикса — возвращаем пусто или metadata
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
            # Ищем ПЕРВУЮ пару скобок (не последнюю!) - используем lookahead
            # При двойных скобках (Series) (Year) нужно взять (Series), не (Year)
            match = re.search(r'\(([^)]+)\)(?:\s*\(|\s*$)', name_for_parsing)
            if match:
                content_in_brackets = match.group(1).strip()
                
                # 🔑 КРИТИЧНО: Проверить если это ТОЛЬКО одно слово
                # Скобки с одним словом это обычно подтитулы или метаинформация: (Наследник), (Король), (СИ)
                # Это НЕ основные названия серий - серии это обычно многословные: "Солдат Удачи", "Боевая Фантастика"
                # Исключение: если одно слово явно часть паттерна с точками/запятыми - обработать
                is_single_word_brackets = ' ' not in content_in_brackets.strip() and '.' not in content_in_brackets.strip()
                
                if is_single_word_brackets:
                    # Это одно слово в скобках - вероятно подтитул, не серия
                    # Пропускаем это правило
                    pass  # ← Не извлекаем "Наследник", переходим к следующему правилу
                else:
                    # Hard check: if all words in brackets are SW or qualifiers → pure annotation,
                    # not a series name. E.g. "(весь цикл)", "(вся трилогия)", "(Дилогия)"
                    SW_QUALIFIERS = {'весь', 'вся', 'все', 'полный', 'полная', 'полное',
                                     'целый', 'целая', 'целое', 'complete', 'omnibus'}
                    bracket_words = content_in_brackets.lower().split()
                    is_pure_annotation = all(
                        w in self.service_words or w in SW_QUALIFIERS or w.isdigit()
                        for w in bracket_words
                    )
                    if is_pure_annotation:
                        pass  # "(весь цикл)", "(Трилогия)" — аннотация, не серия
                    else:
                        # Это многословная комбинация в скобках - может быть серия
                        potential_series = self._extract_series_from_brackets(content_in_brackets)
                        
                        # 🔑 ПРОВЕРКА: это не должна быть фамилия автора или список авторов!
                        looks_like_author = False
                        if ',' in potential_series:
                            # Содержит запятую - это список авторов, не серия
                            looks_like_author = True
                        elif '.' in potential_series:
                            # Содержит точку - для русских имён это часто инициал+фамилия
                            # "А.Михайловский" → это явно инициал в скобках
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
            if ' - ' in potential_series:
                pass  # Skip: config pattern was first priority, don't fall back to Rule 3
            else:
                _ps_words = potential_series.split()
                # Одно слово → вероятно фамилия автора
                # Заканчивается на одну заглавную букву → формат "Фамилия И." (инициал) = автор
                # Пример: "Кларк Ф" (Ф — инициал) или "Белоус" (одно слово)
                # Содержит аббревиатурный паттерн → формат инициалов "Сэнсом К.Дж" = автор
                _is_author_pattern = (
                    len(_ps_words) <= 1 or
                    (len(_ps_words[-1]) == 1 and _ps_words[-1][0].isupper()) or
                    bool(re.search(r'[А-ЯA-Z]\.[А-Яа-яA-Za-z]', potential_series))
                )
                if _is_author_pattern:
                    pass  # Likely author name format, not a series
                elif _has_numeric_suffix:
                    pass  # Пропускаем, Rule 3B обработает корректнее
                elif not validate or self._is_valid_series(potential_series):
                    return potential_series
        
        # Правило 3B: Author. Series N (без второго элемента после точки)
        # "Курилкин. Охотник 1" → "Охотник"
        # "Яманов. Бесноватый Цесаревич I" → "Бесноватый Цесаревич"
        # Структура: OneWord. MultipleWords NUM где NUM это арабские или римские цифры
        if '. ' in name_for_parsing:
            parts = name_for_parsing.split('. ', 1)
            if len(parts) == 2:
                first_part = parts[0].strip()
                second_part = parts[1].strip()
                
                # Проверяем что первая часть это вероятный автор
                # Убираем скобочные части (псевдоним/реальное имя) перед проверкой цифр:
                # "Leach23 (Михалек Дмитрий)" → "Leach23" → содержит цифры → всё равно автор
                # Нам важно чтобы СУТЬ части была авторской, а не чтобы не было цифр вообще.
                # Критерий: длина < 60 и НЕ начинается с цифры (т.е. не год/том).
                first_part_no_parens = re.sub(r'\s*\([^)]*\)', '', first_part).strip()
                looks_like_author = (
                    len(first_part) < 60 and
                    not first_part_no_parens[:1].isdigit()  # Не начинается с цифры
                )
                
                if looks_like_author:
                    # Проверяем диапазоны: "Совок 1-5", "Попаданец в Дракона 1-8" → True
                    series_match = re.match(r'^(.+?)\s+\d+[-–—]\d+\s*$', second_part)
                    # Проверяем арабские цифры: "Охотник 1" → True
                    if not series_match:
                        series_match = re.match(r'^(.+?)\s+\d+\s*$', second_part)
                    # Если нет арабских, проверяем римские цифры: "Бесноватый Цесаревич I" → True
                    if not series_match:
                        series_match = re.match(r'^(.+?)\s+[IVX]+\s*$', second_part)
                    
                    if series_match:
                        potential_series = series_match.group(1).strip()
                        if not validate or self._is_valid_series(potential_series):
                            return potential_series
        
        # Правило 4: Author - Series N или Author - Series N-M (без точки после номера)
        # "Атаманов Михаил - Задача выжить 1" → "Задача выжить"
        # "Земляной Андрей - Один на миллион 1-3" → "Один на миллион"
        if ' - ' in name_for_parsing:
            match = re.match(r'^(.+?)\s*-\s*(.+?)\s+(?:\d+[-–—]\d+|\d{1,2})\s*$', name_for_parsing)
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
                # Это Title (потенциальная Series) если он:
                # 1. Имеет несколько слов ИЛИ 
                # 2. Это нечто более подходящее серии чем фамилия  
                if len(title_before_dot.split()) > 1 or (title_before_dot and len(title_before_dot) > 3):
                    if not validate or self._is_valid_series(title_before_dot):
                        return title_before_dot
        
        if "охотник" in name_without_ext.lower() or "Наследник" in name_without_ext:
            pass

        # Если паттерн БЕЗ Series, но числовой суффикс обнаружен и Rules 3B/4
        # ничего не вернули, возвращаем metadata или пусто
        if pattern_found_without_series:
            if metadata_series:
                return metadata_series if validate else ""
            return ""

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
        
        # Если контент уже содержит '\' (результат BlockLevelPatternMatcher с SubSeries),
        # разбиваем по '\', а каждый компонент дополнительно чистим от номеров через '. '.
        # Иначе разбиваем по '. ' как обычно.
        if '\\' in content:
            raw_parts = []
            for chunk in content.split('\\'):
                # Внутри компонента может быть ". " — берём только первую часть (до точки)
                sub = chunk.split('. ')[0].strip()
                if sub:
                    raw_parts.append(sub)
            parts = raw_parts
        else:
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
            
            # Дополнительно удаляем "№ N" или одиночный "№" в конце
            series_name = re.sub(r'\s*№\s*\d*\s*$', '', series_name).strip()
            
            # Однобуквенные компоненты — это части аббревиатуры (напр. «О. Р. З.»), а не уровни серии.
            # Сбрасываем всю иерархию, чтобы не собирать мусор вида «Р\или Сказ...»
            if len(series_name) <= 1:
                return ""  # Аббревиатура обнаружена, серия не выделена

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
    
    def _remove_blacklist_words(self, text: str) -> str:
        """
        Удалить только слова из blacklist из текста, оставить остальное.
        
        Логика:
        - "Господин следователь (СИ)" → "(СИ)" в blacklist → "Господин следователь"
        - "Последний солдат СССР" → "СССР" в конце + есть слова перед ним → оставить как есть
        - Но если ТОЛЬКО blacklist-word → вернуть пусто
        
        Args:
            text: Исходный текст
            
        Returns:
            Текст с удаленными blacklist-словами, или пусто если ничего не осталось
        """
        if not text or not self.filename_blacklist:
            return text

        text_lower = text.lower()

        # Если текст начинается с collection_keyword (например "Сборник авторов"),
        # весь блок — маркер коллекции, не название серии — отвергаем целиком.
        for kw in (self.collection_keywords or []):
            if text_lower.startswith(kw.lower()):
                return ""

        original_text = text

        # Проходим по каждому слову в blacklist
        for bl_word in self.filename_blacklist:
            bl_word_lower = bl_word.lower().strip()
            if not bl_word_lower:
                continue
            
            # Ищем это слово как целое слово (не substring)
            # Паттерн: слово с границами (пробелы, скобки, пунктуация)
            import re
            pattern = r'(?:^|\s|\(|-)' + re.escape(bl_word_lower) + r'(?:\s|\)|$|[,.\-\!?])'

            # Перед удалением: если blacklist-слово стоит перед именами собственными
            # (все слова после него с заглавной буквы), это профессиональный префикс —
            # не удаляем. Пример: «Детектив Джейкоб Лев» — не трогаем.
            _m = re.search(pattern, original_text, flags=re.IGNORECASE)
            if _m:
                _after = original_text[_m.end():].strip()
                _alpha_after = [w for w in _after.split() if w and w[0].isalpha()]
                if _alpha_after and all(w[0].isupper() for w in _alpha_after):
                    continue  # Не удаляем: профессиональный префикс перед именами

            # Заменяем найденные вхождения на пробел (или пусто)
            original_text = re.sub(
                pattern,
                ' ',
                original_text,
                flags=re.IGNORECASE
            )
        
        # Очищаем множественные пробелы и пустые скобки
        cleaned = re.sub(r'\s+', ' ', original_text).strip()
        cleaned = re.sub(r'\(\s*\)', '', cleaned).strip()
        # Убираем висячие (несбалансированные) скобки в конце строки.
        # Пример: "Серия (СИ" → "Серия" (открытая скобка без закрытой)
        # НЕ трогаем: "Серия (Крылов)" — скобки сбалансированы
        if cleaned.count('(') != cleaned.count(')'):
            cleaned = re.sub(r'\s*[\(\)]\s*$', '', cleaned).strip()
        
        return cleaned if cleaned else ""

    def _contains_blacklist_word(self, text: str) -> bool:
        """
        Проверить, содержит ли text слово(а) из blacklist.
        
        Args:
            text: Проверяемый текст (например, название папки для series)
            
        Returns:
            True если найдено хотя бы одно blacklist слово, False иначе
        """
        if not text or not self.filename_blacklist:
            return False
        
        text_lower = text.lower()
        
        # Проходим по каждому слову в blacklist
        for bl_word in self.filename_blacklist:
            bl_word_lower = bl_word.lower().strip()
            if not bl_word_lower:
                continue
            
            # Проверяем наличие как целого слова (word boundary check)
            # Ищем в виде отдельного слова, не как substring
            # Например: "боевая фантастика" в "Боевая фантастика. Циклы" → FOUND
            #           но не "боевая" как часть слова
            
            # Используем word boundaries: \b работает для ASCII, но для кириллицы нужен свой paттерн
            import re
            pattern = r'(?:^|\W)' + re.escape(bl_word_lower) + r'(?:\W|$)'
            if re.search(pattern, text_lower):
                return True
        
        return False
    
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
        
        # ПРОВЕРКА -1: Исключить названия литературных премий
        # Признаки: содержит слово "премия"/"award"/"prize" ИЛИ заканчивается на "– YYYY" / "- YYYY"
        # Пример: "Литературная премия «Электронная буква – 2019»"
        _award_keywords = ('премия', 'award', 'prize', 'лауреат', 'номинант')
        if any(kw in text_lower for kw in _award_keywords):
            return False
        # Год со знаком тире в конце (после снятия кавычек) — тоже признак номинации/премии
        # ИСКЛЮЧЕНИЕ: дефис БЕЗ пробела как часть составного слова (СССР-2023 — не премия).
        # Отвергаем только: пробел перед любым тире, или длинное тире (– —) без пробела.
        if re.search(r'\s[–—\-]\s*\d{4}\s*[»"\']*\s*$', text) or \
           re.search(r'[–—]\s*\d{4}\s*[»"\']*\s*$', text):
            return False

        # ПРОВЕРКА -0.5: Исключить иерархические серии где любой сегмент — одна буква.
        # Пример: "Р\или Сказ о том..." — это аббревиатура О. Р. З., а не иерархия серий.
        if '\\' in text:
            _segments = [s.strip() for s in text.split('\\')]
            if any(len(s) <= 1 for s in _segments):
                return False

        # ПРОВЕРКА 0: Исключить технические фрагменты (калибры, характеристики)
        # Примеры: ".45", ".357", ",45caliber", "9mm" - это не названия серий
        # Паттерн: начинается с точки/запятой И это только цифры + буквы для единиц
        # Или: это только цифры + буквы без полноценного названия (< 3 букв)
        
        # Случай 1: ".NN" или ",NN" (калибр оружия)
        if re.match(r'^[.,]\d+$', text_lower):
            return False
        
        # Случай 2: чистые цифры с единицами вроде "9mm", "45acp"
        # (более 2 букв после цифр - это "real words", менее 2 букв это техника)
        if re.match(r'^\d+[a-z]{1,2}$', text_lower):
            return False
        
        # Случай 3: только цифры и 1-3 символа (вроде ".45" → "45", ".357" → "357")
        # Это вероятный калибр оружия, а не серия
        # Но берем осторожно - "99" может быть реальная серия
        # Поэтому отвергаем ТОЛЬКО если это 1-2 символа (как "45", "9", "357" = 3 цифры-это OK на грани)
        if re.match(r'^\d{1,2}$', text_lower):
            return False
        
        # ПРОВЕРКА 1: filename_blacklist - запрещенные слова
        # ВАЖНО: проверяем целые слова, не substring!
        # "СИ" в blacklist относится к метатегам "(СИ)" в конце, а не к "Сид"
        # ЭКСПЦИЯ: если blacklist-word это последнее слово И перед ним есть другие слова,
        # это вероятно часть series name, а не сама папка. Пример: "Последний солдат СССР"
        # где "СССР" в blacklist, но это реальная series потому что есть реальные слова перед ней

        # ПЕРЕПРОВЕРКА ПЕРЕД ЦИКЛОМ: перечень жанров через запятую
        # Пример: "Путешествия, приключения, фантастика" — каждая часть одно слово,
        # хотя бы одна часть в blacklist → это издательская рубрика, не серия.
        if ',' in text_lower:
            _comma_parts = [p.strip() for p in text_lower.split(',')]
            # Применяем только когда каждая часть — ≤2 слова (перечень, не «X, или Y»)
            if _comma_parts and all(len(p.split()) <= 2 for p in _comma_parts if p):
                _bl_lower_set = {bl.lower() for bl in self.filename_blacklist}
                if any(p in _bl_lower_set for p in _comma_parts if p):
                    return False

        for bl_word in self.filename_blacklist:
            bl_word_lower = bl_word.lower()
            # Match bl_word as a whole word or at word boundary
            pattern = r'(?:^|\s|\(|-)' + re.escape(bl_word_lower) + r'(?:\s|\)|$)'
            if re.search(pattern, text_lower):
                # Если это ТОЛЬКО blacklist word (например "СССР" или "СССР по категориям"),
                # отвергаем. Но если есть реальные слова ПЕРЕД ним, это series.
                # Пример: "Последний солдат СССР" ← реальная series даже если СССР в blacklist
                words = text_lower.split()
                bl_word_index = None
                
                # Найдем позицию blacklist-word в списке слов
                for i, word in enumerate(words):
                    if word.lower() == bl_word_lower or bl_word_lower in word:
                        bl_word_index = i
                        break
                
                # Если blacklist-word в КОНЦЕ и есть ≥2 слова перед ним
                # (≥2, а не просто >0, чтобы исключить формат «Категория. Жанр»,
                # например «Современность. Фантастика» — только 1 слово перед blacklist-словом)
                if bl_word_index is not None and bl_word_index >= 2 and bl_word_index == len(words) - 1:
                    # Это вероятно series (реальные слова + blacklist-word в конце)
                    # Пример: "Последний солдат" + "СССР" = "Последний солдат СССР"
                    continue  # Не отвергаем
                elif bl_word_index == 0 and len(words) == 1:
                    # Это вероятно папка (ТОЛЬКО blacklist-word)
                    # Пример: "СССР"
                    return False
                elif bl_word_index == 0 and len(words) >= 3:
                    # Blacklist-слово в начале многословной фразы (≥3 слов) →
                    # жанр-префикс в названии серии, допускаем.
                    # Пример: "Попаданец в Дракона", "Детектив из прошлого"
                    continue
                else:
                    # В других случаях (blacklist-word в середине или начале):
                    # Проверяем паттерн «Профессия/Звание + Имя собственное».
                    # Если после blacklist-слова идут слова с заглавной буквы (имена),
                    # это название серии с профессией персонажа, а не жанровый тег.
                    # Пример: «Детектив Джейкоб Лев» → «Джейкоб», «Лев» — заглавные → допускаем.
                    # Пример: «детективный роман» → следующее слово строчное → отвергаем.
                    _bl_idx = bl_word_index if bl_word_index is not None else 0
                    _orig_words = text.split()
                    _words_after = [w for w in _orig_words[_bl_idx + 1:] if w and w[0].isalpha()]
                    if _words_after and all(w[0].isupper() for w in _words_after):
                        continue  # «Профессия + Имя» — допускаем как название серии
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
        
        # Правило -2: Удалить обрамляющие кавычки-ёлочки «» — они обозначают серию в имени файла,
        # но не должны быть частью итогового названия: «СССР-2023» → СССР-2023
        text = re.sub(r'^«\s*', '', text).strip()
        text = re.sub(r'\s*»$', '', text).strip()
        if not text:
            return original
        
        # Правило -1: Удалить ведущий дефис/тире (артефакт разбиения по ". " в паттернах "Author - Series")
        # Пример: "- Сказания Тремейна" → "Сказания Тремейна"
        text = re.sub(r'^[-–—]\s*', '', text).strip()
        if not text:
            return ""
        
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
            
            # Правило 2B: Удалить "№ N" или просто "№" в конце
            # "Смертельный аромат № 5" → "Смертельный аромат"
            # "Смертельный аромат №5" → "Смертельный аромат"
            # "Смертельный аромат №" → "Смертельный аромат"
            text = re.sub(r'\s*№\s*\d*\s*$', '', text).strip()
            
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
        
        # Правило 6: Повторно удалить обрамляющие кавычки-ёлочки после всех остальных правил
        # Случай: «СССР-2023» 2 → strip « → СССР-2023» 2 → strip number → СССР-2023» → strip »
        text = re.sub(r'^«\s*', '', text).strip()
        text = re.sub(r'\s*»$', '', text).strip()

        # Правило 7: Удалить завершающую одиночную точку
        # "Араб." → "Араб"  (метатег в FB2 может содержать точку в конце)
        # НЕ удалять троеточие: "Муля, не нервируй..." → без изменений
        if text.endswith('.') and not text.endswith('..') and not text.endswith('\u2026'):
            text = text[:-1].strip()
        
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
        
        # Проверяем полное совпадение: серия == полное имя автора
        # Пример: "Александрова Наталья" == "Александрова Наталья" → True
        if series_lower.strip() == author.lower().strip():
            return True
        
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
    
    def _balance_quotes(self, text: str) -> str:
        """
        Восстановить парные кавычки в тексте.
        
        Если в тексте есть открывающиеся кавычки но не хватает закрывающихся,
        автоматически добавляет закрывающиеся сдачи.
        
        Обрабатывает три типа кавычек:
        - Русские guillemets: « и »
        - Двойные кавычки: " и "
        - Одиночные кавычки: ' и '
        
        Примеры:
            "Вариант «Бис" → "Вариант «Бис»"
            "Цикл «Война «Ночи" → "Цикл «Война «Ночи»»"
            "Название "серия" → "Название "серия""
            "Текст 'цикл" → "Текст 'цикл'"
        
        Args:
            text: Исходный текст
        
        Returns:
            Текст с уравновешенными кавычками
        """
        if not text:
            return text
        
        # Определить типы кавычек и их пары
        quote_pairs = [
            ('«', '»'),  # Russian guillemets
            ('"', '"'),  # Double quotes
            ("'", "'"),  # Single quotes
        ]
        
        result = text
        
        for open_quote, close_quote in quote_pairs:
            open_count = result.count(open_quote)
            close_count = result.count(close_quote)
            
            # Если открывающихся больше, чем закрывающихся
            if open_count > close_count:
                missing = open_count - close_count
                # Добавляем недостающие закрывающиеся кавычки в конец
                result = result + close_quote * missing
        
        return result
    
    def _fix_russian_grammar(self, series: str) -> str:
        """
        Исправляет грамматические ошибки в названии серии по правилам русского языка.
        
        Правило: перед союзом 'что' в придаточном предложении нужна запятая.
        
        Примеры:
        - "Сделай что сможешь" → "Сделай, что сможешь"
        - "Расчеты что нужны" → "Расчеты, что нужны"
        - "что-то" → не изменяется (это не союз, а местоимение)
        
        Args:
            series: Название серии
            
        Returns:
            Исправленное название серии
        """
        if not series:
            return series
        
        # Ищем слово "что" как отдельное слово (не часть другого слова)
        # Используем word boundaries \b для точного совпадения
        # Проверяем что запятая еще не стоит перед "что"
        
        # Паттерн: что-то вроде "...слово что..." где перед "что" НЕТ запятой
        # Заменяем на "...слово, что..."
        pattern = r'(\S)\s+что\b'  # Пробел + "что" как отдельное слово, перед ним не запятая
        
        # Проверяем что "что" это отдельное слово (не часть "что-то" или "кто-то")
        def replacer(match):
            prefix = match.group(1)
            # Если перед словом уже есть запятая, не добавляем еще одну
            if prefix == ',':
                return match.group(0)
            # Если это дефис (как в "что-то"), не трогаем
            if prefix == '-':
                return match.group(0)
            # Иначе добавляем запятую
            return f"{prefix}, что"
        
        result = re.sub(pattern, replacer, series)
        return result

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
            # Проверяем что находится в скобках - берем ПЕРВУЮ пару скобок, не последнюю
            bracket_match = re.search(r'\(([^)]+)\)(?:\s*\(|\s*$)', filename)
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
