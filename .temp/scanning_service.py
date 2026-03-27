"""
Standalone FB2 Library Scanning Service

This module provides a reusable scanning service for FB2 libraries.
Can be used independently in other projects.

Usage:
    from scanning_service import ScanningService
    
    service = ScanningService(parser)
    genres = service.scan_folder(
        folder_path="/path/to/library",
        progress_callback=lambda idx, total, filename: print(f"{idx}/{total}")
    )
"""

from pathlib import Path
import threading
from typing import Callable, Dict, List, Optional


class ScanningService:
    """
    Standalone service for scanning FB2 libraries.
    
    Scans a folder recursively for FB2 files, extracts genres,
    and groups files by genre combination.
    """
    
    def __init__(self, parser):
        """
        Initialize scanning service.
        
        Args:
            parser: FB2 parser instance with parse_genres(file_path) method
        """
        self.parser = parser
        self.genres: Dict[str, List[str]] = {}
        self.errors: List[str] = []
        self.file_order: List[str] = []
        self.file_to_genre: Dict[str, str] = {}
        self.is_scanning = False
        self._stop_requested = False

    def scan_folder(
        self, 
        folder_path: str, 
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> Dict[str, List[str]]:
        """
        Scan folder for FB2 files and extract genres.
        
        Args:
            folder_path: Path to folder to scan
            progress_callback: Optional callback function(idx, total, filename)
            
        Returns:
            Dictionary mapping genre combinations to list of file paths
            Example: {
                "Fiction, Science Fiction": ["/path/file1.fb2", "/path/file2.fb2"],
                "Not determined": ["/path/file3.fb2"]
            }
        """
        self._reset_state()
        self.is_scanning = True
        self._stop_requested = False
        
        try:
            files = list(Path(folder_path).rglob('*.fb2'))
            total = len(files)
            
            for idx, fb2_file in enumerate(files, 1):
                if self._stop_requested:
                    break
                
                try:
                    # Extract genres from file
                    genres = self.parser.parse_genres(fb2_file)
                    
                    # Filter empty genres
                    genres = [g for g in genres if g and g != "Не определено"]
                    if not genres:
                        genres = ["Не определено"]
                    
                    # Create genre key
                    key = ', '.join(genres)
                    self.genres.setdefault(key, []).append(str(fb2_file))
                    
                    # Record order and mapping
                    fp = str(fb2_file)
                    self.file_order.append(fp)
                    self.file_to_genre[fp] = key
                    
                except Exception as e:
                    self.errors.append(f"{fb2_file}: {str(e)}")
                
                # Call progress callback
                if progress_callback:
                    progress_callback(idx, total, str(fb2_file))
            
            return self.genres
            
        finally:
            self.is_scanning = False

    def scan_folder_async(
        self,
        folder_path: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        completion_callback: Optional[Callable[[Dict[str, List[str]]], None]] = None
    ) -> threading.Thread:
        """
        Scan folder asynchronously in background thread.
        
        Args:
            folder_path: Path to folder to scan
            progress_callback: Optional callback for progress updates
            completion_callback: Optional callback when scan completes
            
        Returns:
            Thread object (daemon thread, already started)
        """
        def _scan_thread():
            genres = self.scan_folder(folder_path, progress_callback)
            if completion_callback:
                completion_callback(genres)
        
        thread = threading.Thread(target=_scan_thread)
        thread.daemon = True
        thread.start()
        return thread

    def stop_scan(self) -> None:
        """Stop scanning if currently in progress."""
        self._stop_requested = True

    def get_results(self) -> Dict[str, List[str]]:
        """Get current scan results."""
        return self.genres.copy()

    def get_errors(self) -> List[str]:
        """Get list of errors that occurred during scan."""
        return self.errors.copy()

    def get_file_count(self) -> int:
        """Get total number of files found."""
        return sum(len(files) for files in self.genres.values())

    def get_genre_count(self) -> int:
        """Get number of unique genre combinations found."""
        return len(self.genres)

    def _reset_state(self) -> None:
        """Reset internal state."""
        self.genres.clear()
        self.errors.clear()
        self.file_order.clear()
        self.file_to_genre.clear()
        self._stop_requested = False
