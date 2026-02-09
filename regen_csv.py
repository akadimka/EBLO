#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV Regeneration Service - Main orchestrator for the 6-PASS system

Главный модуль для регенерации CSV с использованием 6-PASS системы:
- PASS 1: Определение автора по приоритету (папка → файл → метаданные)
- PASS 2: [пропущен]
- PASS 3: Нормализация формата авторов
- PASS 4: Применение консенсуса
- PASS 5: Переприменение conversions
- PASS 6: Раскрытие аббревиатур

Использует модульную архитектуру:
- fb2_author_extractor.py - PASS 1 логика
- author_normalizer_extended.py - PASS 3, 5, 6 логика
- author_processor.py - PASS 4 логика консенсуса
"""

import csv
import os
from pathlib import Path
from typing import List, Dict, Optional, Callable
from dataclasses import asdict
import sys

try:
    from author_normalizer_extended import (
        BookRecord,
        apply_author_normalization,
        apply_surname_conversions_to_records,
        apply_author_consensus,
        build_authors_map,
        expand_abbreviated_authors,
    )
    from fb2_author_extractor import FB2AuthorExtractor
    from settings_manager import SettingsManager
    from logger import Logger
except ImportError:
    from .author_normalizer_extended import (
        BookRecord,
        apply_author_normalization,
        apply_surname_conversions_to_records,
        apply_author_consensus,
        build_authors_map,
        expand_abbreviated_authors,
    )
    from .fb2_author_extractor import FB2AuthorExtractor
    from .settings_manager import SettingsManager
    from .logger import Logger


class RegenCSVService:
    """Service для регенерации CSV файла с авторами."""
    
    def __init__(self, config_path: str = 'config.json'):
        """Initialize the service.
        
        Args:
            config_path: Path to config.json
        """
        self.settings = SettingsManager(config_path)
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor(config_path)
        
        # FB2 файлы сканируются из last_scan_path (рабочей папки), определённой в config.json
        self.work_dir = Path(self.settings.get_last_scan_path())
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
        
        self.records: List[BookRecord] = []
    
    def regenerate(self, output_csv: Optional[str] = None) -> bool:
        """Выполнить полный цикл регенерации CSV.
        
        Args:
            output_csv: Путь к выходному CSV файлу (если None - использует config)
            
        Returns:
            True если успешно, False иначе
        """
        try:
            print("\n" + "🚀 "*40, flush=True)
            print("\n  📊 РЕГЕНЕРАЦИЯ CSV - 6-PASS СИСТЕМА", flush=True)
            print(f"  📁 Рабочая папка: {self.work_dir}\n", flush=True)
            print("🚀 "*40 + "\n", flush=True)
            
            self.logger.log("=== Начало регенерации CSV ===")
            
            # PASS 1: Инициализация - чтение FB2 файлов и определение авторов
            self._pass1_read_fb2_files()
            if not self.records:
                self.logger.log("❌ Нет найдено FB2 файлов")
                return False
            
            self.logger.log(f"✅ PASS 1: Прочитано {len(self.records)} файлов")
            
            # PASS 2: [пропущен]
            self.logger.log("⏭️  PASS 2: [пропущен]")
            
            # PASS 3: Нормализация формата авторов
            self._pass3_normalize_authors()
            self.logger.log(f"✅ PASS 3: Завершена нормализация авторов")
            
            # PASS 4: Применение консенсуса
            self._pass4_apply_consensus()
            self.logger.log(f"✅ PASS 4: Завершено применение консенсуса")
            
            # PASS 5: Переприменение conversions
            self._pass5_apply_conversions()
            self.logger.log(f"✅ PASS 5: Завершено переприменение conversions")
            
            # PASS 6: Раскрытие аббревиатур
            self._pass6_expand_abbreviations()
            self.logger.log(f"✅ PASS 6: Завершено раскрытие аббревиатур")
            
            # Сохранение в CSV
            csv_path = output_csv or self._get_output_csv_path()
            self._save_csv(csv_path)
            
            self.logger.log(f"✅ CSV сохранён: {csv_path}")
            self.logger.log("=== Регенерация завершена успешно ===")
            
            # Финальный вывод
            print("="*80, flush=True)
            print("✅ РЕГЕНЕРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!", flush=True)
            print("="*80 + "\n", flush=True)
            
            return True
            
        except Exception as e:
            self.logger.log(f"❌ Ошибка при регенерации: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _build_folder_structure(self) -> Dict[Path, str]:
        """Построить структуру папок и определить авторские папки.
        
        Анализирует иерархию папок и определяет, какие папки являются авторскими
        (содержат книги одного автора).
        
        Returns:
            Dict[Path, str]: Словарь {папка_путь: имя_автора}
        """
        folder_authors = {}
        
        # Проанализировать первые N уровней вверх от корня work_dir
        # Папки на уровне 1 от work_dir часто являются авторскими папками
        for folder in self.work_dir.iterdir():
            if folder.is_dir():
                folder_name = folder.name
                
                # Проверить: это авторская папка?
                # Авторская папка обычно содержит:
                # - Только FB2 файлы + подпапки с серией
                # - НЕ содержит слова из blacklist (сборник, компиляция)
                
                blacklist = self.settings.get_filename_blacklist()
                is_blacklisted = any(word.lower() in folder_name.lower() for word in blacklist)
                
                if not is_blacklisted:
                    # Это вероятно авторская папка
                    folder_authors[folder] = folder_name
                
                self.logger.log(f"[Структура] Папка: {folder_name} → автор: {folder_name if not is_blacklisted else '[исключена]'}")
        
        return folder_authors
    
    def _get_author_for_file(self, fb2_file: Path, folder_authors: Dict[Path, str]) -> tuple:
        """Определить автора для конкретного файла используя структуру папок.
        
        Приоритет:
        1. Если файл в авторской папке → используем автора из папки (folder_dataset)
        2. Иначе → вызваем resolve_author_by_priority (параллельно filename и metadata)
        
        Args:
            fb2_file: путь к FB2 файлу
            folder_authors: словарь авторских папок из _build_folder_structure()
            
        Returns:
            (author, source) где source in ['folder_dataset', 'filename', 'metadata', '']
        """
        # Проверить: находится ли файл в авторской папке?
        for author_folder, author_name in folder_authors.items():
            try:
                # Проверить: fb2_file в папке author_folder?
                fb2_file.relative_to(author_folder)
                # Да! Файл в авторской папке
                
                # Применить conversions к имени автора из папки
                author_name_converted = author_name
                conversions = self.settings.get_author_surname_conversions()
                if author_name in conversions:
                    author_name_converted = conversions[author_name]
                
                return author_name_converted, 'folder_dataset'
            except ValueError:
                # Нет, не в этой папке
                continue
        
        # Файл не в авторской папке → используем обычную логику
        author, source = self.extractor.resolve_author_by_priority(
            str(fb2_file),
            folder_parse_limit=self.folder_parse_limit
        )
        
        return author, source
    
    def _pass1_read_fb2_files(self) -> None:
        """PASS 1: Чтение FB2 файлов и определение авторов по приоритету.
        
        Алгоритм:
        1. Построить логическую структуру папок с определением авторских папок
        2. Для каждого файла использовать инфо об авторской папке
        3. Если файл в авторской папке → author_source = "folder_dataset"
        4. Если файл вне авторской папки → пробовать filename → metadata
        """
        print("\n" + "="*80, flush=True)
        print("🔄 PASS 1: Сканирование FB2 файлов...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 1] Начало сканирования FB2 файлов...")
        
        # Шаг 1: Построить структуру папок для определения авторских папок
        folder_authors = self._build_folder_structure()
        
        fb2_count = 0
        error_count = 0
        
        for fb2_file in self.work_dir.rglob('*.fb2'):
            try:
                # Получить путь относительно рабочей папки (work_dir)
                rel_path = fb2_file.relative_to(self.work_dir)
                
                fb2_count += 1
                # Выводим первые 5 и каждый 50-й файл
                if fb2_count <= 5 or fb2_count % 50 == 0:
                    print(f"  [{fb2_count:4d}] {rel_path}", flush=True)
                
                # Определить автора с использованием предварительно построенной структуры
                author, source = self._get_author_for_file(fb2_file, folder_authors)
                
                # Извлечь заголовок из метаданных FB2
                title = self.extractor._extract_title_from_fb2(fb2_file)
                
                # Получить оригинальные авторы из метаданных
                metadata_authors = self.extractor._extract_author_from_metadata(fb2_file)
                
                # TODO: Извлечь серию из метаданных FB2 (пока пусто)
                metadata_series = ""
                
                # Создать BookRecord
                record = BookRecord(
                    file_path=str(rel_path),
                    file_title=title or "[без названия]",
                    metadata_authors=metadata_authors or "[неизвестно]",
                    proposed_author=author or "Сборник",
                    author_source=source or "metadata",
                    metadata_series=metadata_series,
                    proposed_series=metadata_series,  # На PASS 1 = metadata (пока пусто)
                    series_source=""  # На PASS 1: series не заполняется (нет логики)
                )
                
                self.records.append(record)
                
                if fb2_count % 100 == 0:
                    self.logger.log(f"  [PASS 1] Обработано {fb2_count} файлов...")
                
            except Exception as e:
                error_count += 1
                self.logger.log(f"⚠️  [PASS 1] Ошибка при чтении {fb2_file}: {e}")
        
        print(f"\n✅ PASS 1 завершён: прочитано {fb2_count} файлов (ошибок: {error_count})\n", flush=True)
        self.logger.log(f"[PASS 1] Прочитано {fb2_count} файлов (ошибок: {error_count})")
    
    def _pass3_normalize_authors(self) -> None:
        """PASS 3: Нормализовать формат авторов.
        
        "Иван Петров" → "Петров Иван"
        Использует AuthorName класс для логики.
        """
        print("\n" + "="*80, flush=True)
        print("🔤 PASS 3: Нормализация формата авторов...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 3] Начало нормализации формата...")
        
        changed_count = 0
        for record in self.records:
            original = record.proposed_author
            apply_author_normalization(record)
            if record.proposed_author != original:
                changed_count += 1
        
        print(f"✅ PASS 3 завершён: {changed_count} авторов нормализовано\n", flush=True)
        self.logger.log(f"[PASS 3] Изменено {changed_count} авторов")
    
    def _pass4_apply_consensus(self) -> None:
        """PASS 4: Применить консенсус к группам файлов.
        
        Файлы с author_source="folder_dataset" НЕ меняются.
        Консенсус применяется только к файлам в одной папке с source="filename" или "metadata".
        """
        print("\n" + "="*80, flush=True)
        print("🤝 PASS 4: Применение консенсуса к группам...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 4] Начало применения консенсуса...")
        
        # Функция для определения группы - parent folder
        def group_by_folder(record: BookRecord) -> str:
            return str(Path(record.file_path).parent)
        
        # Применить консенсус
        apply_author_consensus(self.records, group_by_folder, self.settings)
        
        # Статистика
        consensus_count = sum(1 for r in self.records if r.author_source == "consensus")
        print(f"✅ PASS 4 завершён: {consensus_count} файлов обработано консенсусом\n", flush=True)
        self.logger.log("[PASS 4] Завершено")
    
    def _pass5_apply_conversions(self) -> None:
        """PASS 5: Переприменить conversions после консенсуса.
        
        Это нужно потому что консенсус может изменить автора на другого,
        и нужно переприменить conversions для новой фамилии.
        """
        print("\n" + "="*80, flush=True)
        print("🔄 PASS 5: Переприменение conversions после консенсуса...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 5] Начало переприменения conversions...")
        
        changed_count = 0
        original_authors = {id(r): r.proposed_author for r in self.records}
        
        apply_surname_conversions_to_records(self.records, self.settings)
        
        for record in self.records:
            if record.proposed_author != original_authors.get(id(record)):
                changed_count += 1
        
        print(f"✅ PASS 5 завершён: {changed_count} авторов переприменены conversions\n", flush=True)
        self.logger.log(f"[PASS 5] Переприменено conversions к {changed_count} авторам")
    
    def _pass6_expand_abbreviations(self) -> None:
        """PASS 6: Раскрыть аббревиатуры в именах авторов.
        
        "И.Петров" → "Иван Петров"
        Требует построения словаря полных имён из всех авторов.
        """
        print("\n" + "="*80, flush=True)
        print("📚 PASS 6: Раскрытие аббревиатур в именах...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 6] Начало раскрытия аббревиатур...")
        
        # Построить словарь авторов
        authors_map = build_authors_map(self.records, self.settings)
        print(f"  Построено {len(authors_map)} уникальных фамилий", flush=True)
        self.logger.log(f"  [PASS 6] Построено {len(authors_map)} уникальных фамилий")
        
        # Раскрыть аббревиатуры
        expand_abbreviated_authors(self.records, authors_map, self.settings)
        
        print(f"✅ PASS 6 завершён\n", flush=True)
        self.logger.log("[PASS 6] Завершено")
    
    def _save_csv(self, output_path: str) -> None:
        """Сохранить результаты в CSV файл.
        
        Колонки CSV (согласно пункту 6.1 документации):
        1. file_path - путь к FB2 относительно library_path
        2. metadata_authors - оригинальные авторы из FB2
        3. proposed_author - финальный автор после PASS
        4. author_source - источник автора
        5. metadata_series - оригинальная серия из FB2
        6. proposed_series - финальная серия после PASS
        7. series_source - источник серии
        8. file_title - название книги
        
        Args:
            output_path: Путь к файлу для сохранения
        """
        print("\n" + "="*80, flush=True)
        print("💾 Сохранение результатов в CSV файл...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log(f"[CSV] Сохранение CSV в {output_path}...")
        
        # Убедиться что директория существует
        output_path_obj = Path(output_path)
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # Отсортировать по file_path для консистентности
        sorted_records = sorted(self.records, key=lambda r: r.file_path)
        
        # Написать CSV с всеми 8 колонками согласно документации 6.1
        fieldnames = [
            'file_path',
            'metadata_authors', 
            'proposed_author', 
            'author_source',
            'metadata_series',
            'proposed_series',
            'series_source',
            'file_title'
        ]
        
        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for record in sorted_records:
                row = {
                    'file_path': record.file_path,
                    'metadata_authors': record.metadata_authors,
                    'proposed_author': record.proposed_author,
                    'author_source': record.author_source,
                    'metadata_series': record.metadata_series,
                    'proposed_series': record.proposed_series,
                    'series_source': record.series_source,
                    'file_title': record.file_title,
                }
                writer.writerow(row)
        
        # Статистика
        total = len(sorted_records)
        by_source = {}
        for record in sorted_records:
            source = record.author_source
            by_source[source] = by_source.get(source, 0) + 1
        
        # Вывод в консоль
        print(f"\n✅ CSV сохранён успешно: {total} записей", flush=True)
        print(f"   Путь: {output_path}", flush=True)
        print(f"\n   Статистика по источникам:", flush=True)
        for source, count in sorted(by_source.items()):
            print(f"   • {source:20s}: {count:4d} ({count*100//total}%)", flush=True)
        print()
        
        self.logger.log(f"✅ [CSV] CSV сохранён: {total} записей")
        for source, count in sorted(by_source.items()):
            self.logger.log(f"  [CSV] {source}: {count}")
    
    def _get_output_csv_path(self) -> str:
        """Получить путь к выходному CSV файлу.
        
        CSV файл ВСЕГДА сохраняется в папке проекта (текущая папка скрипта) как regen.csv
        Это гарантирует единую точку сохранения независимо от work_dir.
        
        Returns:
            Путь к файлу CSV в папке проекта
        """
        # CSV файл сохраняется в папке проекта (где находится regen_csv.py)
        project_dir = Path(__file__).parent
        return str(project_dir / 'regen.csv')




def main():
    """Точка входа для запуска регенерации CSV."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Регенерация CSV файла с авторами FB2 библиотеки'
    )
    parser.add_argument(
        '--config',
        type=str,
        default='config.json',
        help='Путь к config.json (по умолчанию: config.json)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Путь к выходному CSV (по умолчанию: папка проекта/regen.csv)'
    )
    
    args = parser.parse_args()
    
    service = RegenCSVService(args.config)
    success = service.regenerate(args.output)
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
