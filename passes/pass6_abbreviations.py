"""
PASS 6: Expand author abbreviations to full names.
"""

from typing import List, Dict


class Pass6Abbreviations:
    """PASS 6: Expand author abbreviations to full names."""
    
    def __init__(self, logger):
        """Initialize PASS 6.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 6: Expand abbreviations.
        
        Transform "А.Фамилия" → "Александр Фамилия" using full author names dict.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 6] Expanding abbreviations...")
        
        # Build dictionary of full names
        authors_map = {}
        for record in records:
            if record.proposed_author and '.' not in record.proposed_author:
                parts = record.proposed_author.split()
                if parts:
                    surname = parts[0].lower()
                    if surname not in authors_map:
                        authors_map[surname] = []
                    if record.proposed_author not in authors_map[surname]:
                        authors_map[surname].append(record.proposed_author)
        
        # Expand abbreviations
        expanded_count = 0
        
        for record in records:
            if not record.proposed_author or '.' not in record.proposed_author:
                continue
            
            # Simple pattern: "Фамилия И."
            parts = record.proposed_author.split()
            if len(parts) == 2 and '.' in parts[1]:
                surname = parts[0].lower()
                if surname in authors_map:
                    # Use first found full name
                    record.proposed_author = authors_map[surname][0]
                    expanded_count += 1
        
        self.logger.log(f"[PASS 6] Expanded {expanded_count} abbreviations")
