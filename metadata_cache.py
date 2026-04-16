import sqlite3
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class MetadataCache:
    """SQLite-based cache for FB2 file metadata to avoid re-parsing unchanged files."""

    def __init__(self, cache_path: Path = Path("metadata_cache.db")):
        self.cache_path = cache_path
        self._init_db()

    def _init_db(self):
        """Initialize the cache database."""
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS file_metadata (
                    file_path TEXT PRIMARY KEY,
                    file_hash TEXT,
                    mtime REAL,
                    metadata TEXT,
                    cached_at REAL
                )
            ''')
            conn.commit()

    def get_cached_metadata(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """Get cached metadata if file hasn't changed."""
        try:
            stat = file_path.stat()
            current_mtime = stat.st_mtime

            with sqlite3.connect(self.cache_path) as conn:
                row = conn.execute(
                    "SELECT metadata, file_hash FROM file_metadata WHERE file_path = ? AND mtime = ?",
                    (str(file_path), current_mtime)
                ).fetchone()

                if row:
                    metadata_json, cached_hash = row
                    # Verify hash hasn't changed (extra safety)
                    if self._calculate_hash(file_path) == cached_hash:
                        meta = json.loads(metadata_json)
                        # Не возвращать запись где и авторы и заголовок пустые —
                        # это признак сбоя парсинга (битая кодировка и т.п.).
                        # Такой файл будет перечитан и результат перекэширован.
                        if not meta.get('authors') and not meta.get('title'):
                            return None
                        return meta
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def cache_metadata(self, file_path: Path, metadata: Dict[str, Any]):
        """Store metadata in cache."""
        try:
            stat = file_path.stat()
            file_hash = self._calculate_hash(file_path)

            with sqlite3.connect(self.cache_path) as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO file_metadata
                       (file_path, file_hash, mtime, metadata, cached_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (str(file_path), file_hash, stat.st_mtime,
                     json.dumps(metadata), datetime.now().timestamp())
                )
                conn.commit()
        except OSError:
            pass  # Silently fail if can't cache

    def _calculate_hash(self, file_path: Path) -> str:
        """Calculate file hash for verification."""
        hash_obj = hashlib.md5()
        try:
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except OSError:
            return ""

    def clear_cache(self):
        """Clear all cached metadata."""
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("DELETE FROM file_metadata")
            conn.commit()

    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with sqlite3.connect(self.cache_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM file_metadata").fetchone()[0]
            recent = conn.execute(
                "SELECT COUNT(*) FROM file_metadata WHERE cached_at > ?",
                (datetime.now().timestamp() - 86400,)  # Last 24 hours
            ).fetchone()[0]
            return {"total_cached": total, "recently_cached": recent}

    def cleanup_old_entries(self, max_age_days: int = 30):
        """Remove cache entries older than max_age_days."""
        cutoff = datetime.now().timestamp() - (max_age_days * 86400)
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("DELETE FROM file_metadata WHERE cached_at < ?", (cutoff,))
            conn.commit()