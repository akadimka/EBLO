"""
PASS 3: Normalize author names to standard format.
"""

from typing import List


class Pass3Normalize:
    """PASS 3: Normalize author names to standard format."""
    
    def __init__(self, extractor, logger):
        """Initialize PASS 3.
        
        Args:
            extractor: FB2AuthorExtractor instance
            logger: Logger instance
        """
        self.extractor = extractor
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 3: Normalize author names.
        
        Apply extractor._normalize_author_format() to each author.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 3] Normalizing author names...")
        
        normalized_count = 0
        
        for record in records:
            if not record.proposed_author or record.proposed_author == "Сборник":
                continue
            
            original = record.proposed_author
            normalized = self.extractor._normalize_author_format(original)
            
            if normalized and normalized != original:
                record.proposed_author = normalized
                normalized_count += 1
        
        self.logger.log(f"[PASS 3] Normalized {normalized_count} author names")
