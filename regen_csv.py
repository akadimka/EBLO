#!/usr/bin/env python3
"""
CSV Regeneration Service - 6-PASS Architecture 2.0 (Modular Edition)

PRECACHE + PASS 1-6 system with each PASS in separate module.

Reference: REGEN_CSV_ARCHITECTURE.md
"""

import csv
import sys
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
        
        # Author folder cache from PRECACHE
        self.author_folder_cache = {}
        
        # CSV output path - ALWAYS in project directory
        self.project_dir = Path(__file__).parent
        self.output_csv = self.project_dir / "regen.csv"
    
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
    
    def _contains_blacklist_word_regen(self, text: str) -> bool:
        """
        Проверить, содержит ли text слово(а) из blacklist (заимствовано от Pass2).
        
        Используется для фильтрации folder names - папка "Боевая фантастика. Циклы"
        содержит слово "боевая фантастика" (жанр), поэтому НЕ может быть series.
        
        Args:
            text: Проверяемый текст (название папки)
            
        Returns:
            True если найдено хотя бы одно blacklist слово, False иначе
        """
        blacklist = self.settings.get_list('filename_blacklist')
        if not text or not blacklist:
            return False
        
        text_lower = text.lower()
        
        # Проходим по каждому слову в blacklist
        for bl_word in blacklist:
            bl_word_lower = bl_word.lower().strip()
            if not bl_word_lower:
                continue
            
            # Проверяем наличие как целого слова (word boundary check)
            import re
            pattern = r'(?:^|\W)' + re.escape(bl_word_lower) + r'(?:\W|$)'
            if re.search(pattern, text_lower):
                return True
        
        return False
    
    def regenerate(self) -> bool:
        """Execute full CSV regeneration pipeline.
        
        Returns:
            True if successful, False otherwise
        """
        try:
            print("\n" + "="*80)
            print("  CSV REGENERATION - 6-PASS SYSTEM (Modular)")
            print(f"  Work folder: {self.work_dir}\n")
            print("="*80 + "\n")
            
            self.logger.log("=== Starting CSV regeneration ===")
            
            # ===== PRECACHE =====
            precache = Precache(self.work_dir, self.settings, self.logger, 
                               self.folder_parse_limit)
            self.author_folder_cache = precache.execute()
            self.logger.log("[OK] Author folder hierarchy cached")
            
            # ===== PASS 1 =====
            pass1 = Pass1ReadFiles(self.work_dir, self.author_folder_cache,
                                  self.extractor, self.logger, 
                                  self.folder_parse_limit)
            self.records = pass1.execute()
            
            if not self.records:
                self.logger.log("[X] No FB2 files found")
                return False
            
            self.logger.log(f"[OK] PASS 1: Read {len(self.records)} files")
            
            # ===== PASS 2 =====
            pass2 = Pass2Filename(self.settings, self.logger, self.work_dir,
                                male_names=precache.male_names,
                                female_names=precache.female_names)
            pass2.prebuild_author_cache(self.records)
            pass2.execute(self.records)
            self.logger.log("[OK] PASS 2: Authors extracted from filenames")
            
            # ===== PASS 2 Fallback =====
            pass2_fallback = Pass2Fallback(self.logger)
            pass2_fallback.execute(self.records)
            self.logger.log("[OK] PASS 2 Fallback: Metadata applied")
            
            # ===== SERIES EXTRACTION: From Folders (VARIANT B) =====
            print("\n[SERIES] Extracting series from folder structure...")
            for record in self.records:
                if record.proposed_series:
                    continue  # Skip if series already set
                
                # Extract series from file path structure
                file_path_parts = Path(record.file_path).parts
                

                # Key Strategy: Find author folder in path and skip it
                # Everything below author folder = series/subseries
                author_folder_index = -1  # Not found by default
                
                if record.proposed_author:
                    # Try to find which folder is the author folder
                    # by comparing folder names with proposed_author
                    # (Check regardless of author_source because author might be from filename extraction)
                    for idx, part in enumerate(file_path_parts[:-1]):  # Exclude filename
                        if self._is_author_folder(part, record.proposed_author):
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
                    elif len(series_folders) == 1:
                        # Simple series: Author / Series / File
                        series_name = self._extract_series_from_folder_name(series_folders[0])
                        if series_name:  # Only set source if we actually got a series name
                            record.proposed_series = series_name
                            record.series_source = "folder_dataset"

                    else:
                        # Hierarchical series: Author / MainSeries / SubSeries / ... / File
                        series_names = [self._extract_series_from_folder_name(folder) for folder in series_folders]
                        series_combined = "\\".join(series_names)
                        if series_combined:  # Only set source if we actually got a series
                            record.proposed_series = series_combined
                            record.series_source = "folder_dataset"

                elif len(file_path_parts) >= 4:
                    # No author folder found, but depth >= 4 (Old behavior: Coll / FB2 / Author / Series / File)
                    # Try old logic as fallback

                    main_series = self._extract_series_from_folder_name(file_path_parts[-3])
                    sub_series = self._extract_series_from_folder_name(file_path_parts[-2])
                    
                    # Check if parts look fishy (contain known authors from config)
                    # If main_series or sub_series look like author names, skip
                    looks_like_author = (
                        self._normalize_name_for_comparison(main_series) in 
                        [self._normalize_name_for_comparison(name) for name in 
                         (self.settings.get_list('male_names') + self.settings.get_list('female_names'))]
                    )
                    
                    if not looks_like_author:
                        # Combine with backslash: "MainSeries\SubSeries"
                        series_combined = f"{main_series}\\{sub_series}"
                        if series_combined:  # Only set source if we got something
                            record.proposed_series = series_combined
                            record.series_source = "folder_dataset"

                    # else: skip when looks suspicious, will use metadata fallback via Pass 2
                
                elif len(file_path_parts) == 3:
                    # Depth 3: Coll / Series / File
                    # Only if author_folder_index not found
                    if author_folder_index < 0:
                        series_folder_name = file_path_parts[-2]
                        series_name = self._extract_series_from_folder_name(series_folder_name)
                        if series_name:  # Only set source if we got a series
                            # ✅ НОВОЕ: Проверить что папка не содержит blacklist слова!
                            # Папка типа "Боевая фантастика. Циклы" НЕ может быть series
                            # потому что "боевая фантастика" это ЖАНР, не series
                            if not self._contains_blacklist_word_regen(series_name):
                                record.proposed_series = series_name
                                record.series_source = "folder_dataset"
            
            self.logger.log("[OK] Series extracted from folder structure (Variant B)")
            
            # ===== SERIES PASS 2 =====
            print("[SERIES] Extracting series from filenames...")
            pass2_series = Pass2SeriesFilename(self.logger,
                                              male_names=precache.male_names,
                                              female_names=precache.female_names)
            pass2_series.execute(self.records)
            self.logger.log("[OK] Series PASS 2: Extracted from filenames")
            
            # ===== SERIES PASS 3 =====
            print("[SERIES] Normalizing series names...")
            pass3_series = Pass3SeriesNormalize(self.logger)
            pass3_series.execute(self.records)
            self.logger.log("[OK] Series PASS 3: Normalized series names")
            
            # ===== PASS 3 =====
            pass3 = Pass3Normalize(self.logger)
            pass3.execute(self.records)
            self.logger.log("[OK] PASS 3: Authors normalized")
            
            # ===== PASS 4 =====
            pass4 = Pass4Consensus(self.logger)
            pass4.execute(self.records)
            self.logger.log("[OK] PASS 4: Consensus applied")
            
            # ===== PASS 5 =====
            pass5 = Pass5Conversions(self.logger)
            pass5.execute(self.records)
            self.logger.log("[OK] PASS 5: Conversions re-applied")
            
            # ===== PASS 6 =====
            pass6 = Pass6Abbreviations(self.logger)
            pass6.execute(self.records)
            self.logger.log("[OK] PASS 6: Abbreviations expanded")
            
            # ===== Clear series for collections/compilations =====
            self._clear_series_for_compilations()
            self.logger.log("[OK] Series cleared for compilations")
            
            # ===== Save CSV =====
            self._save_csv()
            self.logger.log(f"[OK] CSV saved to {self.output_csv}")
            
            print(f"\n✅ CSV regeneration completed successfully!")
            print(f"   Output: {self.output_csv}")
            print(f"   Records: {len(self.records)}")
            print("="*80 + "\n")
            
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
                'file_title'
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
                    record.file_title
                ])


def main():
    """Main entry point."""
    config_path = sys.argv[1] if len(sys.argv) > 1 else 'config.json'
    
    service = RegenCSVService(config_path)
    success = service.regenerate()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
