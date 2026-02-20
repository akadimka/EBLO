"""
PRECACHE Phase: Build author folder hierarchy before PASS 1.
"""

from pathlib import Path
from typing import Dict, Tuple, Optional, Set
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
        self.male_names: Set[str] = set()
        self.female_names: Set[str] = set()
        self._load_name_sets()
    
    def _load_name_sets(self) -> None:
        """Load male and female name lists from config (convert to lowercase for consistent validation)."""
        try:
            # Load names and convert to lowercase for case-insensitive validation
            self.male_names = set(name.lower() for name in self.settings.get_male_names())
            self.female_names = set(name.lower() for name in self.settings.get_female_names())
            print(f"[PRECACHE] Loaded {len(self.male_names)} male names, "
                  f"{len(self.female_names)} female names for validation")
        except Exception as e:
            self.logger.log(f"[PRECACHE] Failed to load name sets: {e}")
            print(f"[PRECACHE] WARNING: Failed to load name sets: {e}")
    
    def _contains_valid_name(self, author_name: str) -> bool:
        """Check if author_name contains at least one valid person name.
        
        Args:
            author_name: Author name to validate (e.g., "Олег Сапфир")
            
        Returns:
            True if at least one word is found in male_names or female_names
        """
        if not author_name:
            return False
        
        # Split author name into words
        words = author_name.split()
        
        # Check if any word is in our name sets
        for word in words:
            word_clean = word.strip('.,;:!?')  # Remove punctuation
            if word_clean in self.male_names or word_clean in self.female_names:
                return True
        
        return False
    
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
            
            # If author folder with FB2 files AND name parses as author AND contains valid names
            if author_name and has_fb2_files and self._contains_valid_name(author_name):
                if depth > 0:
                    result = (author_name, "high")
                    self.author_folder_cache[folder] = result
                    print(f"[CACHE] Added HIGH: {folder.name} → '{author_name}'")
                return result
            
            # If name parses as author but fails validation → skip caching
            # This prevents series folder names from blocking parent author inheritance
            elif author_name and has_fb2_files and not self._contains_valid_name(author_name):
                if depth > 0:
                    print(f"[CACHE] Skipped (no valid names): {folder.name} → '{author_name}'")
                # Don't cache, allow parent inheritance to work
                # Continue to subfolder scanning without caching this folder
            
            # If folder is not author but name parses → cache for inheritance (no FB2 files)
            elif author_name and depth > 0:
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
