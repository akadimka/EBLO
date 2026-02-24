"""
PASS 3: Normalize author names to standard format.
"""

from typing import List, Optional
from author_normalizer_extended import AuthorNormalizer
from settings_manager import SettingsManager


class Pass3Normalize:
    """PASS 3: Normalize author names to standard format.
    
    Transform author names from various formats to standard "Фамилия Имя" format:
    - "Иван Петров" → "Петров Иван"
    - "А.Михайловский; А.Харников" → "Михайловский А., Харников А." (multi-author)
    """
    
    def __init__(self, logger):
        """Initialize PASS 3.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
        try:
            self.settings = SettingsManager('config.json')
        except:
            self.settings = None
        self.normalizer = AuthorNormalizer(self.settings)
    
    def execute(self, records: List) -> None:
        """Execute PASS 3: Normalize author names.
        
        Transform author format and handle multi-author cases.
        Handles both separators: '; ' (from folder parsing) and ', ' (from filename/metadata).
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 3] Normalizing author names...")
        
        normalized_count = 0
        
        for record in records:
            if not record.proposed_author or record.proposed_author == "Сборник":
                continue
            
            original = record.proposed_author
            
            # Check for multi-author cases with different separators
            # '; ' comes from folder_author_parser (temporary separator)
            # ', ' comes from filename or metadata
            # 
            # Metadata handling strategy:
            # - folder_dataset: never use metadata (folder extraction is authoritative)
            # - filename (multi-author): never use metadata (don't replace with list)
            # - filename (single-word): allow metadata (for expanding incomplete names)
            # - metadata source: always use metadata (for normalization/conversions)
            
            if record.author_source == "folder_dataset":
                metadata_for_normalization = ""
            elif record.author_source == "filename":
                # For filename: only use metadata if single incomplete name
                author_words = len(record.proposed_author.strip().split())
                has_separator = ', ' in record.proposed_author or '; ' in record.proposed_author
                
                # Use metadata only for single-word names (incomplete) without separators
                if author_words == 1 and not has_separator:
                    metadata_for_normalization = record.metadata_authors
                else:
                    metadata_for_normalization = ""
            else:
                metadata_for_normalization = record.metadata_authors
            
            if '; ' in record.proposed_author or ', ' in record.proposed_author:
                # Determine separator
                sep = '; ' if '; ' in record.proposed_author else ', '
                normalized = self.normalizer.normalize_format(original, metadata_for_normalization)
            else:
                # Single author
                normalized = self.normalizer.normalize_format(original, metadata_for_normalization)
            
            if normalized and normalized != original:
                record.proposed_author = normalized
                normalized_count += 1
        
        self.logger.log(f"[PASS 3] Normalized {normalized_count} author names")
