#!/usr/bin/env python3
"""
CSV Regeneration Service - 6-PASS Architecture 2.0 (Modular Edition)

PRECACHE + PASS 1-6 system with each PASS in separate module.

Reference: REGEN_CSV_ARCHITECTURE.md
"""

import csv
import sys
import time
from pathlib import Path

from settings_manager import SettingsManager
from logger import Logger
from fb2_author_extractor import FB2AuthorExtractor

from precache import Precache
from passes import (
    Pass1ReadFiles,
    Pass2Filename,
    Pass2Fallback,
    Pass3Normalize,
    Pass4Consensus,
    Pass5Conversions,
    Pass6Abbreviations,
)
from passes.pass2_series_filename import Pass2SeriesFilename
from passes.pass3_series_normalize import Pass3SeriesNormalize
from passes.folder_series_parser import parse_series_from_folder_name
from extraction_constants import FILE_EXTENSION_FOLDER_NAMES, is_no_series_folder
from pattern_converter import compile_patterns
from folder_classifier import FolderClassifier, FolderType
import re


class RegenCSVService:
    """Service for CSV regeneration using 6-PASS architecture."""
    
    def __init__(self, config_path: str = 'config.json'):
        """Initialize the service.
        
        Args:
            config_path: Path to config.json
        """
        self.config_path = Path(config_path)
        self.settings = SettingsManager(config_path)
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor(config_path)
        
        # Load configuration lists
        self.collection_keywords = self.settings.get_list('collection_keywords')
        self.service_words = self.settings.get_list('service_words')
        
        # Load folder patterns for series extraction
        folder_patterns_raw = self.settings.get_author_series_patterns_in_folders()
        self.folder_patterns = compile_patterns(folder_patterns_raw) if folder_patterns_raw else []

        # Folder type classifier — uses config BL lists + name dictionaries
        self.folder_classifier = FolderClassifier(self.settings)
        
        # Working directory (where FB2 files are scanned from)
        self.work_dir = Path(self.settings.get_last_scan_path())
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
        
        # Records list
        self.records = []

        # Compiled blacklist patterns — populated once per regenerate() run,
        # capturing any settings changes made before the run.
        self._compiled_blacklist: list = []

        # Author folder cache from PRECACHE
        self.author_folder_cache = {}
        
        # CSV output path - ALWAYS in project directory
        self.project_dir = Path(__file__).parent
        self.output_csv = self.project_dir / "regen.csv"

        # По умолчанию CSV сохраняется; generate_csv(output_csv_path=None) отключает запись
        self._do_save_csv = True
    
    def generate_csv(self, folder_path: str, output_csv_path=None, progress_callback=None):
        """
        Generate CSV from FB2 files in folder.
        Wrapper for regenerate() that returns records for GUI compatibility.
        
        Args:
            folder_path: Path to folder with FB2 files
            output_csv_path: Optional path to save CSV file
            progress_callback: Optional callback for progress updates (current, total, status)
            
        Returns:
            List of BookRecord objects
        """
        # Override work directory with the provided folder path
        self.work_dir = Path(folder_path)

        # Override output CSV path if provided
        if output_csv_path:
            self.output_csv = Path(output_csv_path)
            self._do_save_csv = True
        else:
            self._do_save_csv = False

        try:
            # Run regeneration with progress callback
            success = self.regenerate(progress_callback=progress_callback)
            
            if success:
                return self.records
            else:
                return []
        except Exception as e:
            self.logger.log(f"[ERROR] generate_csv failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _normalize_name_for_comparison(self, name: str) -> str:
        """Нормализировать имя для сравнения (lowercase, убрать лишние пробелы и пунктуацию).
        
        Заменяет запятые, точки, скобки на пробелы и нормализует пробелы.
        Это позволяет сравнивать "Иван, Петр" с "Иван; Петр" как одинаковые.
        
        Args:
            name: Имя для нормализации
            
        Returns:
            Нормализованное имя
        """
        if not name:
            return ""
        # Заменяем пунктуацию на пробелы
        normalized = re.sub(r'[;,()[\].]', ' ', name)
        # Удаляем лишние пробелы
        normalized = re.sub(r'\s+', ' ', normalized.strip().lower())
        return normalized
    
    def _is_author_folder(self, folder_name: str, proposed_author: str) -> bool:
        """Проверить, является ли папка папкой автора.
        
        Сравнивает нормализованные имена.
        
        Args:
            folder_name: Имя папки
            proposed_author: Предложенное имя автора
            
        Returns:
            True если папка = папка автора
        """
        if not proposed_author or not folder_name:
            return False
        
        folder_normalized = self._normalize_name_for_comparison(folder_name)
        author_normalized = self._normalize_name_for_comparison(proposed_author)
        
        return folder_normalized == author_normalized

    def _surnames_match_folder(self, proposed_author: str, folder_name: str) -> bool:
        """Проверить, является ли папка папкой автора с учётом склонения и формы.

        Обрабатывает:
        - Точное совпадение после нормализации (быстрый путь)
        - Форму множественного числа: "Живовы" совпадает с фамилией "Живов"
          (folder word startswith surname)
        - Несколько авторов: "Живов Геннадий, Живов Георгий" ↔ "Живовы Георгий и Геннадий"
          (все уникальные фамилии должны присутствовать в папке)
        """
        if not proposed_author or not folder_name:
            return False

        # Быстрый путь: точное совпадение после нормализации
        if self._normalize_name_for_comparison(folder_name) == \
                self._normalize_name_for_comparison(proposed_author):
            return True

        # Извлечь уникальные фамилии из proposed_author
        # Формат: "Фамилия Имя" или "Фамилия Имя, Фамилия Имя"
        surnames = []
        for author in re.split(r'[,;]', proposed_author):
            words = author.strip().replace('ё', 'е').split()
            if words:
                surnames.append(words[0].lower())
        unique_surnames = list(dict.fromkeys(surnames))  # дедупликация с сохранением порядка
        if not unique_surnames:
            return False

        folder_words = [w for w in re.split(r'[\s,;\-]+', folder_name.lower().replace('ё', 'е')) if w]

        # Каждая уникальная фамилия должна совпадать хотя бы с одним словом папки.
        # startswith учитывает форму множественного числа (Живов → Живовы)
        for surname in unique_surnames:
            if not any(fw == surname or fw.startswith(surname) for fw in folder_words):
                return False

        return True
    
    def _extract_series_from_folder_name(self, folder_name: str) -> str:
        """
        Извлечь название серии из имени папки, применяя паттерны.
        
        1. Убирает ведущие номера ("1. ", "2) " и т.д.)
        2. Затем применяет паттерны для извлечения серии из авторов в скобках
        3. Fallback: берёт всё перед скобками
        
        Args:
            folder_name: Имя папки ("1941 (Иван Байбаков)" или "1. Путь в Царьград")
        
        Returns:
            Название серии или исходное имя папки
        """
        # ШАГ 0: СНАЧАЛА убрать ведущие номера ("1. ", "2) " и т.д.)
        # "1. Путь в Царьград" → "Путь в Царьград"
        # "2) Варяг" → "Варяг"
        # НО: "1941 (Иван Байбаков)" оставляем как есть (1941 это часть имени)
        cleaned = re.sub(r'^\d+[\.\)\-]\s+', '', folder_name).strip()
        if cleaned and cleaned != folder_name:
            # Если что-то удалили, используем очищенную версию
            folder_name = cleaned
        
        # ШАГ 1: Попробуем применить паттерны и найти группу "series"
        for pattern_str, pattern_regex, group_names in self.folder_patterns:
            match = pattern_regex.search(folder_name)
            if match:
                # Ищем группу "series" (нормализовано в нижнем регистре)
                if 'series' in group_names:
                    series = match.group('series').strip()
                    if series:
                        return series
        
        # ШАГ 2: Fallback - простое правило: всё перед скобками это серия
        # "1941 (Иван Байбаков)" → "1941"
        match = re.match(r'^(.+?)\s*\([^)]+\)\s*$', folder_name)
        if match:
            return match.group(1).strip()
        
        # ШАГ 3: Если ничего не помогло, берём всё имя
        return folder_name.strip()
    
    def _compile_blacklist_for_run(self) -> list:
        """Скомпилировать blacklist regex-паттерны один раз на прогон.

        Вызывается в начале regenerate() — захватывает актуальные настройки
        на момент запуска, включая все изменения, сделанные пользователем.
        """
        blacklist = self.settings.get_list('filename_blacklist')
        if not blacklist:
            return []
        compiled = []
        for bl_word in blacklist:
            bl_word_lower = bl_word.lower().strip()
            if bl_word_lower:
                pattern = r'(?:^|\W)' + re.escape(bl_word_lower) + r'(?:\W|$)'
                compiled.append(re.compile(pattern))
        return compiled

    def _contains_blacklist_word_regen(self, text: str) -> bool:
        """
        Проверить, содержит ли text слово(а) из blacklist (заимствовано от Pass2).

        Использует pre-compiled паттерны из self._compiled_blacklist.
        Паттерны компилируются один раз в начале regenerate(), а не на каждый вызов.

        Args:
            text: Проверяемый текст (название папки)

        Returns:
            True если найдено хотя бы одно blacklist слово, False иначе
        """
        if not text:
            return False
        text_lower = text.lower()
        for pattern in self._compiled_blacklist:
            if pattern.search(text_lower):
                return True
        return False
    
    def regenerate(self, progress_callback=None) -> bool:
        """Execute full CSV regeneration pipeline.
        
        Args:
            progress_callback: Optional callback function(current, total, status) for progress updates
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Пункт 3: compile blacklist once per run with current settings
            self._compiled_blacklist = self._compile_blacklist_for_run()
            # Загрузить пользовательский список «без серии» один раз на прогон
            self._no_series_names = self.settings.get_no_series_folder_names()

            print("\n" + "="*80)
            print("  CSV REGENERATION - 6-PASS SYSTEM (Modular)")
            print(f"  Work folder: {self.work_dir}\n")
            print("="*80 + "\n")

            self.logger.log("=== Starting CSV regeneration ===")
            if progress_callback:
                progress_callback(0, 100, "Инициализация")
            
            # ===== PRECACHE =====
            if progress_callback:
                progress_callback(5, 100, "Кеширование папок авторов")
            _t = time.perf_counter()
            precache = Precache(self.work_dir, self.settings, self.logger,
                               self.folder_parse_limit)
            self.author_folder_cache = precache.execute()
            print(f"[PRECACHE] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] Author folder hierarchy cached")

            # ===== PASS 1 =====
            if progress_callback:
                progress_callback(10, 100, "Pass 1: Чтение FB2 файлов")
            _t = time.perf_counter()
            pass1 = Pass1ReadFiles(self.work_dir, self.author_folder_cache,
                                  self.extractor, self.logger,
                                  self.folder_parse_limit)
            self.records = pass1.execute()
            print(f"[PASS 1] → {time.perf_counter()-_t:.2f}s")
            
            if not self.records:
                raise FileNotFoundError(
                    f"Файлы FB2 не найдены в папке:\n{self.work_dir}\n\n"
                    "Убедитесь, что папка содержит FB2-файлы."
                )
            
            self.logger.log(f"[OK] PASS 1: Read {len(self.records)} files")

            # ===== PASS 1.5: Propagate folder_dataset author within each folder =====
            # If at least one file in a folder got author_source="folder_dataset",
            # all other files in the same folder inherit that author.
            from collections import defaultdict
            _folder_groups = defaultdict(list)
            for rec in self.records:
                parent = str(Path(rec.file_path).parent)
                _folder_groups[parent].append(rec)

            propagated = 0
            for parent, group in _folder_groups.items():
                # Find the best folder_dataset author in this group
                dataset_rec = next(
                    (r for r in group if r.author_source == 'folder_dataset' and r.proposed_author),
                    None
                )
                if dataset_rec:
                    for rec in group:
                        if rec is not dataset_rec and rec.proposed_author != dataset_rec.proposed_author:
                            rec.proposed_author = dataset_rec.proposed_author
                            rec.author_source = 'folder_dataset'
                            rec.needs_filename_fallback = False
                            propagated += 1

            if propagated:
                self.logger.log(f"[OK] PASS 1.5: Propagated folder_dataset author to {propagated} files")

            if progress_callback:
                progress_callback(20, 100, "Pass 2: Извлечение авторов")
            _t = time.perf_counter()
            pass2 = Pass2Filename(self.settings, self.logger, self.work_dir,
                                male_names=precache.male_names,
                                female_names=precache.female_names)
            pass2.prebuild_author_cache(self.records)
            pass2.execute(self.records)
            print(f"[PASS 2] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 2: Authors extracted from filenames")

            # ===== PASS 2 Fallback =====
            if progress_callback:
                progress_callback(25, 100, "Pass 2 Fallback: Применение метаданных")
            _t = time.perf_counter()
            pass2_fallback = Pass2Fallback(self.logger, settings=self.settings)
            pass2_fallback.execute(self.records)
            print(f"[PASS 2 Fallback] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 2 Fallback: Metadata applied")

            # ===== PASS 2.5: Expand abbreviated/plural author from consistent metadata =====
            _t25 = time.perf_counter()
            # Случай: папка "Войлошниковы", proposed_author="Войлошниковы" (filename),
            # но metadata_authors стабильно содержит полные имена авторов. Расширяем.
            import re as _re25

            # Перестраиваем группы по папкам после Pass 2
            _folder_groups2: dict = {}
            for rec in self.records:
                parent = str(Path(rec.file_path).parent)
                _folder_groups2.setdefault(parent, []).append(rec)

            def _stem25(s: str) -> str:
                # Two passes to handle compound endings like 'овы' = 'ов'+'ы'
                # "Войлошниковы" → "Войлошников" → "Войлошник"
                s = s.lower().replace('ё', 'е')
                for _ in range(2):
                    s2 = _re25.sub(r'(?:ова|ева|ов|ев|ин|ина|ий|ая|ый|ых|ы|а|я)$', '', s)
                    if s2 == s:
                        break
                    s = s2
                return s

            def _normalize_meta_author25(name: str) -> str:
                parts = name.strip().split()
                if len(parts) == 2:
                    return f"{parts[-1]} {parts[0]}"
                return name.strip()

            expanded25 = 0
            for parent, group in _folder_groups2.items():
                filename_recs = [
                    r for r in group
                    if r.author_source == 'filename' and r.proposed_author
                    and r.metadata_authors and r.metadata_authors != '[unknown]'
                ]
                if not filename_recs:
                    continue

                # Проверяем стабильность metadata_authors (≥ 60% файлов согласны)
                # Нормализуем: разбиваем на авторов и сортируем, чтобы порядок не важен
                import re as _re25b
                def _meta_key(m):
                    authors = frozenset(a.strip().lower() for a in _re25b.split(r'[;,]+', m) if a.strip())
                    return authors

                meta_counts: dict = {}
                for r in filename_recs:
                    key = _meta_key(r.metadata_authors.strip())
                    meta_counts[key] = meta_counts.get(key, 0) + 1
                dominant_key, dominant_count = max(meta_counts.items(), key=lambda x: x[1])
                if dominant_count / len(filename_recs) < 0.6:
                    continue
                # Берём первый файл с этим ключом как источник canonical metadata
                dominant_meta = next(
                    r.metadata_authors for r in filename_recs
                    if _meta_key(r.metadata_authors.strip()) == dominant_key
                )

                # proposed_author должен быть усечённой формой одного из авторов в meta.
                # ВАЖНО: Pass 2.5 предназначен только для ОДНОСЛОВНЫХ усечённых форм
                # (e.g. "Войлошниковы" → "Войлошников Тим"). Если proposed_author уже
                # содержит 2+ слов — это полное имя, расширение не нужно.
                proposed = filename_recs[0].proposed_author
                if len(proposed.split()) >= 2:
                    continue  # Уже полное имя — пропускаем
                proposed_stem = _stem25(proposed)
                if len(proposed_stem) < 4:
                    continue

                meta_authors_list = [a.strip() for a in _re25.split(r'[;,]+', dominant_meta) if a.strip()]
                matched = any(
                    # bidirectional: either stem contains the other
                    (proposed_stem in _stem25(part) or _stem25(part) in proposed_stem)
                    for a in meta_authors_list
                    for part in a.split()
                    if len(_stem25(part)) >= 4
                )
                if not matched:
                    continue

                normalized_authors = ', '.join(_normalize_meta_author25(a) for a in meta_authors_list)

                for rec in group:
                    if rec.proposed_author == proposed and rec.author_source in ('filename', ''):
                        rec.proposed_author = normalized_authors
                        rec.author_source = 'metadata'
                        rec.needs_filename_fallback = False
                        expanded25 += 1

            print(f"[PASS 2.5] → {time.perf_counter()-_t25:.2f}s")
            if expanded25:
                self.logger.log(f"[OK] PASS 2.5: Expanded abbreviated authors in {expanded25} files")

            # ===== SERIES EXTRACTION: From Folders (VARIANT B) =====
            if progress_callback:
                progress_callback(30, 100, "Извлечение серий")
            _t = time.perf_counter()
            print("\n[SERIES] Extracting series from folder structure...")

            # Кэш нормализации имён для _surnames_match_folder
            _norm_cache: dict = {}

            def _norm(name: str) -> str:
                if name not in _norm_cache:
                    _norm_cache[name] = self._normalize_name_for_comparison(name)
                return _norm_cache[name]

            # Вспомогательная функция: вычислить (proposed_series, series_source)
            # по частям пути и автору. Результат кэшируется по ключу (author, parent_parts).
            _series_folder_cache: dict = {}  # (author, parent_parts) → (series, source)

            def _compute_folder_series(author: str, parent_parts: tuple) -> tuple:
                """Вернуть (proposed_series, series_source) из структуры папок.

                Логика зависит от типа корневой папки (FolderType):

                AUTHOR:
                    Ищем папку автора в пути → всё что глубже = серия/подсерия.
                    Это основной случай: Волков Тим/Дуэлянт/1. Книга.fb2

                PUBLISHER / COLLECTION:
                    Корневая папка НЕ является серией (это издательский каталог).
                    Если файл лежит в подпапке — подпапка = серия, независимо от автора.
                    Если файл лежит прямо в корневой папке — серии из папки нет.
                    Пример: Серия - «Боевая фантастика»/ИмяСерии/1. Книга.fb2

                UNKNOWN:
                    Пробуем найти автора в пути (как AUTHOR).
                    Если автор не найден, но есть подпапки — берём подпапки как серию.
                    Это покрывает случай, когда корневая папка сама является серией.

                VARIANT / NO_SERIES / SKIP:
                    Серию из папки не извлекаем.
                """
                key = (author, parent_parts)
                if key in _series_folder_cache:
                    return _series_folder_cache[key]

                result = ('', '')

                if not parent_parts:
                    _series_folder_cache[key] = result
                    return result

                root_type = self.folder_classifier.classify(parent_parts[0])

                if root_type in (FolderType.SKIP, FolderType.VARIANT, FolderType.NO_SERIES):
                    # Не используем папку как источник серии
                    pass

                elif root_type in (FolderType.PUBLISHER, FolderType.COLLECTION):
                    # Корневая папка = издательский каталог.
                    # Серия = подпапки начиная с уровня 2 (index 1+).
                    series_folders = parent_parts[1:]
                    if series_folders:
                        if any(is_no_series_folder(f, self._no_series_names) for f in series_folders):
                            result = ('', 'no_series_folder')
                        else:
                            series_names = [self._extract_series_from_folder_name(f) for f in series_folders]
                            series_combined = '\\'.join(s for s in series_names if s)
                            if series_combined:
                                result = (series_combined, 'folder_dataset')

                else:
                    # AUTHOR или UNKNOWN — ищем папку автора в пути
                    author_folder_index = -1
                    if author:
                        for idx, part in enumerate(parent_parts):
                            if self._surnames_match_folder(author, part):
                                author_folder_index = idx
                                break

                    if author_folder_index >= 0:
                        # Нашли папку автора → всё глубже = серия
                        series_folders = parent_parts[author_folder_index + 1:]
                        if series_folders:
                            if any(is_no_series_folder(f, self._no_series_names) for f in series_folders):
                                result = ('', 'no_series_folder')
                            else:
                                series_names = [self._extract_series_from_folder_name(f) for f in series_folders]
                                series_combined = '\\'.join(s for s in series_names if s)
                                if series_combined:
                                    result = (series_combined, 'folder_dataset')

                    elif root_type == FolderType.UNKNOWN and len(parent_parts) > 1:
                        # Автор не найден, но есть подпапки в UNKNOWN-папке.
                        # Берём все подпапки (начиная с index 1) как серию.
                        series_folders = parent_parts[1:]
                        if any(is_no_series_folder(f, self._no_series_names) for f in series_folders):
                            result = ('', 'no_series_folder')
                        else:
                            series_names = [self._extract_series_from_folder_name(f) for f in series_folders]
                            series_combined = '\\'.join(s for s in series_names if s)
                            if series_combined:
                                result = (series_combined, 'folder_dataset')

                _series_folder_cache[key] = result
                return result

            # Предвычисляем части пути один раз
            _parts_cache: dict = {}

            for record in self.records:
                if record.proposed_series:
                    continue  # Skip if series already set

                file_path_parts = _parts_cache.get(record.file_path)
                if file_path_parts is None:
                    raw_parts = Path(record.file_path).parts
                    file_path_parts = tuple(
                        p for i, p in enumerate(raw_parts)
                        if i == len(raw_parts) - 1 or p.lower() not in FILE_EXTENSION_FOLDER_NAMES
                    )
                    _parts_cache[record.file_path] = file_path_parts

                parent_parts = file_path_parts[:-1]  # без имени файла
                author = record.proposed_author or ''

                series, source = _compute_folder_series(author, parent_parts)
                if source and series != author:
                    record.proposed_series = series
                    record.series_source = source

                # Если author_folder_index < 0 (папка автора не найдена) —
                # серия из папок не извлекается; Pass 2 Series и metadata возьмут на себя.
            
            print(f"[SERIES folders] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] Series extracted from folder structure (Variant B)")

            # ===== SERIES PASS 2 =====
            if progress_callback:
                progress_callback(40, 100, "Извлечение серий из имен файлов")
            _t = time.perf_counter()
            print("[SERIES] Extracting series from filenames...")
            pass2_series = Pass2SeriesFilename(self.logger,
                                              male_names=precache.male_names,
                                              female_names=precache.female_names)
            pass2_series.execute(self.records)
            print(f"[SERIES PASS 2] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] Series PASS 2: Extracted from filenames")

            # ===== SERIES PASS 3 =====
            if progress_callback:
                progress_callback(45, 100, "Нормализация серий")
            _t = time.perf_counter()
            print("[SERIES] Normalizing series names...")
            pass3_series = Pass3SeriesNormalize(self.logger, settings=self.settings)
            pass3_series.execute(self.records)
            print(f"[SERIES PASS 3] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] Series PASS 3: Normalized series names")

            # ===== PASS 3 =====
            if progress_callback:
                progress_callback(55, 100, "Pass 3: Нормализация авторов")
            _t = time.perf_counter()
            pass3 = Pass3Normalize(self.logger, settings=self.settings)
            pass3.execute(self.records)
            print(f"[PASS 3] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 3: Authors normalized")

            # ===== PASS 4 =====
            if progress_callback:
                progress_callback(65, 100, "Pass 4: Консенсус")
            _t = time.perf_counter()
            pass4 = Pass4Consensus(self.logger, settings=self.settings)
            pass4.execute(self.records)
            print(f"[PASS 4] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 4: Consensus applied")

            # ===== PASS 5 =====
            if progress_callback:
                progress_callback(75, 100, "Pass 5: Преобразования")
            _t = time.perf_counter()
            pass5 = Pass5Conversions(self.logger, settings=self.settings)
            pass5.execute(self.records)
            print(f"[PASS 5] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 5: Conversions re-applied")

            # ===== PASS 6 =====
            if progress_callback:
                progress_callback(85, 100, "Pass 6: Раскрытие аббревиатур")
            _t = time.perf_counter()
            pass6 = Pass6Abbreviations(self.logger, settings=self.settings)
            pass6.execute(self.records)
            print(f"[PASS 6] → {time.perf_counter()-_t:.2f}s")
            self.logger.log("[OK] PASS 6: Abbreviations expanded")
            
            # ===== Post-check: series must never equal author =====
            # Normalize both sides for comparison: strip trailing periods, lowercase.
            def _norm_for_cmp(s: str) -> str:
                return s.rstrip('. ').strip().lower().replace('ё', 'е')

            _series_eq_author_cleared = 0
            for record in self.records:
                if not record.proposed_series or not record.proposed_author:
                    continue
                a_norm = _norm_for_cmp(record.proposed_author)
                s_norm = _norm_for_cmp(record.proposed_series)

                is_conflict = (
                    # Exact match: series == author (e.g. "Фонд А" == "Фонд А.")
                    s_norm == a_norm
                    # Series starts with full author + space: "Фонд А Конторщица"
                    or s_norm.startswith(a_norm + ' ')
                    # Series starts with full author + period: "Берг Ираклий. Крепостной Пушкина"
                    or s_norm.startswith(a_norm + '.')
                )

                # Тип А: folder_dataset series looks like a person name and shares
                # surname with the author — folder-author was not in name dicts so became series.
                # E.g. series="Буров Егор" (folder name), author="Буров Дмитрий" (from filename).
                if not is_conflict and record.series_source == 'folder_dataset':
                    a_parts = a_norm.split()
                    s_parts = s_norm.split()
                    if (len(s_parts) <= 3 and len(a_parts) >= 1
                            and len(a_parts[0]) > 3
                            and s_parts and s_parts[0] == a_parts[0]):
                        is_conflict = True

                # Тип Б: co-author folder — series words are a permutation of author words.
                # E.g. author="Винтеркей Серж, Шумилин Артем", series="Шумилин Артем, Винтеркей Серж".
                if not is_conflict and record.series_source == 'folder_dataset':
                    _strip_punct = re.compile(r'[.,;()]')
                    s_words = set(_strip_punct.sub('', s_norm).split())
                    a_words = set(_strip_punct.sub('', a_norm).split())
                    if s_words and len(s_words) >= 2 and s_words == a_words:
                        is_conflict = True

                # Тип В: publisher subfolder contains author name mixed with series label.
                # E.g. author="Аберкромби Джо", series="Фэнтези Джо Аберкромби" (folder_dataset).
                # Rule: if all meaningful author words (len>2) appear in series (prefix-match),
                # then:
                #   - if metadata is available and does NOT contain author words → use metadata
                #   - if metadata is empty → clear series entirely
                # Protection: if metadata ALSO contains author words → do not replace (e.g. "Лето Элин").
                if not is_conflict and record.series_source == 'folder_dataset':
                    _sp2 = re.compile(r'[.,;()\-]')
                    a_meaningful = [w for w in _sp2.sub('', a_norm).split() if len(w) > 2]
                    s_str = _sp2.sub('', s_norm)

                    def _word_in_str(word, text):
                        """Match word in text allowing 1-2 char Russian inflection suffix."""
                        prefix = word[:max(3, len(word) - 1)]
                        return re.search(r'\b' + re.escape(prefix), text) is not None

                    if (len(a_meaningful) >= 2
                            and all(_word_in_str(w, s_str) for w in a_meaningful)):
                        if record.metadata_series:
                            # Check that metadata does NOT also contain author words
                            meta_norm2 = _norm_for_cmp(record.metadata_series)
                            meta_str = _sp2.sub('', meta_norm2)
                            meta_has_author = all(_word_in_str(w, meta_str) for w in a_meaningful)
                            if not meta_has_author:
                                is_conflict = True
                        else:
                            # No metadata fallback — series is pure "label+author", clear it
                            is_conflict = True

                # Тип Г: series contains only the author's surname as a folder label.
                # E.g. author="Скальци Джон", series="Пространство Скальци" (publisher subfolder).
                # Also handles plural surname family folders: "Войлошниковы" for "Войлошников Владимир, Войлошникова Ольга".
                # Requires: metadata available and metadata does NOT contain the surname.
                if not is_conflict and record.series_source == 'folder_dataset' and record.metadata_series:
                    _sp2_g = re.compile(r'[.,;()\-]')
                    a_norm_g = _norm_for_cmp(record.proposed_author)
                    a_surname_g = _sp2_g.sub('', a_norm_g).split()[0] if a_norm_g.strip() else ''
                    if len(a_surname_g) > 3:
                        s_str_g = _sp2_g.sub('', s_norm)
                        # Use prefix match allowing 1-2 char Russian inflection
                        surname_prefix_g = a_surname_g[:max(4, len(a_surname_g) - 1)]
                        if re.search(r'\b' + re.escape(surname_prefix_g), s_str_g):
                            meta_norm_g = _norm_for_cmp(record.metadata_series)
                            meta_str_g = _sp2_g.sub('', meta_norm_g)
                            if not re.search(r'\b' + re.escape(surname_prefix_g), meta_str_g):
                                is_conflict = True

                # Тип Д: publisher attribution prefix ("от автора X", "от авторов X").
                # E.g. folder "Fanzon. От автора Киллербота" → series="От автора Киллербота",
                # but metadata has the real series name.
                if not is_conflict and record.series_source == 'folder_dataset' and record.metadata_series:
                    if s_norm.startswith('от автор'):
                        is_conflict = True

                if is_conflict:
                    record.proposed_series = record.metadata_series or ''
                    record.series_source = 'metadata' if record.metadata_series else ''
                    _series_eq_author_cleared += 1

            if _series_eq_author_cleared:
                print(f"[POST-CHECK] Cleared {_series_eq_author_cleared} records where series == author")
                self.logger.log(f"[OK] POST-CHECK: Cleared {_series_eq_author_cleared} series==author conflicts")

            # ===== Post-check: metadata rescue — restore metadata_series for records still without series =====
            # Handles cases where series was cleared (e.g. series==author post-check) but metadata has a real series.
            # E.g. proposed_series was folder name "А_З_К, Берг Александр" → cleared → metadata="Антиблицкриг" rescued.
            _meta_rescue_count = 0
            for record in self.records:
                if record.proposed_series or not record.metadata_series:
                    continue
                meta = record.metadata_series.strip()
                if not meta:
                    continue
                author_norm = _norm_for_cmp(record.proposed_author or '')
                meta_norm = _norm_for_cmp(meta)
                if author_norm and meta_norm == author_norm:
                    continue
                # Фильтруем издательские импринты через blacklist (тот же что в pass2)
                _meta_l = meta.lower()
                _bl_hit = False
                for _bl in self._compiled_blacklist:
                    if _bl.search(_meta_l):
                        _bl_hit = True
                        break
                if _bl_hit:
                    continue
                record.proposed_series = meta
                record.series_source = 'metadata'
                _meta_rescue_count += 1
            if _meta_rescue_count:
                print(f"[POST-CHECK] Rescued {_meta_rescue_count} series from metadata after series==author cleanup")
                self.logger.log(f"[OK] POST-CHECK: Rescued {_meta_rescue_count} series from metadata")

            # ===== Post-check: clear series_number if >= 100 (year, chapter range, title fragment) =====
            _large_num_count = 0
            for record in self.records:
                sn = (record.series_number or '').strip()
                if sn and re.match(r'^\d+$', sn) and int(sn) >= 100:
                    record.series_number = ''
                    _large_num_count += 1
            if _large_num_count:
                print(f"[POST-CHECK] Cleared {_large_num_count} oversized series numbers (>=100)")
                self.logger.log(f"[OK] POST-CHECK: Cleared {_large_num_count} oversized series numbers")

            # ===== Post-check: strip leading "N. " number prefix from series (filename artifact) =====
            # E.g. "3. Шмыг" → "Шмыг", "4. Городская Стража" → "Городская Стража"
            _digit_prefix_re = re.compile(r'^\d+\.\s+', re.UNICODE)
            _digit_prefix_count = 0
            for record in self.records:
                if not record.proposed_series:
                    continue
                cleaned = _digit_prefix_re.sub('', record.proposed_series)
                if cleaned != record.proposed_series:
                    # Prefer metadata if available and matches
                    record.proposed_series = record.metadata_series or cleaned
                    record.series_source = 'metadata' if record.metadata_series else record.series_source
                    _digit_prefix_count += 1
            if _digit_prefix_count:
                print(f"[POST-CHECK] Stripped digit prefix from {_digit_prefix_count} series values")
                self.logger.log(f"[OK] POST-CHECK: Stripped digit prefix from {_digit_prefix_count} series")

            # ===== Post-check: trim series to metadata prefix when filename added extra words =====
            # E.g. proposed="1917 год министр" (filename), meta="1917 год" → use meta.
            # Only when meta is a proper prefix (word boundary) and len(meta) >= 6.
            _meta_prefix_count = 0
            for record in self.records:
                if not record.proposed_series or not record.metadata_series:
                    continue
                if 'filename' not in record.series_source:
                    continue
                ps_l = record.proposed_series.lower().replace('ё', 'е')
                ms_l = record.metadata_series.lower().replace('ё', 'е').strip()
                rest_after_meta = record.proposed_series[len(ms_l):].strip()
                # Don't trim if extra part contains digits (year, version — meaningful, not noise)
                if (len(ms_l) >= 6
                        and ps_l.startswith(ms_l)
                        and len(record.proposed_series) > len(ms_l)
                        and not record.proposed_series[len(ms_l)].isalpha()
                        and not re.search(r'\d', rest_after_meta)):
                    record.proposed_series = record.metadata_series.strip()
                    record.series_source = 'metadata'
                    _meta_prefix_count += 1
            if _meta_prefix_count:
                print(f"[POST-CHECK] Trimmed filename series to metadata prefix in {_meta_prefix_count} records")
                self.logger.log(f"[OK] POST-CHECK: Trimmed series to metadata prefix in {_meta_prefix_count} records")

            # ===== Post-check: expand truncated filename series using metadata =====
            # If metadata_series STARTS WITH proposed_series (metadata is more complete),
            # and the extra part is NOT purely alphabetic noise (has digits or ends with letters
            # that are meaningful), expand proposed to metadata.
            # Example: proposed="Боевой", metadata="Боевой 1918 год" → expand.
            def _norm_dash(s: str) -> str:
                return s.replace('–', '-').replace('—', '-').replace('‒', '-')

            _meta_expand_count = 0
            for record in self.records:
                if not record.proposed_series or not record.metadata_series:
                    continue
                if 'filename' not in record.series_source:
                    continue
                ps_l = _norm_dash(record.proposed_series.lower().replace('ё', 'е').strip())
                ms_l = _norm_dash(record.metadata_series.lower().replace('ё', 'е').strip())
                if (len(ps_l) >= 3
                        and ms_l.startswith(ps_l)
                        and len(ms_l) > len(ps_l)):
                    extra = ms_l[len(ps_l):].strip()
                    # Only expand when extra is meaningful: starts with letter, digit, or dash
                    # (dash covers "Наш дом" → "Наш дом – СССР" where extra = "– СССР")
                    if extra and (extra[0].isalnum() or extra[0] in '-–—'):
                        # Normalize em/en-dash to hyphen to match filename convention
                        record.proposed_series = _norm_dash(record.metadata_series.strip())
                        record.series_source = record.series_source + '+meta_expanded'
                        _meta_expand_count += 1
            if _meta_expand_count:
                print(f"[POST-CHECK] Expanded truncated filename series via metadata in {_meta_expand_count} records")
                self.logger.log(f"[OK] POST-CHECK: Expanded series via metadata in {_meta_expand_count} records")

            # ===== Post-check: strip trailing service words (Книга, Том, Часть, Book) =====
            _service_tail_re = re.compile(
                r'\s+(?:книга|том|часть|book|vol|volume)\.?\s*$',
                re.IGNORECASE | re.UNICODE,
            )
            _service_count = 0
            for record in self.records:
                if not record.proposed_series:
                    continue
                cleaned = _service_tail_re.sub('', record.proposed_series).strip()
                if cleaned and cleaned != record.proposed_series:
                    record.proposed_series = cleaned
                    _service_count += 1
            if _service_count:
                print(f"[POST-CHECK] Stripped trailing service words from {_service_count} series values")
                self.logger.log(f"[OK] POST-CHECK: Stripped service words from {_service_count} series")

            # ===== Post-check: deduplicate backslash hierarchy where both parts are identical =====
            # E.g. "Боец\Боец" → "Боец"  (filename parsed "Боец 1. Боец." as two identical parts)
            _bs_dedup_count = 0
            for record in self.records:
                ps = record.proposed_series
                if ps and '\\' in ps:
                    parts = ps.split('\\')
                    # If first and last parts are the same (case+ё→е insensitive), keep only first
                    p0 = parts[0].strip().lower().replace('ё', 'е')
                    pl = parts[-1].strip().lower().replace('ё', 'е')
                    if p0 and p0 == pl:
                        record.proposed_series = parts[0].strip()
                        _bs_dedup_count += 1
            if _bs_dedup_count:
                print(f"[POST-CHECK] Deduplicated identical backslash series in {_bs_dedup_count} records")
                self.logger.log(f"[OK] POST-CHECK: Deduplicated backslash series in {_bs_dedup_count} records")

            # ===== Post-check: remove consecutive duplicate words in series =====
            _dedup_word_re = re.compile(
                r'\b(\w+)\b(\s+\1)+\b',
                re.IGNORECASE | re.UNICODE,
            )
            _dedup_count = 0
            for record in self.records:
                if not record.proposed_series:
                    continue
                cleaned = _dedup_word_re.sub(r'\1', record.proposed_series)
                if cleaned != record.proposed_series:
                    record.proposed_series = cleaned.strip()
                    _dedup_count += 1
            if _dedup_count:
                print(f"[POST-CHECK] Deduplicated words in {_dedup_count} series values")
                self.logger.log(f"[OK] POST-CHECK: Deduplicated words in {_dedup_count} series")

            # POST-CHECK Тип Е: folder_hierarchy series enrichment.
            # If a folder_hierarchy record's series "B" is the SUFFIX of a same-author
            # filename-based series "A. B" (≥2 records), enrich the folder record with "A. B".
            # Example: folder series "Шоу должно продолжаться!" + filename series
            # "90-е. Шоу должно продолжаться" → folder records get "90-е. Шоу должно продолжаться".
            def _norm_series_suffix(s: str) -> str:
                """Normalize for suffix matching: strip trailing punctuation & lowercase."""
                return re.sub(r'[!?.]+$', '', s).strip().lower().replace('ё', 'е')

            # Build: author → {norm_series_suffix: canonical_filename_series}
            _fn_series_by_author: dict = {}
            _fn_series_count: dict = {}
            for record in self.records:
                if not record.proposed_series or 'filename' not in record.series_source:
                    continue
                author = record.proposed_author or ''
                norm = _norm_series_suffix(record.proposed_series)
                _fn_series_count[(author, norm)] = _fn_series_count.get((author, norm), 0) + 1
                _fn_series_by_author.setdefault(author, {})[norm] = record.proposed_series

            _folder_enrich_count = 0
            for record in self.records:
                if not record.proposed_series:
                    continue
                if record.series_source not in ('folder_hierarchy', 'folder_meta_consensus'):
                    continue
                author = record.proposed_author or ''
                fn_map = _fn_series_by_author.get(author, {})
                if not fn_map:
                    continue
                folder_norm = _norm_series_suffix(record.proposed_series)
                # Find a filename-series whose suffix (after ". ") matches the folder series
                best = None
                for fn_norm, fn_canonical in fn_map.items():
                    # fn_norm must end with folder_norm
                    if fn_norm == folder_norm:
                        continue  # same name, no enrichment needed
                    if not fn_norm.endswith(folder_norm):
                        continue
                    # The prefix before ". " must exist and be non-empty
                    prefix_part = fn_norm[: len(fn_norm) - len(folder_norm)].rstrip('. ')
                    if not prefix_part:
                        continue
                    # Require ≥2 filename records for this series to avoid false positives
                    if _fn_series_count.get((author, fn_norm), 0) < 2:
                        continue
                    best = fn_canonical
                    break
                if best and best != record.proposed_series:
                    record.proposed_series = best
                    record.series_source = record.series_source + '+filename_enriched'
                    _folder_enrich_count += 1
            if _folder_enrich_count:
                print(f"[POST-CHECK] Enriched {_folder_enrich_count} folder_hierarchy series with filename prefix")
                self.logger.log(f"[OK] POST-CHECK: Enriched {_folder_enrich_count} folder_hierarchy series")

            # ===== Post-check: filename prefix pattern — cross-file series detection =====
            # Если Author. Title.fb2 И Author. Title. Subtitle.fb2 лежат в одной папке,
            # то Title — название серии для обоих файлов.
            # Признак: стем одного файла является префиксом стема другого (у того же автора).
            _prefix_series_count = 0
            _prefix_groups: dict = {}
            for record in self.records:
                folder = str(Path(record.file_path).parent)
                author = record.proposed_author or ''
                _prefix_groups.setdefault((folder, author), []).append(record)

            for (folder, author), grp in _prefix_groups.items():
                if len(grp) < 2:
                    continue
                # Извлечь часть имени файла после автора (Author. Title → Title)
                def _title_part(rec, _author=author):
                    stem = Path(rec.file_path).stem
                    _a_norm = _norm_for_cmp(_author)
                    for sep in ('. ', ' - '):
                        if sep in stem:
                            before, after = stem.split(sep, 1)
                            if _norm_for_cmp(before) == _a_norm or _norm_for_cmp(before) in _a_norm:
                                return after.strip()
                    return stem.strip()

                titled = [(r, _title_part(r)) for r in grp]

                from difflib import SequenceMatcher

                def _is_prefix_match(ta: str, tb: str) -> bool:
                    """True если ta является префиксом tb (точно или с небольшой опечаткой).
                    Стратегия: берём первые len(ta) символов tb и сравниваем через SequenceMatcher.
                    Порог схожести 0.85 — допускает 1-2 символа разницы в длинных словах.
                    """
                    if not ta or not tb:
                        return False
                    # Точный match
                    if tb.startswith(ta + '. ') or tb.startswith(ta + '.'):
                        return True
                    # Нечёткий: tb должен быть длиннее ta, сравниваем prefix
                    if len(tb) <= len(ta):
                        return False
                    # Убедиться что после предполагаемого префикса идёт '. ' или конец
                    cut = tb[:len(ta)]
                    rest = tb[len(ta):]
                    if not rest.startswith('. ') and not rest.startswith('.'):
                        return False
                    ratio = SequenceMatcher(None, ta, cut).ratio()
                    return ratio >= 0.85

                # Ищем пары A, B где title_A — префикс title_B (разделитель '. ')
                for rec_a, title_a in titled:
                    if not title_a:
                        continue
                    ta_norm = _norm_for_cmp(title_a)
                    for rec_b, title_b in titled:
                        if rec_b is rec_a or not title_b:
                            continue
                        tb_norm = _norm_for_cmp(title_b)
                        if _is_prefix_match(ta_norm, tb_norm):
                            # Canonical series name: prefer existing proposed_series (e.g. from "filename")
                            canonical = rec_a.proposed_series or rec_b.proposed_series or title_a
                            if not rec_a.proposed_series:
                                rec_a.proposed_series = canonical
                                rec_a.series_source = 'filename_prefix_pattern'
                                _prefix_series_count += 1
                            if not rec_b.proposed_series:
                                rec_b.proposed_series = canonical
                                rec_b.series_source = 'filename_prefix_pattern'
                                _prefix_series_count += 1
                            break
            if _prefix_series_count:
                print(f"[POST-CHECK] Assigned series via filename prefix pattern: {_prefix_series_count} records")
                self.logger.log(f"[OK] POST-CHECK: filename prefix pattern → {_prefix_series_count} series assigned")

            # ===== Clear series for collections/compilations =====
            if progress_callback:
                progress_callback(90, 100, "Финальная обработка")
            self._clear_series_for_compilations()
            self.logger.log("[OK] Series cleared for compilations")

            # ===== Final sanitization: strip folder-illegal chars from all series/authors =====
            # Backslash (\) сохраняем в series — это разделитель иерархии "Серия\Подсерия".
            _ILLEGAL_AUTHOR = re.compile(r'[\\/:*?"<>=|]')
            _ILLEGAL_SERIES = re.compile(r'[/:*?"<>=|]')   # без backslash

            def _replace_colon_in_series(s: str) -> str:
                """Replace ':' with '. ' and capitalize the next word."""
                def _repl(m):
                    rest = m.string[m.end():]
                    # Find next non-space character
                    stripped = rest.lstrip(' ')
                    if stripped:
                        capitalized = stripped[0].upper() + stripped[1:]
                        return '. ' + capitalized[:len(stripped)]
                    return '. '
                # Replace colon + optional spaces with ". " + capitalized next char
                result = re.sub(r':\s*([^\s]?)', lambda m: '. ' + m.group(1).upper() if m.group(1) else '.', s)
                return result

            _abbr_re = re.compile(r'\b[А-ЯЁA-Z][а-яёa-zA-Z]?\.$')

            def _strip_trailing_dot(s: str) -> str:
                """Strip trailing punctuation except a period that belongs to an abbreviation."""
                stripped = s.rstrip('.,…;: \t').rstrip('.')
                # If the original ended with an abbreviated initial (e.g. "Таннер А." or "Бреннан Дж."),
                # restore the trailing period.
                if s.endswith('.') and _abbr_re.search(s):
                    stripped = stripped.rstrip() + '.'
                return stripped

            for rec in self.records:
                if rec.proposed_series:
                    # First replace ':' with '. Capitalized'
                    rec.proposed_series = _replace_colon_in_series(rec.proposed_series)
                    # Then strip remaining illegal chars (excluding ':' already handled)
                    rec.proposed_series = re.sub(r'[/*?"<>=|]', '', rec.proposed_series).strip()
                    rec.proposed_series = _strip_trailing_dot(rec.proposed_series)
                    # Capitalize first letter
                    if rec.proposed_series:
                        rec.proposed_series = rec.proposed_series[0].upper() + rec.proposed_series[1:]
                if rec.proposed_author:
                    rec.proposed_author = _ILLEGAL_AUTHOR.sub('', rec.proposed_author).strip()
                    rec.proposed_author = _strip_trailing_dot(rec.proposed_author)
            self.logger.log("[OK] Final sanitization applied")
            
            # ===== Save CSV =====
            if self._do_save_csv:
                if progress_callback:
                    progress_callback(95, 100, "Сохранение CSV")
                self._save_csv()
                self.logger.log(f"[OK] CSV saved to {self.output_csv}")
            
            print(f"\n[OK] CSV regeneration completed successfully!")
            print(f"   Output: {self.output_csv}")
            print(f"   Records: {len(self.records)}")
            print("="*80 + "\n")
            
            if progress_callback:
                progress_callback(100, 100, "Завершено")
            
            return True
            
        except Exception as e:
            self.logger.log(f"[ERROR] CSV regeneration failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _clear_series_for_compilations(self) -> None:
        """Clear series for compilation/collection records.
        
        If proposed_author contains collection keyword, 
        proposed_series should be empty.
        """
        for record in self.records:
            if not record.proposed_author:
                continue
            
            author_lower = record.proposed_author.lower()
            
            # Check if author contains collection keyword
            if any(kw.lower() in author_lower for kw in self.collection_keywords):
                # Clear the series for compilations
                record.proposed_series = ""
                record.series_source = ""
    
    def _clear_collection_folder_series(self) -> None:
        """Финальный пост-чек: папка серии всегда внутри папки автора.

        Если папка содержит книги разных авторов (коллекция), её имя не является серией
        ни из какого источника. Сбрасываем proposed_series для всех файлов в такой папке,
        если серия совпадает с именем папки.
        """
        from collections import defaultdict
        from pathlib import Path as _P

        folder_files: dict = defaultdict(list)
        for record in self.records:
            folder_files[str(_P(record.file_path).parent)].append(record)

        cleared = 0
        for folder_path, files_in_folder in folder_files.items():
            # Используем proposed_author (нормализован pass3) для определения авторского состава.
            unique_authors = {
                f.proposed_author.strip()
                for f in files_in_folder
                if f.proposed_author and f.proposed_author.strip() not in ('', 'Сборник')
            }
            if len(unique_authors) <= 1:
                continue

            folder_name_norm = _P(folder_path).name.lower().replace('ё', 'е').strip()

            for record in files_in_folder:
                if not record.proposed_series:
                    continue
                ps_norm = record.proposed_series.lower().replace('ё', 'е').strip()
                if ps_norm == folder_name_norm or folder_name_norm.startswith(ps_norm) or ps_norm.startswith(folder_name_norm):
                    record.proposed_series = ''
                    record.series_source = ''
                    cleared += 1

        if cleared:
            print(f"[POST-CHECK] Cleared {cleared} collection-folder series (multi-author folders)")
            self.logger.log(f"[OK] POST-CHECK: Cleared {cleared} series from multi-author collection folders")

    def _save_csv(self) -> None:
        """Save records to CSV file."""


        # Финальная очистка: серия из папки-коллекции (несколько авторов).
        # Запускается ПОСЛЕ всех пасов и rescue-блоков — чтобы перекрыть любые источники.
        self._clear_collection_folder_series()

        # Sort by file_path
        self.records.sort(key=lambda r: r.file_path)
        
        # Write to CSV
        with open(self.output_csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                'file_path',
                'metadata_authors',
                'proposed_author',
                'author_source',
                'metadata_series',
                'proposed_series',
                'series_source',
                'series_number',
                'file_title',
                'metadata_genre'
            ])

            # Write data
            for record in self.records:
                writer.writerow([
                    record.file_path,
                    record.metadata_authors,
                    record.proposed_author,
                    record.author_source,
                    record.metadata_series,
                    record.proposed_series,
                    record.series_source,
                    record.series_number,
                    record.file_title,
                    record.metadata_genre
                ])


def main():
    """Main entry point."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    service = RegenCSVService(config_path)
    success = service.regenerate()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
