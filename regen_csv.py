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
            
            # PASS 2: Извлечение автора из имени файла
            self._pass2_extract_from_filename()
            self.logger.log(f"✅ PASS 2: Извлечение авторов из имён файлов")
            
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
            
            # Сортировка записей: отдельные файлы по алфавиту, потом папки по алфавиту
            self._sort_records()
            self.logger.log(f"✅ Записи отсортированы")
            
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
    
    def _parse_author_from_folder_name(self, folder_name: str) -> str:
        """Распарсить авторов из названия папки.
        
        Везде есть формат: "название_серии (авторы)" или "название_серии (автор1, автор2)"
        Правильно обрабатывает случаи с несколькими скобками:
        "МВП-2 (1) Одиссея (Александр Чернов)" → "Александр Чернов"
        
        Логика:
        - Если 1 автор: возвращаем его как есть
        - Если 2 автора: возвращаем обоих через '; ' (будет нормализовано в PASS позже)
        - Если >2: берём первого
        
        Args:
            folder_name: Название папки
            
        Returns:
            Имя автора/авторов из папки
        """
        import re
        
        # Сначала проверить есть ли содержимое в скобках
        # Паттерн: "название (содержимое)" - ищет ПОСЛЕДНИЕ скобки в строке
        # Используем [^)]* чтобы избежать несоответствия с вложенными скобками
        match = re.search(r'\(([^)]*)\)$', folder_name)
        
        if match:
            # Есть скобки с авторами
            authors_str = match.group(1)  # "А.Михайловский, А.Харников" или "Буланов Константин"
            
            # Если есть несколько авторов разделённых запятой
            if ',' in authors_str:
                # Разбить на авторов
                authors = [a.strip() for a in authors_str.split(',')]
                
                if len(authors) <= 2:
                    # <= 2 авторов - берём всех через '; ' (временный разделитель для PASS)
                    return '; '.join(authors)
                else:
                    # > 2 авторов - берём только первого
                    return authors[0]
            
            # Иначе просто один автор в скобках
            return authors_str.strip()
        
        # Нет скобок - это не ожиданный формат, но вернём как есть
        return folder_name
    
    def _build_folder_structure(self) -> Dict[Path, str]:
        """Построить структуру папок и определить авторские папки.
        
        Анализирует иерархию папок и определяет, какие папки являются авторскими
        (содержат книги одного автора). Ищет на разных уровнях вложенности.
        
        Returns:
            Dict[Path, str]: Словарь {папка_путь: имя_автора}
        """
        folder_authors = {}
        blacklist = self.settings.get_filename_blacklist()
        
        # Рекурсивно скан папок до нужной глубины (2-3 уровня)
        # Нужно найти папки типа "Автор Фамилия" которые могут быть на разных уровнях
        def scan_folder(folder_path: Path, depth: int = 0, max_depth: int = 3):
            if depth > max_depth:
                return
            
            try:
                for folder in folder_path.iterdir():
                    if folder.is_dir():
                        folder_name = folder.name
                        
                        # Проверить: это авторская папка?
                        is_blacklisted = any(word.lower() in folder_name.lower() for word in blacklist)
                        
                        if not is_blacklisted:
                            # Это вероятно авторская папка
                            # Парсим имя автора (может быть несколько авторов в названии)
                            author_name = self._parse_author_from_folder_name(folder_name)
                            folder_authors[folder] = author_name
                            
                            parsed_name = author_name if not is_blacklisted else '[исключена]'
                            self.logger.log(f"[Структура {depth}] Папка: {folder_name} → автор: {parsed_name}")
                        
                        # Рекурсивно смотрим подпапки (но не очень глубоко)
                        if depth < max_depth:
                            scan_folder(folder, depth + 1, max_depth)
            except Exception as e:
                self.logger.log(f"[Структура] Ошибка при сканировании {folder_path}: {e}")
        
        # Начинаем сканирование с work_dir
        scan_folder(self.work_dir, depth=0, max_depth=2)
        
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
                
                # Получить всех авторов из метаданных (все авторы из <title-info>)
                metadata_authors = self.extractor._extract_all_authors_from_metadata(fb2_file)
                
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
    
    def _pass2_extract_from_filename(self) -> None:
        """PASS 2: Извлечь авторов из имён файлов и папок.
        
        Для файлов, не определённых в PASS 1 (не folder_dataset),
        ищем автора в любых скобках в пути файла:
        - В самом имени файла: "Название (Автор).fb2"
        - В папках пути: "Папка (Автор)/файл.fb2"
        
        Пропускаем файлы с author_source="folder_dataset" - они уже определены.
        """
        print("\n" + "="*80, flush=True)
        print("📄 PASS 2: Извлечение авторов из имён файлов и папок...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 2] Начало извлечения авторов из имён файлов/папок...")
        
        extracted_count = 0
        
        for record in self.records:
            # Пропустить файлы с folder_dataset - они уже определены надёжно
            if record.author_source == "folder_dataset":
                continue
            
            # Попытаться найти автора в пути файла
            file_path = Path(record.file_path)
            
            # Проверить все части пути, начиная с самой близкой к файлу (справа)
            # Идём вверх по иерархии папок
            parts_to_check = []
            
            # Сначала само имя файла (без расширения)
            parts_to_check.append(file_path.stem)
            
            # Затем все папки в пути (от листа к корню)
            for parent in file_path.parents:
                parts_to_check.append(parent.name)
            
            # Попытаться парсить каждую часть
            parsed_author = None
            for part in parts_to_check:
                parsed_author = self._parse_author_from_folder_name(part)
                if parsed_author and parsed_author != "Сборник":
                    # Нашли - берём первый найденный
                    break
            
            # Если найдено - применить
            if parsed_author and parsed_author != "Сборник":
                record.proposed_author = parsed_author
                record.author_source = "filename"
                extracted_count += 1
        
        print(f"✅ PASS 2 завершён: {extracted_count} авторов извлечено из файлов/папок\n", flush=True)
        self.logger.log(f"[PASS 2] Извлечено {extracted_count} авторов из файлов/папок")
    
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
    
    
    def _sort_records(self) -> None:
        """Отсортировать записи: сначала отдельные файлы, потом папки (обе по алфавиту).
        
        Структура пути:
        - Отдельные файлы: "Серия - XXX\File.fb2" (1 backslash)
        - Файлы в папках: "Серия - XXX\Folder\File.fb2" (2+ backslash)
        """
        # Разделить новые и старые записи
        single_files = []  # Отдельные файлы (глубина 1)
        folder_files = []  # Файлы в папках (глубина 2+)
        
        for record in self.records:
            # Считаем количество backslash в пути
            path_parts = record.file_path.count('\\')
            
            if path_parts == 1:
                single_files.append(record)
            else:
                folder_files.append(record)
        
        # Отсортировать обе группы по file_path (алфавитный порядок)
        single_files.sort(key=lambda r: r.file_path)
        folder_files.sort(key=lambda r: r.file_path)
        
        # Объединить: сначала отдельные, потом папки
        self.records = single_files + folder_files
    
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
        
        # Использовать уже отсортированные записи (отсортировано в _sort_records())
        # Не переоопределяем сортировку!
        
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
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for record in self.records:
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
        total = len(self.records)
        by_source = {}
        for record in self.records:
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
