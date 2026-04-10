"""
PASS 1: Read FB2 files and determine initial authors from folder hierarchy.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional

try:
    from extraction_constants import FILE_EXTENSION_FOLDER_NAMES
except ImportError:
    from ..extraction_constants import FILE_EXTENSION_FOLDER_NAMES


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

        lock = threading.Lock()
        processed_count = [0]

        def process_file(fb2_file: Path):
            try:
                meta = self.extractor._extract_all_metadata_at_once(fb2_file)
                author, author_source = self._get_author_for_file(fb2_file)

                # ВАЛИДАЦИЯ FOLDER_DATASET: если автор из кэша папок не подтверждён
                # метаданными файла (ни одно слово не пересекается), это скорее всего
                # ярлык серии/издательства (например «Питер» из «Мировой криминальный
                # бестселлер (Питер)»), а не реальный автор. Сбрасываем — pass2 доберёт
                # автора из имени файла или метаданных.
                if author_source == "folder_dataset" and author and meta.get('authors'):
                    import re as _re_p1
                    author_words = set(author.lower().split())
                    meta_words = set(_re_p1.sub(r'[;,]', ' ', meta['authors'].lower()).split())
                    if author_words and meta_words and not (author_words & meta_words):
                        author = ""
                        author_source = ""

                rel_path = str(fb2_file.relative_to(self.work_dir))

                record = BookRecord(
                    file_path=rel_path,
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

                with lock:
                    processed_count[0] += 1
                    count = processed_count[0]
                if count <= 5 or count % 50 == 0:
                    print(f"  [{count:4d}/{total}] {rel_path}")
                if count % 100 == 0:
                    self.logger.log(f"[PASS 1] Processed {count}/{total} files...")

                return record
            except Exception as e:
                self.logger.log(f"[PASS 1] Error reading {fb2_file}: {e}")
                return None

        max_workers = min(8, total, os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(process_file, fb2_files))

        records = [r for r in results if r is not None]
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
