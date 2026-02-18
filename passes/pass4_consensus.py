"""
PASS 4: Apply consensus author to files in same folder.
"""

from pathlib import Path
from typing import List, Dict


class Pass4Consensus:
    """PASS 4: Apply consensus author to files in same folder."""
    
    def __init__(self, logger):
        """Initialize PASS 4.
        
        Args:
            logger: Logger instance
        """
        self.logger = logger
    
    def execute(self, records: List) -> None:
        """Execute PASS 4: Apply consensus author.
        
        Group records by folder and apply consensus author to undetermined files.
        Protected files (folder_dataset, metadata) are not overwritten.
        
        Args:
            records: List of BookRecord objects to process
        """
        print("[PASS 4] Applying consensus...")
        
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
            # Filter protected files (folder_dataset, metadata)
            undetermined = [r for r in group_records 
                          if r.author_source in ["", "filename"]]
            
            if len(undetermined) < 2:
                continue
            
            # Find consensus author
            author_counts = {}
            for record in undetermined:
                if record.proposed_author:
                    author_counts[record.proposed_author] = \
                        author_counts.get(record.proposed_author, 0) + 1
            
            if not author_counts:
                continue
            
            consensus_author = max(author_counts, key=author_counts.get)
            
            # Apply to all undetermined files
            for record in undetermined:
                if not record.proposed_author:
                    record.proposed_author = consensus_author
                    record.author_source = "consensus"
                    consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied consensus to {consensus_count} records")
