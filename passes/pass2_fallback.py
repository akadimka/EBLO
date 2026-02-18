"""
PASS 2 Fallback: Apply metadata as last resort for records without author.
"""

from typing import List


class Pass2Fallback:
    """PASS 2 Fallback: Use metadata as last resort for author assignment."""
    
    def __init__(self, logger):
        """Initialize PASS 2 Fallback.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 2 Fallback: Apply metadata for records without author.
        
        For records with empty proposed_author after PASS 1 and PASS 2,
        apply metadata_authors as the last resort.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 2 Fallback] Applying metadata as last resort...")
        
        fallback_count = 0
        
        for record in records:
            # Only for records without determined author
            if record.proposed_author:
                continue
            
            # Apply metadata
            if record.metadata_authors and record.metadata_authors != "[unknown]":
                record.proposed_author = record.metadata_authors
                record.author_source = "metadata"
                fallback_count += 1
            else:
                # Even metadata is empty
                record.proposed_author = ""
                record.author_source = ""
        
        self.logger.log(f"[PASS 2 Fallback] Applied metadata to {fallback_count} records")
