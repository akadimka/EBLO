"""
PASS 1: Read FB2 files and determine initial authors from folder hierarchy.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional


@dataclass
class BookRecord:
    """Book record with progressive filling through PASS stages."""
    file_path: str              # Path to FB2 file (relative to work_dir)
    file_title: str             # Book title from title-info
    metadata_authors: str       # Original authors from FB2 XML (immutable)
    proposed_author: str        # Proposed author (evolves through PASS)
    author_source: str          # Source: "folder_dataset", "filename", "metadata", "consensus", ""
    metadata_series: str        # Original series from FB2 XML (immutable)
    proposed_series: str        # Final series after all PASS
    series_source: str          # Source of series


class Pass1ReadFiles:
    """PASS 1: Read FB2 files and extract initial metadata."""
    
    def __init__(self, work_dir: Path, author_folder_cache: Dict[Path, Tuple[str, str]], 
                 extractor, logger, folder_parse_limit: int):
        """Initialize PASS 1.
        
        Args:
            work_dir: Working directory with FB2 files
            author_folder_cache: Cached author folders from PRECACHE
            extractor: FB2AuthorExtractor instance
            logger: Logger instance
            folder_parse_limit: Maximum depth for folder parsing
        """
        self.work_dir = work_dir
        self.author_folder_cache = author_folder_cache
        self.extractor = extractor
        self.logger = logger
        self.folder_parse_limit = folder_parse_limit
    
    def execute(self) -> List[BookRecord]:
        """Execute PASS 1: Read FB2 files and create BookRecords.
        
        Returns:
            List of BookRecord objects
        """
        print("[PASS 1] Reading FB2 files...")
        
        records = []
        fb2_count = 0
        
        for fb2_file in self.work_dir.rglob('*.fb2'):
            try:
                fb2_count += 1
                
                # Show progress
                if fb2_count <= 5 or fb2_count % 50 == 0:
                    rel_path = fb2_file.relative_to(self.work_dir)
                    print(f"  [{fb2_count:4d}] {rel_path}")
                
                # Extract metadata
                title = self.extractor._extract_title_from_fb2(fb2_file)
                metadata_authors = self.extractor._extract_all_authors_from_metadata(fb2_file)
                
                # Determine author from folder hierarchy cache
                author, author_source = self._get_author_for_file(fb2_file)
                
                # Relative path
                rel_path = str(fb2_file.relative_to(self.work_dir))
                
                # Create BookRecord
                record = BookRecord(
                    file_path=rel_path,
                    file_title=title or "[no title]",
                    metadata_authors=metadata_authors or "[unknown]",
                    proposed_author=author or "",
                    author_source=author_source or "",
                    metadata_series="",
                    proposed_series="",
                    series_source=""
                )
                
                records.append(record)
                
                if fb2_count % 100 == 0:
                    self.logger.log(f"[PASS 1] Processed {fb2_count} files...")
                    
            except Exception as e:
                self.logger.log(f"[PASS 1] Error reading {fb2_file}: {e}")
        
        self.logger.log(f"[PASS 1] Read {len(records)} files")
        return records
    
    def _get_author_for_file(self, fb2_file: Path) -> Tuple[str, str]:
        """Determine author for a file using folder hierarchy cache.
        
        Starting from file's folder, walk up the hierarchy searching in
        author_folder_cache. Return first match or empty string.
        
        Returns:
            (author_name, source) where source = "folder_dataset" or ""
        """
        current_dir = fb2_file.parent
        parse_levels = 0
        
        while parse_levels < self.folder_parse_limit:
            if current_dir == self.work_dir:
                break
            
            # Check cache
            if current_dir in self.author_folder_cache:
                author_name, confidence = self.author_folder_cache[current_dir]
                return author_name, "folder_dataset"
            
            # Move up
            try:
                parent_dir = current_dir.parent
                if parent_dir == current_dir:
                    break
                current_dir = parent_dir
                parse_levels += 1
            except Exception:
                break
        
        return "", ""
