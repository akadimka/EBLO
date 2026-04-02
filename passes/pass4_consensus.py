"""
PASS 4: Apply consensus author to files in same folder.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional
from author_normalizer_extended import AuthorNormalizer
from settings_manager import SettingsManager


class Pass4Consensus:
    """PASS 4: Apply consensus author to files in same folder.
    
    For each folder group:
    1. Identify "determined" files with reliable source (folder_dataset, metadata, consensus)
    2. Identify "undetermined" files (empty or filename source)
    3. Apply consensus author (most common) to undetermined files
    
    ⚠️ CRITICAL: Files with ANY successful source are NEVER overwritten!
    - folder_dataset: Extracted from folder hierarchy
    - filename: Successfully parsed from file name  
    - metadata: From FB2 XML metadata
    - consensus: Already has consensus from previous folder
    - empty string: Only undetermined files get new consensus
    """
    
    def __init__(self, logger, settings=None):
        """Initialize PASS 4.
        
        Args:
            logger: Logger instance
            settings: Optional shared SettingsManager
        """
        self.logger = logger
        try:
            self.settings = settings or SettingsManager('config.json')
        except:
            self.settings = None
        self.normalizer = AuthorNormalizer(self.settings)
        # Cache for _normalize_series_for_consensus results
        self._series_norm_cache: dict = {}
    
    def _normalize_series_for_consensus(self, series_candidate: str) -> str:
        """
        Normalize series candidate for consensus comparison.
        Removes volume numbers so "Охотник 1" and "Охотник 2" match as same series.
        
        Args:
            series_candidate: Raw series candidate string
        
        Returns:
            Normalized series name
        """
        if not series_candidate:
            return ""

        cached = self._series_norm_cache.get(series_candidate)
        if cached is not None:
            return cached

        import re

        text = series_candidate.strip()
        
        # Remove " N" or " N. " patterns (space + digits)
        # "Охотник 1" → "Охотник"
        # "Охотник 2. Something" → "Охотник"  
        text = re.sub(r'\s+\d+[\s\.\:].*$', '', text).strip()
        
        # Remove trailing digits after space
        # "Охотник 1" → "Охотник"
        text = re.sub(r'\s+\d+\s*$', '', text).strip()
        
        # Remove trailing digits after hyphen (but keep the base, e.g. "Фэндом-3" → "Фэндом")
        text = re.sub(r'[-–—]\d+\s*$', '', text).strip()

        result = text if text else series_candidate
        self._series_norm_cache[series_candidate] = result
        return result
    
    def execute(self, records: List) -> None:
        """Execute PASS 4: Apply consensus author.
        
        Group records by folder and apply consensus author to undetermined files.
        Protected files (folder_dataset, metadata) are not overwritten.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 4] Applying consensus...")
        
        # CLEANUP: Remove false "series" that are actually just titles/subtitles
        # These are single-appearance series with no numbering/service words markers
        # Example: "Осень 93-го" or "Баржа Т-36" (no other files in author's catalog with these series)
        print("[PASS 4] Cleaning up false series (single-file titles)...")
        false_series_count = 0
        
        # Build series frequency map by author
        import re
        author_series_count = {}
        for record in records:
            if record.proposed_series:
                author = record.proposed_author or "[unknown]"
                series = record.proposed_series
                
                key = (author, series)
                if key not in author_series_count:
                    author_series_count[key] = []
                author_series_count[key].append(record)
        
        # Load service words from config (markers that indicate THIS IS a series, not just a title)
        service_markers = set(self.settings.get_list('service_words')) if self.settings else set()
        
        # Check each (author, series) pair
        for (author, series), records_with_series in author_series_count.items():
            # If this series appears only ONCE (not a real series)
            if len(records_with_series) == 1:
                record = records_with_series[0]
                
                # PROTECTION: If series came from folder structure (folder_dataset),
                # DO NOT remove it! Folders are trusted sources
                if record.series_source == "folder_dataset":
                    continue  # Trust folder-based series, don't remove
                
                # Check if series contains service markers that indicate it's a real series
                series_lower = series.lower()
                has_service_marker = any(marker in series_lower for marker in service_markers)
                
                # FIX: Check if series is confirmed in metadata BEFORE removing it
                # Even if it's a single-file series from filename, if metadata confirms it,
                # we should keep it
                is_confirmed_in_metadata = (
                    record.metadata_series and 
                    record.metadata_series.strip().lower() == series.lower()
                )
                
                # NEW FIX: Check if the filename contains evidence of a legitimate series pattern
                # Pattern: "(Series. service_word)" or "(Series service_word)" like "(Солдат удачи. Тетралогия)" or "(Эпоха перемен Трилогия)"
                # Also handles "(Series N. Additional info. service_word)" like "(Мир вечного 1. Охота на охотника. Тетралогия)"
                # Also recognizes "(Series N-M)" patterns which are multi-file series indicators like "(Легион 1-3)", "(Легион 4-6)"
                # Also recognizes "(Novels/Romany из цикла «Series»)" patterns like "(Романы из цикла «Артуа»)"
                # This indicates the original filename HAD a service word or multi-file pattern before extraction
                has_pattern_evidence = False
                if record.file_path and record.series_source == "filename":
                    filename = Path(record.file_path).name
                    
                    # Find ALL brackets in the filename
                    all_brackets = re.findall(r'\([^)]*\)', filename)
                    
                    for bracket_content in all_brackets:
                        bracket_lower = bracket_content.lower()
                        
                        # Check if this bracket content has service markers
                        have_service_marker_in_brackets = any(marker in bracket_lower for marker in service_markers)
                        if have_service_marker_in_brackets:
                            has_pattern_evidence = True
                            break
                        
                        # Check for multi-file patterns like "N-M" which strongly indicate series
                        if re.search(r'\d+[-,]\d+', bracket_content):
                            has_pattern_evidence = True
                            break
                        
                        # Check for "из цикла" or "из серии" patterns
                        # Examples: (Романы из цикла «Артуа»), (Книги из цикла «Серия»)
                        if re.search(r'из\s+(?:цикла|серии)', bracket_lower):
                            has_pattern_evidence = True
                            break
                        
                        # Check для multi-level series patterns like "Series N. SubSeries M. SubSubSeries K"
                        # Examples: (Сид 1. Принцип талиона 1. Геката 1), (Война 1. Мир 2. Система 3)
                        # Наличие 2+ точек-пробелов является веским доказательством иерархической структуры серии
                        if bracket_content.count('. ') >= 2:
                            has_pattern_evidence = True
                            break
                
                # If NO service markers AND from filename source AND NOT confirmed in metadata
                # AND NOT from a legitimate (Series. service_words) pattern
                # → Check if this is in a Series Collection folder before removing
                if (not has_service_marker and record.series_source == "filename" and 
                    not is_confirmed_in_metadata and not has_pattern_evidence):
                    
                    # EXCEPTION: If file is in a Series Collection folder (depth=2 with "Серия" in parent name),
                    # Trust the extraction because it came from a reliable "Author - Series N. Title" pattern
                    is_series_collection_folder = False
                    if record.file_path:
                        file_path_parts = Path(record.file_path).parts
                        if len(file_path_parts) >= 1:
                            parent_folder = file_path_parts[0]
                            # Check if parent folder is a Series Collection
                            is_series_collection_folder = (
                                parent_folder.startswith('Серия') or
                                'Серия' in parent_folder
                            )
                    
                    # Only clear if it's NOT in a Series Collection folder
                    if not is_series_collection_folder:
                        # Clear it
                        record.proposed_series = ""
                        record.series_source = ""
                        false_series_count += 1

        
        self.logger.log(f"[PASS 4] Removed {false_series_count} false series (single-file titles)")
        
        # SPECIAL HANDLING: If metadata contains specific series values, they take absolute priority
        # These values override all other extraction methods
        special_series_values = self.settings.get_list('special_series_values') if self.settings else []
        
        for record in records:
            if record.metadata_series:
                metadata_series = record.metadata_series.strip()
                if metadata_series in special_series_values:
                    # This metadata value has absolute priority
                    record.proposed_series = metadata_series
                    record.series_source = "metadata"
        
        # ⚠️ REMOVED: METADATA AUTHOR CONFIRMATION logic
        # This logic was attempting to "improve" authors by cross-checking with metadata,
        # but this is fundamentally wrong:
        # 
        # 1. folder_dataset source is AUTHORITATIVE (user explicitly created folder hierarchy)
        #    → MUST NOT be modified or questioned
        # 
        # 2. Cross-checking with metadata is:
        #    - Resource-intensive (requires parsing every FB2 file)
        #    - Ineffective (metadata may be worse quality than folder_dataset)
        #    - Logically incorrect (damages confidence in folder-based extraction)
        # 
        # 3. Correct strategy:
        #    - folder_dataset → Final and should never be changed
        #    - filename → Can check metadata only if extraction is incomplete
        #    - metadata → Sufficient on its own, no need to cross-check
        
        # Group by folder
        groups: Dict[Path, List] = {}
        for record in records:
            folder = Path(record.file_path).parent
            if folder not in groups:
                groups[folder] = []
            groups[folder].append(record)
        
        consensus_count = 0
        
        # Process each group
        for folder, group_records in groups.items():
            # Separate determined and undetermined files
            # DETERMINED: files with ANY successful source (folder_dataset, metadata, consensus, filename)
            # UNDETERMINED: files with empty source only
            determined = [r for r in group_records 
                         if r.author_source in ["folder_dataset", "metadata", "metadata_folder_confirmed", "consensus", "filename", "filename_meta_confirmed"]]
            undetermined = [r for r in group_records 
                           if r.author_source == ""]
            
            if not determined or not undetermined:
                continue
            
            # Find consensus author from determined files  
            author_counts = {}
            for record in determined:
                if record.proposed_author and record.proposed_author != "Сборник":
                    author_counts[record.proposed_author] = \
                        author_counts.get(record.proposed_author, 0) + 1
            
            if not author_counts:
                continue
            
            consensus_author = max(author_counts, key=author_counts.get)
            
            # Apply to all undetermined files (only empty ones)
            for record in undetermined:
                if record.proposed_author and record.proposed_author != "Сборник":
                    # Update with consensus
                    if record.proposed_author != consensus_author:
                        record.proposed_author = consensus_author
                        record.author_source = "consensus"
                        consensus_count += 1
                elif not record.proposed_author:
                    # Apply consensus to empty records
                    record.proposed_author = consensus_author
                    record.author_source = "consensus"
                    consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied consensus to {consensus_count} records")
        
        # SERIES CONSENSUS: Apply consensus series to files in same folder
        # IMPORTANT: Only apply to files that have extracted_series_candidate matching
        # the consensus candidate. This prevents applying unrelated series to files
        # that only happen to be in the same folder.
        # GROUP BY AUTHOR for consensus calculation
        # Build author groups: author → [records]
        author_groups = {}
        for record in records:
            author = record.proposed_author or "[unknown]"
            if author not in author_groups:
                author_groups[author] = []
            author_groups[author].append(record)
        
        # AUTHOR-BASED SERIES CONSENSUS: Match files by sequence in filename
        # For each author group, find files with same series_base that have proposed_series
        # and apply to files without series_candidate
        series_consensus_count = 0
        
        for author, author_records in author_groups.items():
            # Build map: series_base → [records with proposed_series from extracted_series_candidate]
            series_base_map = {}
            
            for record in author_records:
                if record.extracted_series_candidate:
                    # Extract series_base from proposed_series (remove volume numbers)
                    normalized = self._normalize_series_for_consensus(record.extracted_series_candidate)
                    if normalized not in series_base_map:
                        series_base_map[normalized] = []
                    series_base_map[normalized].append(record)
            
            # For each series_base, check if we have files without series_candidate
            # that match the series_base in their filename
            for series_base, source_records in series_base_map.items():
                # For each record without extracted_series_candidate
                for target_record in author_records:
                    if target_record.proposed_series and target_record.series_source not in ("metadata", "metadata_folder_confirmed"):
                        # Already has series from filename or other source, skip
                        # But try consensus if it's only from metadata or metadata confirmed by folder
                        continue
                    
                    if target_record.extracted_series_candidate:
                        # Already has extracted_series_candidate, would be caught earlier
                        continue
                    
                    # Check if target filename contains the same series_base as source
                    # Extract filename and check if it contains series_base
                    filename = Path(target_record.file_path).stem
                    
                    # Simple heuristic: series_base appears in the filename
                    # and it's likely the same series (case-insensitive, normalize spaces)
                    # Format: "Author - SeriesBase" or "Author - SeriesBase N" or "SeriesBase N" or "Author. Series"
                    series_base_normalized = series_base.lower().strip()
                    filename_normalized = filename.lower()
                    
                    # PROTECTION: Skip if series_base is too short (would match any single char)
                    # Example: "П" matches any word starting with "п" like "первый", "пятьдесят"
                    # Require at least 2 characters for a valid series name
                    if len(series_base_normalized) < 2:
                        continue
                    
                    # Check if filename contains series_base in the expected position
                    # Must be after author name (after " - " or after ". ") or at start
                    if series_base_normalized in filename_normalized:
                        # Verify it's at the right position: after author name or at position
                        # where series should be
                        dash_pos = filename_normalized.find(" - ")
                        dot_pos = filename_normalized.find(". ")
                        base_pos = filename_normalized.find(series_base_normalized)
                        
                        # Three patterns: "Author - Series", "Author. Series", or "Series ..." at start
                        applies = False
                        
                        if dash_pos >= 0 and base_pos > dash_pos:
                            # "Author - Series" pattern
                            applies = True
                        elif dot_pos >= 0 and base_pos > dot_pos:
                            # "Author. Series" pattern
                            applies = True
                        elif base_pos == 0:
                            # Series at start of filename
                            applies = True
                        
                        if applies:
                            # Не перезаписываем «Без серии»
                            if target_record.series_source == "no_series_folder":
                                continue
                            # Apply consensus
                            target_record.proposed_series = series_base
                            target_record.series_source = "author-consensus"
                            
                            # Check for metadata confirmation
                            if (target_record.metadata_series and 
                                self._normalize_series_for_consensus(target_record.metadata_series) == series_base):
                                target_record.series_source = "author-consensus (metadata-confirmed)"
                            
                            series_consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied author-based series consensus to {series_consensus_count} records")
        
        # METADATA SERIES CONSENSUS: For depth 2 files (Author/File)
        # Apply metadata_series consensus to files without proposed_series
        # This handles files that have metadata_series but it was rejected/empty
        print("[PASS 4] Applying metadata series consensus...")
        metadata_series_consensus_count = 0
        
        for folder, group_records in groups.items():
            # Count metadata_series occurrences (only from files with valid proposed_series)
            metadata_series_count = {}
            for record in group_records:
                # Consider medadata_series only if it resulted in proposed_series
                if record.metadata_series and record.proposed_series == record.metadata_series:
                    series = record.metadata_series
                    metadata_series_count[series] = metadata_series_count.get(series, 0) + 1
            
            # Only consider series that appear 2+ times
            consensus_metadata_series = {
                series: count 
                for series, count in metadata_series_count.items() 
                if count >= 2
            }
            
            if not consensus_metadata_series:
                continue
            
            # Apply to files with empty proposed_series if they have empty proposed_series
            for record in group_records:
                if (not record.proposed_series and 
                    record.series_source != "no_series_folder" and
                    record.metadata_series and 
                    record.metadata_series in consensus_metadata_series):
                    
                    record.proposed_series = record.metadata_series
                    record.series_source = "consensus"
                    metadata_series_consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied metadata series consensus to {metadata_series_consensus_count} records")
        
        # PROPOSED SERIES CONSENSUS: For files without extracted_series_candidate
        # Apply proposed_series from other files in same folder when multiple files agree
        # This handles series folders where some files don't have extractable series names
        print("[PASS 4] Applying proposed series fallback consensus...")
        proposed_consensus_count = 0
        
        for folder, group_records in groups.items():
            # Count proposed_series occurrences (only from files with valid proposed_series)
            proposed_count = {}
            for record in group_records:
                if record.proposed_series:
                    series = record.proposed_series
                    proposed_count[series] = proposed_count.get(series, 0) + 1
            
            # Only consider series that appear 2+ times
            consensus_proposed_series = {
                series: count 
                for series, count in proposed_count.items() 
                if count >= 2
            }
            
            if not consensus_proposed_series:
                continue
            
            # Apply to files with empty proposed_series if they're in a series folder
            for record in group_records:
                # Only apply if:
                # 1. File has no proposed_series yet (empty)
                # 2. Not extracted from extracted_series_candidate (would be caught earlier)
                # 3. A proposed_series appears 2+ times in the group
                # ВАЖНО: проверяем что extracted_series_candidate is None, не just falsey
                # Потому что "" (empty string) означает что это одна книга, не серия
                if (not record.proposed_series and 
                    record.series_source != "no_series_folder" and
                    record.extracted_series_candidate is None and
                    len(consensus_proposed_series) == 1):  # Only apply if unanimous consensus
                    
                    consensus_series = list(consensus_proposed_series.keys())[0]
                    record.proposed_series = consensus_series
                    record.series_source = "consensus"
                    proposed_consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied proposed series consensus to {proposed_consensus_count} records")
        
        # SERIES AUTHOR CONSENSUS (Variant 5: Combined Protective Approach)
        # For each series with multiple files, apply the most common author to all files
        # in that series. This handles cases where a multi-author series has inconsistent
        # author assignments across files.
        # 
        # CRITICAL SAFEGUARDS for filename sources:
        #   1. Skip if metadata_authors confirm the extracted author
        #   2. Skip if this author is UNIQUE in the series (appears only once)
        #   3. Skip if consensus percentage < 80% (insufficient majority)
        #   4. Only apply if all checks pass AND consensus >= 80%
        # 
        # folder_dataset: NEVER change (sacred, user-defined folder hierarchy)
        # metadata/consensus/empty: Apply consensus if different (low-quality sources)
        # 
        # Case Studies:
        #
        # Case 1: "Капитонов Николай - Наемник 1" (filename source, unique)
        #   - Series "Наемник": 6 files (5 Поселягин, 1 Капитонов)
        #   - Consensus: Поселягин (83.3%) → YES, above threshold
        #   - But Капитонов is UNIQUE (count=1) → SKIP (might be co-author)
        #   Result: UNCHANGED ✓
        #
        # Case 2: "Ипатова" in "Врата Валгаллы" (filename source, incomplete)
        #   - Series "Врата Валгаллы": 3 files
        #     * File 1: "Ильин, Ипатова" (filename)
        #     * File 2: "Ильин, Ипатова" (filename)
        #     * File 3: "Ипатова" (filename, incomplete name)
        #   - Consensus: "Ильин, Ипатова" (66.7%) → Below 80% threshold
        #   - Ипатова appears 3 times → Not unique
        #   - Metadata confirms "Ипатова" is Ипатова → Safeguard 1 should skip
        #   Result: UNCHANGED (by Safeguard 1 - metadata confirmation)
        print("[PASS 4] Applying series author consensus...")
        series_author_consensus_count = 0
        
        # Group records by proposed_series
        series_groups = {}
        for record in records:
            if record.proposed_series:
                series = record.proposed_series
                if series not in series_groups:
                    series_groups[series] = []
                series_groups[series].append(record)
        
        # Apply author consensus within each series
        for series, series_records in series_groups.items():
            # Only apply consensus if there are 2+ files in the series
            if len(series_records) < 2:
                continue
            
            # Count author occurrences (only for files with valid authors)
            author_counts = {}
            for record in series_records:
                if record.proposed_author and record.proposed_author != "Сборник":
                    author = record.proposed_author
                    author_counts[author] = author_counts.get(author, 0) + 1
            
            if not author_counts:
                continue
            
            # Find most common author (consensus)
            consensus_author = max(author_counts, key=author_counts.get)
            consensus_count = author_counts[consensus_author]
            consensus_percentage = (consensus_count / len(series_records)) * 100
            
            # HELPER: Check if current_author is a subset/incomplete version of consensus_author
            def is_author_subset(current_author, consensus_author):
                """
                Check if current_author is an incomplete/subset version of consensus_author.
                Examples:
                  - "Ипатова Наталия" is subset of "Ильин Сергей, Ипатова Наталия" → YES
                  - "Капитонов Николай" is subset of "Поселягин Владимир" → NO
                """
                if current_author == consensus_author:
                    # Exact match - should be handled by skip logic above
                    return False
                
                # Normalize and split into words
                current_words = set(current_author.lower().replace(',', '').split())
                consensus_words = set(consensus_author.lower().replace(',', '').split())
                
                # Check if all words from current are in consensus (is subset)
                # AND current has fewer words (is incomplete version)
                if current_words and consensus_words:
                    is_subset = current_words.issubset(consensus_words)
                    is_shorter = len(current_words) < len(consensus_words)
                    return is_subset and is_shorter
                
                return False
            
            for record in series_records:
                # Skip if already matches consensus
                if record.proposed_author == consensus_author or record.proposed_author == "Сборник":
                    continue
                
                # PROTECTION 1: Never touch folder_dataset
                if record.author_source == "folder_dataset":
                    continue
                
                # NEW LOGIC: Check if current author is a subset of consensus
                is_subset = is_author_subset(record.proposed_author, consensus_author)
                
                # For filename source
                if record.author_source in ("filename", "filename_meta_confirmed"):
                    if is_subset:
                        # Current author is incomplete version of consensus → DEFINITELY apply
                        record.proposed_author = consensus_author
                        record.author_source = f"{record.author_source}+series-consensus"
                        series_author_consensus_count += 1
                    else:
                        # Current author is DIFFERENT, not subset → DON'T apply (might be co-author)
                        continue
                
                # For low-quality sources
                elif record.author_source in ["metadata", "consensus", ""]:
                    # Note: "metadata_folder_confirmed" is intentionally excluded —
                    # it is already confirmed by folder and treated as authoritative.
                    if is_subset:
                        # Incomplete version → apply
                        original_source = record.author_source or ""
                        record.proposed_author = consensus_author
                        if original_source:
                            record.author_source = f"{original_source}+series-consensus"
                        else:
                            record.author_source = "series-consensus"
                        series_author_consensus_count += 1
                    elif author_counts.get(record.proposed_author, 0) == 1:
                        # Unique author in series (might be co-author) → protect
                        continue
                    else:
                        # Not unique, not subset → still different author, skip
                        continue
        
        self.logger.log(f"[PASS 4] Applied series author consensus to {series_author_consensus_count} records")
        
        # HIERARCHICAL SERIES UNIFICATION
        # For files of the same author with hierarchical series variants (e.g., "Серия" and "Серия. Подсерия"),
        # unify all to the shortest/base version if it appears most frequently
        # Example: "Старплекс" vs "Старплекс. Конец эры" → all use "Старплекс"
        print("[PASS 4] Applying hierarchical series unification...")
        hierarchical_unification_count = 0
        
        # Group by author
        author_groups = {}
        for record in records:
            author = record.proposed_author or "[unknown]"
            if author not in author_groups:
                author_groups[author] = []
            author_groups[author].append(record)
        
        for author, author_records in author_groups.items():
            # Group by base series (part before first ". ")
            base_series_groups = {}
            
            for record in author_records:
                if record.proposed_series:
                    # Extract base series (part before ". " if hierarchical)
                    series = record.proposed_series
                    if '. ' in series:
                        base = series.split('. ')[0]
                    else:
                        base = series
                    
                    if base not in base_series_groups:
                        base_series_groups[base] = []
                    base_series_groups[base].append((record, series))
            
            # For each base series with multiple variants
            for base, records_with_series in base_series_groups.items():
                series_variants = {}
                for record, series in records_with_series:
                    if series not in series_variants:
                        series_variants[series] = []
                    series_variants[series].append(record)
                
                # If this base has multiple variants (e.g., "Старплекс" and "Старплекс. Конец эры")
                if len(series_variants) > 1:
                    # Choose the shortest variant as the canonical one
                    canonical_series = min(series_variants.keys(), key=len)
                    
                    # Unify all variants to the canonical
                    for variant_series, variant_records in series_variants.items():
                        if variant_series != canonical_series:
                            for record in variant_records:
                                record.proposed_series = canonical_series
                                hierarchical_unification_count += 1
        
        self.logger.log(f"[PASS 4] Unified {hierarchical_unification_count} hierarchical series variants")
