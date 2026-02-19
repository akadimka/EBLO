"""
PASS 4: Apply consensus author to files in same folder.
"""

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
    
    def __init__(self, logger):
        """Initialize PASS 4.
        
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
            # Separate determined and undetermined files
            # DETERMINED: files with ANY successful source (folder_dataset, metadata, consensus, filename)
            # UNDETERMINED: files with empty source only
            determined = [r for r in group_records 
                         if r.author_source in ["folder_dataset", "metadata", "consensus", "filename"]]
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
                    consensus_count += 1
        
        self.logger.log(f"[PASS 4] Applied consensus to {consensus_count} records")
