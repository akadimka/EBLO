"""
PRECACHE Phase: Build author folder hierarchy before PASS 1.
"""

from pathlib import Path
from typing import Dict, Tuple, Optional
from passes.folder_author_parser import parse_author_from_folder_name


class Precache:
    """PRECACHE: Recursively scan folder hierarchy and cache author folders."""
    
    def __init__(self, work_dir: Path, settings, logger, folder_parse_limit: int):
        """Initialize PRECACHE.
        
        Args:
            work_dir: Working directory to scan
            settings: SettingsManager instance
            logger: Logger instance
            folder_parse_limit: Maximum depth for folder parsing
        """
        self.work_dir = work_dir
        self.settings = settings
        self.logger = logger
        self.folder_parse_limit = folder_parse_limit
        self.author_folder_cache: Dict[Path, Tuple[str, str]] = {}
    
    def execute(self) -> Dict[Path, Tuple[str, str]]:
        """Execute PRECACHE: Build author folder cache.
        
        Returns:
            Dictionary {folder_path: (author_name, confidence)}
        """
        print("[PRECACHE] Building author folder hierarchy...")
        
        conversions = self.settings.get_author_surname_conversions()
        
        def scan_folder_hierarchy(folder: Path, depth: int = 0) -> Optional[Tuple[str, str]]:
            """Recursively scan folders and cache authors."""
            
            # Never process work_dir itself
            if folder == self.work_dir:
                try:
                    for subdir in folder.iterdir():
                        if subdir.is_dir() and not subdir.name.startswith('.'):
                            scan_folder_hierarchy(subdir, depth + 1)
                except (PermissionError, OSError):
                    pass
                return None
            
            if depth > self.folder_parse_limit:
                return None
            
            folder_name = folder.name
            if not folder_name or folder_name.startswith('.'):
                return None
            
            # Check cache
            if folder in self.author_folder_cache:
                return self.author_folder_cache[folder]
            
            # Apply conversions to folder name
            folder_name_to_parse = conversions.get(folder_name, folder_name)
            
            # Apply PASS0+PASS1+PASS2 structural analysis
            author_name = parse_author_from_folder_name(folder_name_to_parse)
            
            # Check if folder contains FB2 files
            has_fb2_files = False
            try:
                for item in folder.iterdir():
                    if item.is_file() and item.suffix.lower() == '.fb2':
                        has_fb2_files = True
                        break
            except (PermissionError, OSError):
                pass
            
            # If author folder with FB2 files AND name parses as author
            if author_name and has_fb2_files:
                if depth > 0:
                    result = (author_name, "high")
                    self.author_folder_cache[folder] = result
                    print(f"[CACHE] Added HIGH: {folder.name} → '{author_name}'")
                return result
            
            # If folder is not author but name parses → cache for inheritance
            if author_name and depth > 0:
                result = (author_name, "low")
                self.author_folder_cache[folder] = result
            
            # Recursively scan subfolders
            try:
                for subdir in folder.iterdir():
                    if subdir.is_dir() and not subdir.name.startswith('.'):
                        scan_folder_hierarchy(subdir, depth + 1)
            except (PermissionError, OSError):
                pass
            
            return None
        
        # Start scanning
        try:
            scan_folder_hierarchy(self.work_dir, depth=0)
            print(f"[PRECACHE] Cached {len(self.author_folder_cache)} author folders\n")
            self.logger.log(f"[PRECACHE] Cached {len(self.author_folder_cache)} author folders")
        except Exception as e:
            self.logger.log(f"[PRECACHE] Error: {e}")
        
        return self.author_folder_cache
