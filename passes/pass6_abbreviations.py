"""
PASS 6: Expand author abbreviations to full names.
"""

from typing import List, Dict, Optional
import re
from author_normalizer_extended import AuthorNormalizer
from settings_manager import SettingsManager
from logger import Logger


class Pass6Abbreviations:
    """PASS 6: Expand author abbreviations to full names.
    
    Build a dictionary of full author names and use it to expand abbreviations:
    - "Фамилия И." → "Фамилия Имя"
    - "И.Фамилия" → "Имя Фамилия" 
    - "А.Михайловский, А.Харников" → "Александр Михайловский, Александр Харников" (multi-author)
    """
    
    def __init__(self, logger, settings=None):
        """Initialize PASS 6.
        
        Args:
            logger: Logger instance
            settings: Optional shared SettingsManager
        """
        self.logger = logger
        self.py_logger = logger  # Reference to system logger
        try:
            self.settings = settings or SettingsManager('config.json')
        except:
            self.settings = None
        self.normalizer = AuthorNormalizer(self.settings)
    
    def execute(self, records: List) -> None:
        """Execute PASS 6: Expand abbreviations and incomplete author names.
        
        Two-pass algorithm:
        1. First pass: Build complete authors_map from ALL records
        2. Second pass: Expand abbreviations and incomplete names using full map
        
        This allows forward references: a file can be expanded using information
        from files that appear later in the list.
        
        Two operations:
        1. Expand abbreviations: "Петров И." → "Петров Иван"
        2. Expand incomplete names: "Живой" → "Живой Алексей" (using cache from other files)
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 6] Expanding abbreviations and incomplete names...")
        
        # PASS 1: Build complete authors map from ALL records
        print("[PASS 6]   Building author cache from all records...")
        authors_map = self._build_authors_map(records)
        
        # PASS 2: Expand abbreviations and incomplete names
        expanded_count = 0
        
        for record in records:
            if record.proposed_author == "Сборник":
                continue
            
            original = record.proposed_author
            
            # Check for multi-author case with both separators ('; ' from folder, ', ' from filename)
            if '; ' in record.proposed_author:
                authors = record.proposed_author.split('; ')
                expanded_authors = [self._expand_author(a, authors_map) for a in authors]
                record.proposed_author = '; '.join(expanded_authors)
            elif ', ' in record.proposed_author:
                authors = record.proposed_author.split(', ')
                expanded_authors = [self._expand_author(a, authors_map) for a in authors]
                record.proposed_author = ', '.join(expanded_authors)
            else:
                record.proposed_author = self._expand_author(original, authors_map)
            
            if record.proposed_author != original:
                expanded_count += 1
        
        self.logger.log(f"[PASS 6] Expanded {expanded_count} author names")

        # Финальная проверка: серия не может совпадать с автором
        cleared_count = 0
        for record in records:
            if record.proposed_series and record.proposed_author:
                series_norm = record.proposed_series.strip().lower().replace('ё', 'е')
                author_norm = record.proposed_author.strip().lower().replace('ё', 'е')
                if series_norm == author_norm:
                    record.proposed_series = ""
                    record.series_source = ""
                    cleared_count += 1
        if cleared_count:
            self.logger.log(f"[PASS 6] Cleared {cleared_count} series values that matched author name")

    def _expand_author(self, author: str, authors_map: Dict[str, List[str]]) -> str:
        """Expand a single author name using authors_map.
        
        Handles two cases:
        1. Abbreviations: "Петров И." → "Петров Иван"
        2. Incomplete names: "Живой" → "Живой Алексей" (single word)
        
        Selects the FULLEST name (most words) from alternatives for better quality.
        
        Args:
            author: Single author name (not multi-author)
            authors_map: Dictionary {surname.lower(): [full_names]}
            
        Returns:
            Expanded author name or original if no expansion found
        """
        author = author.strip()
        if not author:
            return author
        
        # Try abbreviation expansion first (has priority)
        if '.' in author:
            return self.normalizer.expand_abbreviation(author, authors_map)
        
        # Check if this is an incomplete name (single word)
        words = author.split()
        if len(words) == 1:
            # Single word - try to expand using authors_map
            surname_lower = words[0].lower()
            if surname_lower in authors_map:
                # Found matching surnames - pick the FULLEST name (most words)
                full_names = authors_map[surname_lower]
                best_name = max(full_names, key=lambda x: len(x.split()))
                
                if len(best_name.split()) > 1:  # Only expand if found a fuller version
                    return best_name
        
        # No expansion needed or found
        return author
    
    
    def _build_authors_map(self, records: List) -> Dict[str, List[str]]:
        """Build dictionary of full author names for abbreviation expansion.
        
        Result: {"петров": ["Петров Иван", "Петров Сергей"]}
        Key is surname in lowercase, values are full names.
        
        Args:
            records: List of BookRecord objects
            
        Returns:
            Dictionary {surname.lower(): [full_names]}
        """
        authors_map: Dict[str, List[str]] = {}
        seen = set()      # нормализованные строки — дедупликация результатов
        seen_raw = set()  # сырые строки — пропускаем normalize_format если уже видели
        norm_cache: Dict[str, str] = {}  # raw → normalized, избегаем повторных вызовов

        def _add(normalized: str) -> None:
            """Добавить нормализованного автора в authors_map."""
            if not normalized or normalized in seen:
                return
            parts = normalized.split()
            if not parts:
                return
            key = parts[0].lower()
            if key:
                authors_map.setdefault(key, []).append(normalized)
                seen.add(normalized)

        def _normalize_cached(raw: str) -> str:
            if raw not in norm_cache:
                norm_cache[raw] = self.normalizer.normalize_format(raw)
            return norm_cache[raw]

        # Collect from proposed_author (already processed)
        for record in records:
            if record.proposed_author and record.proposed_author != "Сборник":
                author = record.proposed_author
                if ', ' in author:
                    for single_author in author.split(', '):
                        single_author = single_author.strip()
                        if single_author and '.' not in single_author:
                            _add(single_author)
                else:
                    if '.' not in author:
                        _add(author)

            # Collect from metadata_authors (original source - best for abbreviation expansion)
            if record.metadata_authors and record.metadata_authors != "Сборник":
                author = record.metadata_authors
                sep = ', ' if ', ' in author else ('; ' if '; ' in author else None)
                if sep:
                    for single_author in author.split(sep):
                        single_author = single_author.strip()
                        if single_author and single_author not in seen_raw:
                            seen_raw.add(single_author)
                            _add(_normalize_cached(single_author))
                else:
                    if author not in seen_raw:
                        seen_raw.add(author)
                        _add(_normalize_cached(author))

        return authors_map
