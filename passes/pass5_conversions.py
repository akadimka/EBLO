"""
PASS 5: Re-apply author surname conversions.
"""

from typing import List


class Pass5Conversions:
    """PASS 5: Re-apply author surname conversions after consensus."""
    
    def __init__(self, settings, logger):
        """Initialize PASS 5.
        
        Args:
            settings: SettingsManager instance
            logger: Logger instance
        """
        self.settings = settings
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 5: Re-apply surname conversions.
        
        Apply author_surname_conversions a second time after consensus.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 5] Re-applying conversions...")
        
        conversions = self.settings.get_author_surname_conversions()
        conversions_count = 0
        
        for record in records:
            if not record.proposed_author or record.proposed_author == "Сборник":
                continue
            
            original = record.proposed_author
            
            # Apply conversions
            for old_name, new_name in conversions.items():
                if old_name in original:
                    record.proposed_author = original.replace(old_name, new_name)
                    original = record.proposed_author
                    conversions_count += 1
        
        self.logger.log(f"[PASS 5] Applied conversions to {conversions_count} records")
