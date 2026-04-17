"""
PASS 1: Read FB2 files and determine initial authors from folder hierarchy.
"""

import os
import sys
import threading
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import concurrent.futures
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import tqdm

try:
    from extraction_constants import FILE_EXTENSION_FOLDER_NAMES
    from fb2_sax_extractor import FB2SAXExtractor
except ImportError:
    from ..extraction_constants import FILE_EXTENSION_FOLDER_NAMES
    from ..fb2_sax_extractor import FB2SAXExtractor


def process_file_worker(fb2_file_path_str: str, work_dir_str: str,
                       author_folder_cache: Dict, folder_parse_limit: int,
                       settings_dict: Dict, use_cache: bool = True, use_sax_parser: bool = True) -> Optional[Tuple]:
    """
    Module-level worker function for multiprocessing.
    Must be serializable and import all needed dependencies.
    """
    try:
        from pathlib import Path
        from fb2_author_extractor import FB2AuthorExtractor
        from settings_manager import SettingsManager
        from metadata_cache import MetadataCache

        fb2_file = Path(fb2_file_path_str)
        work_dir = Path(work_dir_str)

        # Reconstruct extractor
        if use_sax_parser:
            extractor = FB2SAXExtractor()
        else:
            extractor = FB2AuthorExtractor()
        if hasattr(extractor, 'settings') and settings_dict:
            extractor.settings.settings = settings_dict

        # Try cache first
        cache = MetadataCache() if use_cache else None
        meta = None
        if cache:
            meta = cache.get_cached_metadata(fb2_file)

        if not meta:
            # Parse file
            meta = extractor._extract_all_metadata_at_once(fb2_file)
            # Cache the metadata
            if cache:
                cache.cache_metadata(fb2_file, meta)

        author, author_source = _get_author_for_file_worker(
            fb2_file, work_dir, author_folder_cache, folder_parse_limit)

        # Create record
        record = BookRecord(
            file_path=str(fb2_file.relative_to(work_dir)),
            file_title=meta['title'] or "[no title]",
            metadata_authors=meta['authors'] or "[unknown]",
            proposed_author=author or "",
            author_source=author_source or "",
            metadata_series=meta['series'] or "",
            series_number=meta.get('series_number', ''),
            proposed_series="",
            series_source="",
            metadata_genre=meta['genre'] or "",
            needs_filename_fallback=(author == ""),
        )

        return record.to_tuple()

    except Exception as e:
        print(f"[WORKER ERROR] {fb2_file_path_str}: {e}")
        return None


def _get_author_for_file_worker(fb2_file: Path, work_dir: Path,
                              author_folder_cache: Dict, folder_parse_limit: int) -> Tuple[str, str]:
    """Simplified author extraction for worker"""
    current_dir = fb2_file.parent
    parse_levels = 0
    last_hit = ""

    while parse_levels < folder_parse_limit:
        if current_dir == work_dir:
            break

        # Skip extension folders
        if current_dir.name.lower() in FILE_EXTENSION_FOLDER_NAMES:
            try:
                parent_dir = current_dir.parent
                if parent_dir == current_dir:
                    break
                current_dir = parent_dir
            except Exception:
                break
            continue

        if current_dir in author_folder_cache:
            author_name, confidence = author_folder_cache[current_dir]
            last_hit = author_name

        try:
            parent_dir = current_dir.parent
            if parent_dir == current_dir:
                break
            current_dir = parent_dir
            parse_levels += 1
        except Exception:
            break

    return (last_hit, "folder_dataset") if last_hit else ("", "")


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
    metadata_genre: str = ""    # Genres from <genre> tags (comma-separated)
    series_number: str = ""       # Sequence number within series (from <sequence number=.../>)
    extracted_series_candidate: str = ""  # Series found in filename (even if blocked by BL)
    needs_filename_fallback: bool = False  # True if folder parse found nothing, need filename PASS 2
    
    def to_tuple(self):
        """Convert record to tuple for GUI table display."""
        return (
            self.file_path,
            self.metadata_authors,
            self.proposed_author,
            self.author_source,
            self.metadata_series,
            self.proposed_series,
            self.series_source,
            self.file_title,
            self.metadata_genre,
            self.series_number,
        )

    @classmethod
    def from_tuple(cls, data):
        """Reconstruct from tuple for multiprocessing."""
        return cls(
            file_path=data[0],
            file_title=data[7],  # file_title is at index 7
            metadata_authors=data[1],
            proposed_author=data[2],
            author_source=data[3],
            metadata_series=data[4],
            proposed_series=data[5],
            series_source=data[6],
            metadata_genre=data[8],
            series_number=data[9],
            extracted_series_candidate="",  # defaults
            needs_filename_fallback=(data[2] == ""),  # based on proposed_author
        )


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

        Reads files in parallel (I/O-bound) using ThreadPoolExecutor.
        Each file is read exactly once via _extract_all_metadata_at_once().

        Returns:
            List of BookRecord objects
        """
        print("[PASS 1] Reading FB2 files...")

        fb2_files = sorted(self.work_dir.rglob('*.fb2'))
        total = len(fb2_files)
        if total == 0:
            self.logger.log("[PASS 1] No FB2 files found")
            return []

        print(f"[PASS 1] Found {total} files, processing in parallel...")

        # Serialize cache for workers
        author_folder_cache_serialized = {}
        for path, (author, conf) in self.author_folder_cache.items():
            author_folder_cache_serialized[str(path)] = (author, conf)

        settings_dict = getattr(self.extractor.settings, 'settings', {}) if hasattr(self.extractor, 'settings') else {}
        use_cache = settings_dict.get('performance', {}).get('enable_caching', True)
        use_sax_parser = settings_dict.get('performance', {}).get('use_sax_parser', True)

        # Use ProcessPoolExecutor for CPU-bound XML parsing
        max_workers = min(multiprocessing.cpu_count() or 4, max(1, total // 20))
        print(f"[PASS 1] Using {max_workers} processes for CPU-bound XML parsing...")
        if use_cache:
            print(f"[PASS 1] Metadata caching enabled")
        print(f"[PASS 1] Using {'SAX' if use_sax_parser else 'ElementTree'} parser")

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {}
            for fb2_file in fb2_files:
                future = executor.submit(
                    process_file_worker,
                    str(fb2_file),
                    str(self.work_dir),
                    author_folder_cache_serialized,
                    self.folder_parse_limit,
                    settings_dict,
                    use_cache,
                    use_sax_parser
                )
                future_to_file[future] = fb2_file

            # Process results with progress bar
            records = []
            with tqdm.tqdm(total=total, desc="Processing FB2 files", unit="file",
                           file=sys.stdout, dynamic_ncols=True) as pbar:
                for future in concurrent.futures.as_completed(future_to_file):
                    fb2_file = future_to_file[future]
                    try:
                        result_tuple = future.result()
                        if result_tuple:
                            record = BookRecord.from_tuple(result_tuple)
                            records.append(record)
                    except Exception as e:
                        self.logger.log(f"[PASS 1] Error processing {fb2_file}: {e}")

                    pbar.update(1)

        self.logger.log(f"[PASS 1] Read {len(records)} files")
        return records
    
    def _get_author_for_file(self, fb2_file: Path) -> Tuple[str, str]:
        """Determine author for a file using folder hierarchy cache.

        Walks UP from the file's folder toward work_dir (up to folder_parse_limit
        steps), collecting ALL cache hits. Returns the hit CLOSEST to work_dir
        (= last found), so a real author folder higher up takes precedence over a
        deeper pseudonym/series folder that also looks like a name.

        Example: "Волк Антон\Макс Лайт\file.fb2"
          - Макс Лайт → cache hit (HIGH)
          - Волк Антон → cache hit (LOW, closer to work_dir)  ← returned

        Returns:
            (author_name, source) where source = "folder_dataset" or ""
        """
        current_dir = fb2_file.parent
        parse_levels = 0
        last_hit: str = ""

        while parse_levels < self.folder_parse_limit:
            if current_dir == self.work_dir:
                break

            # Прозрачно пропускаем папки-расширения (не считаем уровень)
            if current_dir.name.lower() in FILE_EXTENSION_FOLDER_NAMES:
                try:
                    parent_dir = current_dir.parent
                    if parent_dir == current_dir:
                        break
                    current_dir = parent_dir
                except Exception:
                    break
                continue

            if current_dir in self.author_folder_cache:
                author_name, confidence = self.author_folder_cache[current_dir]
                last_hit = author_name  # keep going — higher folder wins

            try:
                parent_dir = current_dir.parent
                if parent_dir == current_dir:
                    break
                current_dir = parent_dir
                parse_levels += 1
            except Exception:
                break

        if last_hit:
            return last_hit, "folder_dataset"
        return "", ""
