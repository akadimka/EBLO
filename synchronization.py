#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Synchronization Service - Move and organize FB2 files into library structure.

Handles:
- CSV generation from last_scan_path
- Duplicate detection (author + series + title)
- Folder structure creation (genre/author/series/)
- File movement to library_path
- Database recording
- Empty folder cleanup
- Progress reporting and statistics
"""

import os
import re
import sqlite3
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Callable
from collections import defaultdict

try:
    from settings_manager import SettingsManager
    from logger import Logger
    from regen_csv import RegenCSVService
except ImportError:
    from .settings_manager import SettingsManager
    from .logger import Logger
    from .regen_csv import RegenCSVService


class SynchronizationService:
    """Service for synchronizing FB2 library into organized structure."""
    
    def __init__(self, config_path: str = 'config.json'):
        """Initialize the service.
        
        Args:
            config_path: Path to config.json
        """
        self.config_path = Path(config_path)
        self.settings = SettingsManager(config_path)
        self.logger = Logger()
        self.csv_service = RegenCSVService(config_path)
        
        # Get paths from config
        self.library_path = Path(self.settings.get_library_path())
        self.last_scan_path = Path(self.settings.get_last_scan_path())
        
        # Database is in project root, not in library
        self.db_path = Path(__file__).parent / '.library_cache.db'
        
        # Log callback for UI integration
        self.log_callback = None
        
        # Statistics tracking
        self.stats = {
            'files_moved': 0,
            'duplicates_found': 0,
            'duplicates_deleted': 0,
            'folders_deleted': 0,
            'errors': 0,
            'total_files': 0,
            'start_time': None,
            'end_time': None,
        }
    
    def _log(self, msg: str):
        """Log message using callback or logger.
        
        Args:
            msg: Message to log
        """
        if self.log_callback:
            self.log_callback(msg)
        else:
            self.logger.log(msg)
        
    def sync_database_with_library(self, log_callback: Optional[Callable] = None, 
                                   progress_callback: Optional[Callable] = None) -> Dict:
        """Synchronize database with actual library structure.
        
        Removes entries for files that physically no longer exist in the library.
        Call this at application startup to clean up orphaned database records.
        
        Args:
            log_callback: Function(message_str) for logging messages to UI
            progress_callback: Function(current, total, status_str) for progress updates
            
        Returns:
            Dictionary with statistics {'deleted': count, 'checked': count}
        """
        self.log_callback = log_callback
        
        self._log("=" * 60)
        self._log("СИНХРОНИЗАЦИЯ БД С БИБЛИОТЕКОЙ (удаление orphaned записей)")
        self._log("=" * 60)
        
        stats = {'deleted': 0, 'checked': 0, 'errors': 0}
        
        try:
            if not self.db_path.exists():
                self._log(f"БД не найдена: {self.db_path} - синхронизация не требуется")
                return stats
            
            if not self.library_path.exists():
                self._log(f"Папка библиотеки не найдена: {self.library_path}")
                return stats
            
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Read all book entries
            cursor.execute("SELECT id, file_path, author, series, title FROM books")
            rows = cursor.fetchall()
            
            total_rows = len(rows)
            self._log(f"Проверка {total_rows} записей в БД...")
            
            if progress_callback:
                progress_callback(0, total_rows, "Проверка БД...")
            
            deleted_ids = []
            
            for i, row in enumerate(rows):
                record_id, file_path, author, series, title = row
                stats['checked'] += 1
                
                # Progress update
                if progress_callback and i % max(1, total_rows // 10) == 0:
                    progress_callback(i, total_rows, f"Проверка записей БД ({i}/{total_rows})")
                
                # Check if file physically exists
                full_path = self.library_path / file_path
                
                if not full_path.exists():
                    deleted_ids.append(record_id)
                    stats['deleted'] += 1
            
            # Delete orphaned records
            if deleted_ids:
                placeholders = ','.join(['?' for _ in deleted_ids])
                cursor.execute(f"DELETE FROM books WHERE id IN ({placeholders})", deleted_ids)
                
                if progress_callback:
                    progress_callback(len(deleted_ids), len(deleted_ids), 
                                    f"Удаление orphaned записей...")
                
                self._log(f"Удалено orphaned записей: {len(deleted_ids)}")
                conn.commit()
            
            conn.close()
            
            self._log(f"Синхронизация БД завершена: "
                     f"проверено {stats['checked']}, удалено {stats['deleted']}")
            self._log("=" * 60)
            
            if progress_callback:
                progress_callback(100, 100, "БД синхронизирована")
            
        except Exception as e:
            self._log(f"ОШИБКА при синхронизации БД: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
            stats['errors'] += 1
        
        return stats
    
    def synchronize(self, progress_callback: Optional[Callable] = None, log_callback: Optional[Callable] = None) -> Dict:
        """Execute full synchronization process.
        
        Args:
            progress_callback: Function(current, total, status_str) for progress updates
            log_callback: Function(message_str) for logging messages to UI
            
        Returns:
            Dictionary with statistics
        """
        self.stats['start_time'] = datetime.now()
        self.log_callback = log_callback  # Store for use in other methods
        
        self._log("=" * 60)
        self._log("НАЧАЛО СИНХРОНИЗАЦИИ")
        self._log("=" * 60)
        self._log(f"Library path: {self.library_path}")
        self._log(f"Last scan path: {self.last_scan_path}")
        self._log(f"DB path: {self.db_path}")
        
        try:
            # Step 0: Cleanup orphaned database entries
            if progress_callback:
                progress_callback(1, 100, "Очистка БД от orphaned записей")
            
            self._log("Шаг 0: Очистка БД от orphaned записей")
            
            def db_cleanup_progress(current, total, status):
                """Progress callback for DB cleanup."""
                if progress_callback:
                    progress_callback(1 + (current / max(total, 1) * 3), 100, status)
            
            db_cleanup = self.sync_database_with_library(
                log_callback=log_callback,
                progress_callback=db_cleanup_progress
            )
            self._log(f"  Удалено orphaned записей: {db_cleanup['deleted']}")
            
            # Step 1: Generate CSV
            if progress_callback:
                progress_callback(5, 100, "Генерация CSV из исходной папки")
            
            records = self._generate_csv_data(progress_callback)
            self.stats['total_files'] = len(records)
            
            if not records:
                if progress_callback:
                    progress_callback(10, 100, "Нет файлов для обработки")
                self._log("Синхронизация: нет файлов в исходной папке")
                return self.stats
            
            # Step 2: Build folder structure and detect duplicates
            if progress_callback:
                progress_callback(15, 100, "Анализ дубликатов")
            
            folder_structure = self._build_folder_structure(records, progress_callback)
            
            # Step 3: Move files and track successfully moved
            if progress_callback:
                progress_callback(50, 100, "Перемещение файлов в библиотеку")
            
            moved_records = self._move_files(records, folder_structure, progress_callback)
            
            self._log(f"Всего перемещено: {len(moved_records)} файлов")
            self._log(f"Готово к внесению в БД: {len(moved_records)} записей")
            
            # Step 4: Update database with moved files
            if progress_callback:
                progress_callback(80, 100, "Обновление базы данных")
            
            self._update_database(moved_records, progress_callback)
            
            # Step 5: Cleanup empty folders
            if progress_callback:
                progress_callback(90, 100, "Очистка пустых папок")
            
            self._cleanup_empty_folders()
            
            if progress_callback:
                progress_callback(100, 100, "Синхронизация завершена")
            
            self.stats['end_time'] = datetime.now()
            
            # Log summary statistics
            self._log("")
            self._log("=" * 60)
            self._log("ИТОГОВАЯ СТАТИСТИКА:")
            self._log(f"  Файлов перемещено: {self.stats['files_moved']}")
            self._log(f"  Дубликатов найдено и удалено: {self.stats['duplicates_found']}")
            self._log(f"  Папок удалено: {self.stats['folders_deleted']}")
            self._log(f"  Ошибок: {self.stats['errors']}")
            self._log("=" * 60)
            
            return self.stats
            
        except Exception as e:
            self._log(f"ОШИБКА при синхронизации: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
            self.stats['errors'] += 1
            self.stats['end_time'] = datetime.now()
            self._log("=" * 60)
            raise
    
    def _generate_csv_data(self, progress_callback: Optional[Callable] = None) -> List:
        """Generate CSV data from last_scan_path without saving to file.
        
        Args:
            progress_callback: Function(current, total, status_str) for progress
            
        Returns:
            List of BookRecord objects
        """
        self._log(f"Генерация CSV из: {self.last_scan_path}")
        self._log(f"Путь существует: {self.last_scan_path.exists()}")
        
        try:
            records = self.csv_service.generate_csv(
                str(self.last_scan_path),
                output_csv_path=None,  # Don't save CSV file
                progress_callback=progress_callback
            )
            
            self._log(f"CSV сгенерирован: {len(records)} записей")
            for i, record in enumerate(records[:5]):  # Log first 5 records
                self._log(f"  [{i+1}] {record.proposed_author} | {record.file_title}")
            if len(records) > 5:
                self._log(f"  ... и ещё {len(records) - 5} записей")
            
            return records
            
        except Exception as e:
            self._log(f"Ошибка при генерации CSV: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
            raise
    
    def _build_folder_structure(
        self,
        records: List,
        progress_callback: Optional[Callable] = None
    ) -> Dict:
        """Build folder structure and detect duplicates.
        
        Args:
            records: List of BookRecord objects
            progress_callback: Progress callback function
            
        Returns:
            Dictionary mapping file_path -> (genre, author, series, subseries)
        """
        self._log("Построение структуры папок")
        
        folder_structure = {}
        duplicates = defaultdict(list)
        
        # Check database for existing entries
        existing_entries = self._get_existing_entries()
        self._log(f"Существующих записей в БД: {len(existing_entries)}")
        
        # Debug: Log first few existing entries
        if existing_entries:
            entries_list = list(existing_entries)[:5]
            for entry in entries_list:
                self._log(f"  БД содержит: {entry[0]} | {entry[1]} | {entry[2]}")
            if len(existing_entries) > 5:
                self._log(f"  ... и ещё {len(existing_entries) - 5} записей")
        else:
            self._log("  (БД пуста или очищена)")
        
        new_files_count = 0
        duplicate_files_count = 0
        
        for i, record in enumerate(records):
            # Progress update
            if progress_callback and i % 10 == 0:
                progress_callback(15 + (i / len(records) * 35), 100, 
                                f"Анализ файла {i+1}/{len(records)}")
            
            # Extract metadata
            genre = record.metadata_genre or "Без жанра"
            author = record.proposed_author or "Неизвестный автор"
            series = record.proposed_series or ""
            title = record.file_title or Path(record.file_path).stem
            
            # Handle genre with multiple entries
            genres = [g.strip() for g in genre.split(',') if g.strip()]
            primary_genre = genres[0] if genres else "Без жанра"
            
            # Detect duplicates
            dup_key = (author, series, title)
            in_db = dup_key in existing_entries
            
            if in_db:
                self._log(f"  [{i+1}] ДУБЛИКАТ: {author} | {series} | {title}")
                self._log(f"       Файл: {record.file_path}")
                duplicates[dup_key].append(record.file_path)
                self.stats['duplicates_found'] += 1
                duplicate_files_count += 1
                
                # Удаляем дубликат из файловой системы
                try:
                    file_to_delete = self.last_scan_path / record.file_path
                    if file_to_delete.exists():
                        os.unlink(str(file_to_delete))
                        self._log(f"       ✓ Удален")
                    else:
                        self._log(f"       ⚠️  Файл не найден для удаления")
                except Exception as e:
                    self._log(f"       ✗ Ошибка при удалении: {str(e)}")
                    self.stats['errors'] += 1
                continue
            
            # New file - add to structure
            new_files_count += 1
            
            # Store subseries info if present (parse from filename)
            subseries = self._extract_subseries(record)
            
            # Build folder path
            folder_structure[record.file_path] = (
                primary_genre,
                author,
                series,
                subseries
            )
            
            # Record as existing for duplicate detection in this batch
            existing_entries.add(dup_key)
        
        self._log(f"")
        self._log(f"РЕЗУЛЬТАТЫ АНАЛИЗА:")
        self._log(f"  Новые файлы: {new_files_count}")
        self._log(f"  Дубликаты: {duplicate_files_count}")
        self._log(f"  Итого файлов в структуре: {len(folder_structure)}")
        
        return folder_structure
    
    def _extract_subseries(self, record) -> str:
        """Extract subseries information from record if present.
        
        Args:
            record: BookRecord object
            
        Returns:
            Subseries string or empty string
        """
        # For now, return empty - can be enhanced to parse from metadata
        return ""
    
    def _move_files(
        self,
        records: List,
        folder_structure: Dict,
        progress_callback: Optional[Callable] = None
    ) -> List:
        """Move files to library structure.
        
        Args:
            records: List of BookRecord objects
            folder_structure: Dictionary with folder mapping
            progress_callback: Progress callback function
            
        Returns:
            List of successfully moved records with updated file_path
        """
        self._log("Начало перемещения файлов")
        self._log(f"Всего записей: {len(records)}, в структуре: {len(folder_structure)}")
        
        # Log first few items in folder_structure
        if folder_structure:
            for file_path in list(folder_structure.keys())[:3]:
                self._log(f"  В структуре: {file_path}")
        
        deleted_duplicates = len(records) - len(folder_structure)
        if deleted_duplicates > 0:
            self._log(f"🗑️  {deleted_duplicates} дубликатов удалены")
        
        moved_records = []
        
        for i, record in enumerate(records):
            # Delete if no structure (duplicate)
            if record.file_path not in folder_structure:
                self._log(f"[{i+1}/{len(records)}] 🗑️  УДАЛЕН: {record.file_path} (дубликат - уже в БД)")
                try:
                    file_to_delete = self.last_scan_path / record.file_path
                    if file_to_delete.exists():
                        os.unlink(str(file_to_delete))
                        self._log(f"       ✓ Успешно удален")
                        self.stats['duplicates_deleted'] = self.stats.get('duplicates_deleted', 0) + 1
                    else:
                        self._log(f"       ⚠️  Файл не найден")
                except Exception as e:
                    self._log(f"       ✗ Ошибка при удалении: {str(e)}")
                    self.stats['errors'] += 1
                continue
            
            self._log(f"[{i+1}/{len(records)}] ◆ Обработка: {record.file_path}")
            
            try:
                genre, author, series, subseries = folder_structure[record.file_path]
                
                # Build target path
                target_dir = self.library_path / genre / author
                if series:
                    target_dir = target_dir / series
                if subseries:
                    target_dir = target_dir / subseries

                # Path traversal guard: ensure target stays inside library_path
                resolved_target = target_dir.resolve()
                resolved_library = self.library_path.resolve()
                if not str(resolved_target).startswith(str(resolved_library)):
                    self._log(f"✖️ Попытка выхода за пределы библиотеки: {target_dir}")
                    self.stats['errors'] += 1
                    continue

                # Create directories
                target_dir.mkdir(parents=True, exist_ok=True)

                # Build source and target file paths
                source_file = self.last_scan_path / record.file_path
                target_file = target_dir / source_file.name
                
                # Check if file already exists at target
                if target_file.exists():
                    self._log(f"⚠️  Файл уже существует в библиотеке: {target_file}")
                    self._log(f"    Пропускаем перемещение")
                    self.stats['duplicates_found'] += 1
                    continue
                
                # Move file
                if source_file.exists():
                    self._log(f"  → Перемещение: {source_file.name}")
                    shutil.move(str(source_file), str(target_file))
                    self._log(f"  ✓ Успешно перемещён")
                    self.stats['files_moved'] += 1

                    # Patch FB2 metadata tags (author + series) in the moved file.
                    # Books with >=3 original authors: do not touch author tags.
                    orig_auth_count = len([
                        a for a in re.split(r'[;,]+', record.metadata_authors or '')
                        if a.strip()
                    ])
                    patch_author = record.proposed_author if orig_auth_count < 3 else None
                    self._patch_fb2_tags(
                        target_file,
                        patch_author,
                        record.proposed_series or "",
                    )

                    # Update record with new path (relative to library_path)
                    record.file_path = str(target_file.relative_to(self.library_path))
                    moved_records.append(record)
                    self._log(f"    Новый путь: {record.file_path}")
                else:
                    self._log(f"  ✗ Ошибка: файл не найден: {source_file}")
                    self.stats['errors'] += 1
                    
            except Exception as e:
                self._log(f"ОШИБКА при перемещении {record.file_path}: {str(e)}")
                import traceback
                self._log(f"Stacktrace: {traceback.format_exc()}")
                self.stats['errors'] += 1
        
        self._log(f"Перемещение завершено: {len(moved_records)} файлов переместили")
        return moved_records
    
    def _update_database(
        self,
        records: List,
        progress_callback: Optional[Callable] = None
    ) -> None:
        """Insert records into database.
        
        Args:
            records: List of BookRecord objects (successfully moved files)
            progress_callback: Progress callback function
        """
        self._log(f"Обновление базы данных: {self.db_path}")
        self._log(f"Количество записей для внесения: {len(records)}")
        
        if not records:
            self._log("ВНИМАНИЕ: Нет файлов для внесения в БД")
            self._log("Проверьте, были ли файлы успешно перемещены")
            return
        
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            rows_to_insert = []

            for i, record in enumerate(records):
                # Progress update
                if progress_callback and i % 10 == 0:
                    progress_callback(80 + (i / len(records) * 10), 100,
                                    f"Запись в БД: {i+1}/{len(records)}")
                
                try:
                    file_hash = self._calculate_file_hash(
                        self.library_path / record.file_path
                    )
                    rows_to_insert.append((
                        record.proposed_author,
                        record.author_source,
                        record.proposed_series,
                        record.series_source,
                        getattr(record, 'subseries', ''),
                        record.file_title,
                        record.file_path,
                        file_hash,
                        record.metadata_genre,
                        now, now, now,
                    ))
                except Exception as e:
                    self._log(f"ОШИБКА при подготовке записи {record.file_path}: {str(e)}")
                    self.stats['errors'] += 1

            if rows_to_insert:
                cursor.executemany("""
                    INSERT INTO books (
                        author, author_source, series, series_source,
                        subseries, title, file_path, file_hash, genre,
                        added_date, updated_date, last_sync_check
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, rows_to_insert)

            inserted_count = len(rows_to_insert) - self.stats.get('errors', 0)
            self._log(f"Коммит базы данных... ({inserted_count} записей)")
            conn.commit()
            self._log(f"Коммит завершён успешно")
            self._log(f"Записано в БД: {inserted_count} записей")
            
        except Exception as e:
            self._log(f"ОШИБКА при обновлении БД: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
            self.stats['errors'] += 1
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    def _cleanup_empty_folders(self) -> None:
        """Remove empty folders from source directory, preserving root.
        
        Recursively deletes empty directories but preserves last_scan_path root.
        """
        self._log(f"Очистка пустых папок в: {self.last_scan_path}")
        
        try:
            self._remove_empty_dirs_recursive(self.last_scan_path)
            self._log(f"Удалено пустых папок: {self.stats['folders_deleted']}")
        except Exception as e:
            self._log(f"Ошибка при очистке папок: {str(e)}")
    
    def _remove_empty_dirs_recursive(self, path: Path) -> None:
        """Recursively remove empty directories.
        
        Args:
            path: Directory to clean
        """
        if not path.is_dir():
            return
        
        # Don't delete root scan path
        if path == self.last_scan_path:
            # Just process subdirectories
            for item in path.iterdir():
                if item.is_dir():
                    self._remove_empty_dirs_recursive(item)
            return
        
        # Try to remove if empty
        try:
            # First, recursively process subdirectories
            for item in path.iterdir():
                if item.is_dir():
                    self._remove_empty_dirs_recursive(item)
            
            # Now try to remove this directory if empty
            if not any(path.iterdir()):  # Check if empty
                path.rmdir()
                self.stats['folders_deleted'] += 1
                self._log(f"Удалена пустая папка: {path}")
        except Exception as e:
            # Ignore errors (directory may be in use, has files, etc)
            pass
    
    def _get_existing_entries(self) -> set:
        """Get existing entries from database.
        
        Returns:
            Set of (author, series, title) tuples
        """
        existing = set()
        
        try:
            if not self.db_path.exists():
                self._log(f"БД не найдена: {self.db_path}")
                return existing
            
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT author, series, title FROM books
            """)
            
            rows = cursor.fetchall()
            self._log(f"Прочитано из БД: {len(rows)} существующих записей")
            
            for row in rows:
                existing.add(tuple(row))
            
            conn.close()
        except Exception as e:
            self._log(f"Ошибка при чтении БД: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
        
        return existing
    
    def _calculate_file_hash(self, file_path: Path, chunk_size: int = 8192) -> str:
        """Calculate SHA256 hash of file.
        
        Args:
            file_path: Path to file
            chunk_size: Size of chunks to read
            
        Returns:
            Hexadecimal hash string
        """
        try:
            hash_obj = hashlib.sha256()
            
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    hash_obj.update(chunk)
            
            return hash_obj.hexdigest()
        except Exception as e:
            self.logger.log(f"Ошибка при расчёте хеша {file_path}: {str(e)}")
            return ""
    
    def get_statistics(self) -> Dict:
        """Get current statistics.
        
        Returns:
            Dictionary with statistics
        """
        stats = self.stats.copy()
        
        if stats['start_time'] and stats['end_time']:
            duration = (stats['end_time'] - stats['start_time']).total_seconds()
            stats['duration_seconds'] = duration
            stats['duration_str'] = f"{int(duration)} секунд"
        
        return stats

    # ------------------------------------------------------------------
    # FB2 tag patching
    # ------------------------------------------------------------------

    def _patch_fb2_tags(
        self,
        fb2_path: Path,
        proposed_author: Optional[str],
        proposed_series: str,
    ) -> None:
        """Overwrite <author> and <sequence> tags in a FB2 file.

        The file is read and written back with its **original** encoding
        (detected from the XML declaration or trial-decoded).

        Args:
            fb2_path:        Absolute path to the already-moved FB2 file.
            proposed_author: Author string in "Фамилия Имя[, …]" format.
                             ``None`` — leave existing <author> tags untouched.
            proposed_series: Series name to write into <sequence name="…"/>.
                             Empty string — leave existing <sequence> untouched.
        """
        if proposed_author is None and not proposed_series:
            return

        try:
            raw_bytes = fb2_path.read_bytes()

            # ---- detect encoding ----
            declared_enc = None
            decl_m = re.search(
                rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']',
                raw_bytes, re.IGNORECASE,
            )
            if decl_m:
                try:
                    declared_enc = decl_m.group(1).decode('ascii', errors='ignore')
                except Exception:
                    pass

            enc_candidates = []
            if declared_enc:
                enc_candidates.append(declared_enc)
            enc_candidates.extend(['utf-8-sig', 'utf-8', 'cp1251', 'latin-1'])

            seen_enc: set = set()
            content: Optional[str] = None
            content_encoding = 'utf-8'

            for enc in enc_candidates:
                norm = enc.lower().replace('-', '').replace('_', '')
                if norm in seen_enc:
                    continue
                seen_enc.add(norm)
                try:
                    candidate = raw_bytes.decode(enc, errors='strict')
                except (LookupError, UnicodeDecodeError):
                    continue
                if candidate.lstrip('\ufeff').lstrip().startswith(('<', '<?')):
                    content = candidate
                    content_encoding = enc
                    break

            if content is None:
                self._log(f"  ⚠️  Не удалось определить кодировку: {fb2_path.name}")
                return

            # ---- strip / remember BOM ----
            has_bom = content.startswith('\ufeff')
            if has_bom:
                content = content[1:]

            # ---- locate <title-info> section ----
            ti_m = re.search(
                r'(<(?:fb:)?title-info>)(.*?)(</(?:fb:)?title-info>)',
                content, re.DOTALL,
            )
            if not ti_m:
                self._log(f"  ⚠️  <title-info> не найден в {fb2_path.name}")
                return

            ti_open  = ti_m.group(1)
            ti_body  = ti_m.group(2)
            ti_close = ti_m.group(3)

            # namespace prefix used in this file
            ns = 'fb:' if ti_open.startswith('<fb:') else ''

            # ---- 1. patch author tags ----
            if proposed_author:
                authors = [a.strip() for a in re.split(r'[,;]+', proposed_author) if a.strip()]
                author_xmls = []
                for auth in authors:
                    parts = auth.split()
                    if len(parts) == 1:
                        xml = (
                            f'<{ns}author>'
                            f'<{ns}last-name>{parts[0]}</{ns}last-name>'
                            f'</{ns}author>'
                        )
                    elif len(parts) == 2:
                        xml = (
                            f'<{ns}author>'
                            f'<{ns}last-name>{parts[0]}</{ns}last-name>'
                            f'<{ns}first-name>{parts[1]}</{ns}first-name>'
                            f'</{ns}author>'
                        )
                    else:
                        xml = (
                            f'<{ns}author>'
                            f'<{ns}last-name>{parts[0]}</{ns}last-name>'
                            f'<{ns}first-name>{parts[1]}</{ns}first-name>'
                            f'<{ns}middle-name>{" ".join(parts[2:])}</{ns}middle-name>'
                            f'</{ns}author>'
                        )
                    author_xmls.append(xml)

                new_authors_block = '\n    '.join(author_xmls)

                # remove all existing <author> blocks (including whitespace around them)
                ti_body = re.sub(
                    r'\s*<(?:fb:)?author>.*?</(?:fb:)?author>',
                    '', ti_body, flags=re.DOTALL,
                )

                # insert before <book-title> (or prepend if absent)
                bt_m = re.search(r'<(?:fb:)?book-title', ti_body)
                if bt_m:
                    pos = bt_m.start()
                    ti_body = (
                        ti_body[:pos]
                        + '\n    ' + new_authors_block + '\n    '
                        + ti_body[pos:]
                    )
                else:
                    ti_body = '\n    ' + new_authors_block + ti_body

            # ---- 2. patch series tag ----
            if proposed_series:
                seq_m = re.search(r'<sequence\b[^>]*/?\s*>', ti_body, re.IGNORECASE)

                # preserve existing <number> attribute if any
                number_attr = ''
                if seq_m:
                    num_m = re.search(
                        r'number\s*=\s*["\']([^"\']*)["\']',
                        seq_m.group(0), re.IGNORECASE,
                    )
                    if num_m:
                        number_attr = f' number="{num_m.group(1)}"'

                new_seq = f'<sequence name="{proposed_series}"{number_attr}/>'
                if seq_m:
                    ti_body = ti_body[:seq_m.start()] + new_seq + ti_body[seq_m.end():]
                else:
                    ti_body = ti_body.rstrip() + '\n    ' + new_seq + '\n  '

            # ---- reconstruct content ----
            new_ti = ti_open + ti_body + ti_close
            result = content[:ti_m.start()] + new_ti + content[ti_m.end():]

            if has_bom:
                result = '\ufeff' + result

            # ---- write back with ORIGINAL encoding ----
            try:
                out_bytes = result.encode(content_encoding, errors='replace')
            except LookupError:
                out_bytes = result.encode('utf-8', errors='replace')

            fb2_path.write_bytes(out_bytes)
            self._log(f"  ✓ Теги обновлены ({content_encoding}): {fb2_path.name}")

        except Exception as e:
            import traceback
            self._log(f"  ✗ Ошибка обновления тегов {fb2_path.name}: {e}")
            self._log(traceback.format_exc())
