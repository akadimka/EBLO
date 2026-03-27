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
        
    def sync_database_with_library(self, log_callback: Optional[Callable] = None) -> Dict:
        """Synchronize database with actual library structure.
        
        Removes entries for files that physically no longer exist in the library.
        Call this at application startup to clean up orphaned database records.
        
        Args:
            log_callback: Function(message_str) for logging messages to UI
            
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
            
            self._log(f"Всего записей в БД: {len(rows)}")
            
            deleted_ids = []
            
            for row in rows:
                record_id, file_path, author, series, title = row
                stats['checked'] += 1
                
                # Check if file physically exists
                full_path = self.library_path / file_path
                
                if not full_path.exists():
                    self._log(f"✗ Orphaned запись: {author} | {series} | {title}")
                    self._log(f"  Файл не найден: {file_path}")
                    deleted_ids.append(record_id)
                    stats['deleted'] += 1
            
            # Delete orphaned records
            if deleted_ids:
                placeholders = ','.join(['?' for _ in deleted_ids])
                cursor.execute(f"DELETE FROM books WHERE id IN ({placeholders})", deleted_ids)
                
                self._log(f"Удалено orphaned записей: {len(deleted_ids)}")
                conn.commit()
            
            conn.close()
            
            self._log(f"Синхронизация БД завершена: "
                     f"проверено {stats['checked']}, удалено {stats['deleted']}")
            self._log("=" * 60)
            
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
            self._log("Шаг 0: Очистка БД от orphaned записей")
            db_cleanup = self.sync_database_with_library(log_callback)
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
            self._log(f"Синхронизация завершена: {self.stats}")
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
            for entry in list(existing_entries)[:3]:
                self._log(f"  БД запись: {entry}")
        
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
            self._log(f"  Файл [{i+1}]: {record.file_path}")
            self._log(f"    -> Ключ дубликата: {dup_key}")
            self._log(f"    -> В БД: {dup_key in existing_entries}")
            
            if dup_key in existing_entries:
                self._log(f"    ✗ ДУБЛИКАТ найден")
                duplicates[dup_key].append(record.file_path)
                self.stats['duplicates_found'] += 1
                continue
            
            self._log(f"    ✓ Новый файл, добавляем в структуру")
            
            # Store subseries info if present (parse from filename)
            subseries = self._extract_subseries(record)
            
            # Build folder path
            folder_structure[record.file_path] = (
                primary_genre,
                author,
                series,
                subseries
            )
            
            self._log(f"    Добавлен: {author} | {primary_genre} | {series}")
            
            # Record as existing for duplicate detection
            existing_entries.add(dup_key)
        
        self._log(f"Структура создана: {len(folder_structure)} файлов, "
                       f"{len(duplicates)} дубликатов")
        
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
        
        if len(folder_structure) < len(records):
            self._log(f"⚠️  {len(records) - len(folder_structure)} файлов не в структуре (дубликаты или ошибки)")
        
        moved_records = []
        
        for i, record in enumerate(records):
            # Skip if no structure (duplicate)
            if record.file_path not in folder_structure:
                self._log(f"[{i+1}/{len(records)}] ⊘ ПРОПУЩЕН: {record.file_path} (не в структуре)")
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
                
                # Create directories
                target_dir.mkdir(parents=True, exist_ok=True)
                
                # Build source and target file paths
                source_file = self.last_scan_path / record.file_path
                target_file = target_dir / source_file.name
                
                # Check if file already exists at target
                if target_file.exists():
                    self._log(f"Файл уже существует: {target_file}")
                    self.stats['duplicates_found'] += 1
                    continue
                
                # Move file
                if source_file.exists():
                    shutil.move(str(source_file), str(target_file))
                    self._log(f"Перемещён: {source_file} -> {target_file}")
                    self.stats['files_moved'] += 1
                    
                    # Update record with new path (relative to library_path)
                    record.file_path = str(target_file.relative_to(self.library_path))
                    moved_records.append(record)
                    self._log(f"  -> Добавлен в moved_records (новый путь: {record.file_path})")
                else:
                    self._log(f"ОШИБКА: файл не найден: {source_file}")
                    self.stats['errors'] += 1
                    
            except Exception as e:
                self._log(f"Ошибка при перемещении {record.file_path}: {str(e)}")
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
            
            inserted_count = 0
            
            for i, record in enumerate(records):
                # Progress update
                if progress_callback and i % 10 == 0:
                    progress_callback(80 + (i / len(records) * 10), 100,
                                    f"Запись в БД: {i+1}/{len(records)}")
                
                try:
                    # Calculate file hash
                    file_hash = self._calculate_file_hash(
                        self.library_path / record.file_path
                    )
                    
                    now = datetime.now().isoformat()
                    
                    self._log(f"Запись в БД: {record.proposed_author} | {record.proposed_series} | {record.file_title}")
                    
                    cursor.execute("""
                        INSERT INTO books (
                            author, author_source, series, series_source,
                            subseries, title, file_path, file_hash, genre,
                            added_date, updated_date, last_sync_check
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        record.proposed_author,
                        record.author_source,
                        record.proposed_series,
                        record.series_source,
                        getattr(record, 'subseries', ''),
                        record.file_title,
                        record.file_path,
                        file_hash,
                        record.metadata_genre,
                        now,
                        now,
                        now
                    ))
                    
                    inserted_count += 1
                    self._log(f"  -> Успешно записано (ID: {cursor.lastrowid})")
                    
                except Exception as e:
                    self._log(f"ОШИБКА при записи в БД {record.file_path}: {str(e)}")
                    import traceback
                    self._log(f"Stacktrace: {traceback.format_exc()}")
                    self.stats['errors'] += 1
            
            self._log(f"Коммит базы данных... ({inserted_count} записей)")
            conn.commit()
            self._log(f"Коммит завершён успешно")
            conn.close()
            
            self._log(f"Записано в БД: {inserted_count} записей")
            
        except Exception as e:
            self._log(f"ОШИБКА при обновлении БД: {str(e)}")
            import traceback
            self._log(f"Stacktrace: {traceback.format_exc()}")
            self.stats['errors'] += 1
    
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
                self._log(f"  Существующий: {row[0]} | {row[1]} | {row[2]}")
            
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
