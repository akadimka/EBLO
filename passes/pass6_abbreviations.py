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
    
    def __init__(self, logger):
        """Initialize PASS 6.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
        self.py_logger = logger  # Reference to system logger
        try:
            self.settings = SettingsManager('config.json')
        except:
            self.settings = None
        self.normalizer = AuthorNormalizer(self.settings)
    
    def execute(self, records: List) -> None:
        """Execute PASS 6: Expand abbreviations.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 6] Expanding abbreviations...")
        
        # Build authors map from all records
        authors_map = self._build_authors_map(records)
        
        # Expand abbreviations
        expanded_count = 0
        
        for record in records:
            if record.proposed_author == "Сборник" or "." not in record.proposed_author:
                continue
            
            original = record.proposed_author
            
            # Check for multi-author case with both separators ('; ' from folder, ', ' from filename)
            if '; ' in record.proposed_author:
                authors = record.proposed_author.split('; ')
                expanded_authors = [self.normalizer.expand_abbreviation(a, authors_map) for a in authors]
                record.proposed_author = '; '.join(expanded_authors)
            elif ', ' in record.proposed_author:
                authors = record.proposed_author.split(', ')
                expanded_authors = [self.normalizer.expand_abbreviation(a, authors_map) for a in authors]
                record.proposed_author = ', '.join(expanded_authors)
            else:
                record.proposed_author = self.normalizer.expand_abbreviation(original, authors_map)
            
            if record.proposed_author != original:
                expanded_count += 1
        
        self.logger.log(f"[PASS 6] Expanded {expanded_count} abbreviations")
    
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
        seen = set()  # For deduplication
        
        # Collect from proposed_author (already processed)
        for record in records:
            if record.proposed_author and record.proposed_author != "Сборник":
                author = record.proposed_author
                
                # Handle multi-author case
                if ', ' in author:
                    for single_author in author.split(', '):
                        single_author = single_author.strip()
                        if single_author and '.' not in single_author:
                            key = single_author.split()[0].lower()  # First word = surname
                            if key and single_author not in seen:
                                if key not in authors_map:
                                    authors_map[key] = []
                                authors_map[key].append(single_author)
                                seen.add(single_author)
                else:
                    # Single author
                    if '.' not in author:
                        key = author.split()[0].lower()  # First word = surname
                        if key and author not in seen:
                            if key not in authors_map:
                                authors_map[key] = []
                            authors_map[key].append(author)
                            seen.add(author)
            
            # Collect from metadata_authors (original source - best for abbreviation expansion)
            if record.metadata_authors and record.metadata_authors != "Сборник":
                author = record.metadata_authors
                
                # Handle multi-author case (could use , or ;)
                sep = ', ' if ', ' in author else ('; ' if '; ' in author else None)
                if sep:
                    for single_author in author.split(sep):
                        single_author = single_author.strip()
                        if single_author:
                            normalized = self.normalizer.normalize_format(single_author)
                            key = normalized.split()[0].lower()  # First word = surname
                            if key and normalized not in seen:
                                if key not in authors_map:
                                    authors_map[key] = []
                                authors_map[key].append(normalized)
                                seen.add(normalized)
                else:
                    # Single author
                    normalized = self.normalizer.normalize_format(author)
                    key = normalized.split()[0].lower()  # First word = surname
                    if key and normalized not in seen:
                        if key not in authors_map:
                            authors_map[key] = []
                        authors_map[key].append(normalized)
                        seen.add(normalized)
        
        return authors_map
