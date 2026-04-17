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

            # Пункт 5: cache normalized name lookups — avoids repeated re.sub() calls
            #          for the same strings across thousands of records.
            _norm_cache: dict = {}

            def _norm(name: str) -> str:
                if name not in _norm_cache:
                    _norm_cache[name] = self._normalize_name_for_comparison(name)
                return _norm_cache[name]

            # Пункт 6: cache Path(...).parts per file_path to avoid constructing
            #          a new Path object on each iteration.
            _parts_cache: dict = {}

            for record in self.records:
                if record.proposed_series:
                    continue  # Skip if series already set

                # Пункт 6: use cached path parts
                file_path_parts = _parts_cache.get(record.file_path)
                if file_path_parts is None:
                    raw_parts = Path(record.file_path).parts
                    # Фильтруем папки с именами-расширениями (последний элемент = имя файла, не фильтруем)
                    file_path_parts = tuple(
                        p for i, p in enumerate(raw_parts)
                        if i == len(raw_parts) - 1 or p.lower() not in FILE_EXTENSION_FOLDER_NAMES
                    )
                    _parts_cache[record.file_path] = file_path_parts

                # Key Strategy: Find author folder in path and skip it
                # Everything below author folder = series/subseries
                author_folder_index = -1  # Not found by default

                if record.proposed_author:
                    # Поиск папки автора с учётом формы множественного числа фамилии
                    # и нескольких авторов (Живов Геннадий, Живов Георгий ↔ Живовы Георгий и Геннадий)
                    for idx, part in enumerate(file_path_parts[:-1]):  # Exclude filename
                        if self._surnames_match_folder(record.proposed_author, part):
                            author_folder_index = idx
                            break  # Found the author folder
                
                # Now extract series based on structure AFTER author folder
                if author_folder_index >= 0 and len(file_path_parts) > author_folder_index + 1:
                    # We found author folder, extract series folders after it
                    series_folders = file_path_parts[author_folder_index + 1 : -1]  # Exclude author folder and filename
                    

                    if len(series_folders) == 0:
                        # No series folder (file directly in author folder)
                        # ВАЖНО: Оставляем proposed_series пустым чтобы дать возможность:
                        # 1. Pass 2 попытаться извлечь из filename (приоритет 2)
                        # 2. Потом применить metadata как fallback (приоритет 1)
                        # Это соблюдает cascade priority: FOLDER(3) > FILENAME(2) > METADATA(1)
                        # Do NOT set series_source here - let following passes handle it
                        pass
                    elif any(is_no_series_folder(f, self._no_series_names) for f in series_folders):
                        # Папка «Вне серий» / «Без серии» — явный признак отсутствия серии.
                        # Фиксируем пустую серию и блокируем дальнейшее извлечение.
                        record.proposed_series = ""
                        record.series_source = "no_series_folder"
                    else:
                        # Hierarchical OR simple series: Author / Series [/ SubSeries ...] / File
                        # NOTE: Папка автора НЕ включается в иерархию серии
                        # Серия содержит только папки после папки автора
                        
                        all_folders = list(series_folders)
                        series_names = [self._extract_series_from_folder_name(folder) for folder in all_folders]
                        series_combined = "\\".join(series_names)
                        if series_combined:  # Only set source if we actually got a series
                            record.proposed_series = series_combined
                            record.series_source = "folder_dataset"

                elif len(file_path_parts) >= 4:
                    # No author folder found, but depth >= 4 (Old behavior: Coll / FB2 / Author / Series / File)
                    # Only use fallback if we're confident this is actually a series folder structure
                    # Skip if we can't reliably identify series vs author folders
                    
                    # Don't use this fallback at all - let Pass 2 (filename extraction) and metadata
                    # handle series extraction. Fallback was too unreliable for depth >= 4 without
                    # knowing author folder position upfront (proposed_author not yet available in Pass 1)
                    pass
                
                elif len(file_path_parts) == 3:
                    # Depth 3: Coll / Series / File
                    # Правило: папка серии возможна ТОЛЬКО внутри папки автора.
                    # Если author_folder_index < 0 — папки автора нет, middle-папка
                    # является жанровой/издательской структурой, не серией книг.
                    # folder_dataset для серии при отсутствии folder_dataset автора — недопустимо.
                    pass  # Let Pass 2 (filename patterns) and metadata handle series extraction
            
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

            def _strip_trailing_dot(s: str) -> str:
                """Strip trailing punctuation (dots, commas, ellipsis, etc.) but keep '!'."""
                return s.rstrip('.,…;: \t').rstrip('.')

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
    
    def _save_csv(self) -> None:
        """Save records to CSV file."""
        

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
