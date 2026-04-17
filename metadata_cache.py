import sqlite3
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


# Файлы парсера, от которых зависит качество извлечения метаданных.
# При изменении любого из них весь кэш автоматически сбрасывается.
_PARSER_SOURCE_FILES = [
    'fb2_sax_extractor.py',
    'fb2_author_extractor.py',
    'passes/pass1_read_files.py',
]


def _compute_parser_version() -> str:
    """Вычислить хэш исходников парсера.

    Если код парсера изменился — хэш изменится → кэш будет сброшен
    при следующем запуске пайплайна.
    """
    h = hashlib.md5()
    base = Path(__file__).parent
    for rel in _PARSER_SOURCE_FILES:
        p = base / rel
        try:
            h.update(p.read_bytes())
        except OSError:
            h.update(rel.encode())
    return h.hexdigest()


class MetadataCache:
    """SQLite-based cache for FB2 file metadata to avoid re-parsing unchanged files.

    Автоматически сбрасывается при изменении исходников парсера —
    таким образом фиксы в логике всегда отражаются в результатах
    следующего запуска пайплайна без ручного вмешательства.
    """

    def __init__(self, cache_path: Path = Path("metadata_cache.db")):
        self.cache_path = cache_path
        self._parser_version = _compute_parser_version()
        self._init_db()
        self._check_parser_version()

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
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cache_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            conn.commit()

    def _check_parser_version(self):
        """Сбросить кэш если исходники парсера изменились."""
        with sqlite3.connect(self.cache_path) as conn:
            row = conn.execute(
                "SELECT value FROM cache_meta WHERE key = 'parser_version'"
            ).fetchone()
            stored_version = row[0] if row else None

            if stored_version != self._parser_version:
                conn.execute("DELETE FROM file_metadata")
                conn.execute(
                    "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('parser_version', ?)",
                    (self._parser_version,)
                )
                conn.commit()
                if stored_version is not None:
                    # Не первый запуск — сообщаем о сбросе
                    print(f"[CACHE] Парсер обновлён — кэш метаданных сброшен")

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
                    if self._calculate_hash(file_path) == cached_hash:
                        return json.loads(metadata_json)
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
            pass

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
                (datetime.now().timestamp() - 86400,)
            ).fetchone()[0]
            return {"total_cached": total, "recently_cached": recent}

    def cleanup_old_entries(self, max_age_days: int = 30):
        """Remove cache entries older than max_age_days."""
        cutoff = datetime.now().timestamp() - (max_age_days * 86400)
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("DELETE FROM file_metadata WHERE cached_at < ?", (cutoff,))
            conn.commit()
