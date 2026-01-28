"""
Сервис для регенерации CSV из FB2 файлов.

Извлекает информацию об авторах, названиях книг и жанрах из FB2 файлов
и заполняет таблицу в gui_normalizer.

Структура данных соответствует столбцам Treeview в gui_normalizer:
- file_path: путь к файлу
- metadata_authors: авторы из метаданных FB2
- proposed_author: предлагаемое имя автора (после парсинга)
- author_source: источник автора (folder/filename/metadata)
- metadata_series: серия из метаданных (TODO: не реализовано)
- proposed_series: предлагаемая серия (TODO: не реализовано)
- series_source: источник серии (TODO: не реализовано)
- book_title: название книги из метаданных FB2
- metadata_genre: жанр из метаданных FB2
"""

import threading
from pathlib import Path
from typing import Optional, List, Dict, Callable, Any
import xml.etree.ElementTree as ET
import re

try:
    from fb2_author_extractor import FB2AuthorExtractor
    from settings_manager import SettingsManager
    from logger import Logger
except ImportError:
    from .fb2_author_extractor import FB2AuthorExtractor
    from .settings_manager import SettingsManager
    from .logger import Logger


class BookRecord:
    """Запись о книге для таблицы."""
    
    def __init__(
        self,
        file_path: str,
        metadata_authors: str = "",
        proposed_author: str = "",
        author_source: str = "",
        metadata_series: str = "",
        proposed_series: str = "",
        series_source: str = "",
        book_title: str = "",
        metadata_genre: str = ""
    ):
        """Инициализация записи о книге."""
        self.file_path = file_path
        self.metadata_authors = metadata_authors
        self.proposed_author = proposed_author
        self.author_source = author_source
        self.metadata_series = metadata_series
        self.proposed_series = proposed_series
        self.series_source = series_source
        self.book_title = book_title
        self.metadata_genre = metadata_genre
    
    def to_tuple(self) -> tuple:
        """Преобразовать в кортеж для вставки в Treeview."""
        return (
            self.file_path,
            self.metadata_authors,
            self.proposed_author,
            self.author_source,
            self.metadata_series,
            self.proposed_series,
            self.series_source,
            self.book_title,
            self.metadata_genre
        )
    
    def to_dict(self) -> dict:
        """Преобразовать в словарь."""
        return {
            'file_path': self.file_path,
            'metadata_authors': self.metadata_authors,
            'proposed_author': self.proposed_author,
            'author_source': self.author_source,
            'metadata_series': self.metadata_series,
            'proposed_series': self.proposed_series,
            'series_source': self.series_source,
            'book_title': self.book_title,
            'metadata_genre': self.metadata_genre
        }


class RegenCSVService:
    """Сервис для регенерации CSV из FB2 файлов."""
    
    def __init__(self, settings_path: str = None):
        """
        Инициализация сервиса.
        
        Args:
            settings_path: Путь к файлу конфигурации (если None, ищет в папке скрипта)
        """
        # Если путь не задан, ищем config.json в папке скрипта
        if settings_path is None:
            settings_path = str(Path(__file__).parent / 'config.json')
        
        self.settings = SettingsManager(settings_path)
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor(settings_path)
        self.blacklist = self.settings.get_filename_blacklist()
        self.surname_conversions = self.settings.get_author_surname_conversions()
        
        # Загрузить настройку глубины парсинга папок
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
    
    def generate_csv(
        self,
        folder_path: str,
        output_csv_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[BookRecord]:
        """
        Генерировать CSV из FB2 файлов в папке.
        
        Args:
            folder_path: Путь к папке с FB2 файлами
            output_csv_path: Путь для сохранения CSV (если None, не сохраняется)
            progress_callback: Функция для обновления UI
                Вызывается как: progress_callback(current, total, status_text)
        
        Returns:
            Список BookRecord с результатами
        """
        folder = Path(folder_path)
        
        if not folder.exists():
            self.logger.log(f"Папка не найдена: {folder_path}")
            return []
        
        # Найти все FB2 файлы
        fb2_files = list(folder.rglob('*.fb2')) + list(folder.rglob('*.FBZ'))
        
        if not fb2_files:
            self.logger.log(f"FB2 файлы не найдены в {folder_path}")
            return []
        
        self.logger.log(f"Найдено {len(fb2_files)} FB2 файлов")
        
        # PASS 1: Анализируем иерархию папок
        self.logger.log("[PASS 1] Анализ иерархии папок...")
        folder_analysis = self._analyze_folder_hierarchy(fb2_files)
        
        # PASS 2: Обрабатываем файлы с учетом иерархии
        self.logger.log("[PASS 2] Обработка файлов...")
        records = []
        
        for idx, fb2_path in enumerate(fb2_files):
            if progress_callback:
                progress_callback(idx, len(fb2_files), f"Обработка: {fb2_path.name}")
            
            try:
                record = self._process_fb2_file(fb2_path, folder_analysis)
                records.append(record)
            except Exception as e:
                self.logger.log(f"Ошибка обработки {fb2_path}: {str(e)}")
                # Добавить запись об ошибке
                records.append(BookRecord(
                    file_path=str(fb2_path),
                    metadata_authors="ERROR",
                    proposed_author="ERROR"
                ))
        
        # PASS 3: Раскрыть сокращённых авторов (А.Фамилия)
        if progress_callback:
            progress_callback(len(fb2_files), len(fb2_files), "Раскрытие аббревиатур авторов...")
        self.logger.log("[PASS 3] Раскрытие аббревиатур авторов...")
        records = self._expand_abbreviated_authors(records)
        
        # PASS 4: Применить консенсус авторов
        if progress_callback:
            progress_callback(len(fb2_files), len(fb2_files), "Применение консенсуса авторов...")
        self.logger.log("[PASS 4] Применение консенсуса авторов...")
        # records = self._apply_author_consensus(records)
        
        # Сохранить CSV если путь указан
        if output_csv_path:
            self._save_csv(records, output_csv_path)
        
        if progress_callback:
            progress_callback(len(fb2_files), len(fb2_files), "Завершено")
        
        self.logger.log(f"Обработано {len(records)} файлов")
        return records
    
    def _analyze_folder_hierarchy(self, fb2_files: List[Path]) -> dict:
        """
        Анализировать иерархию папок для извлечения автора.
        
        Алгоритм:
        1. Сгруппировать файлы по папкам АВТОРОВ (папкам на уровне автора)
        2. Для каждой группы файлов найти общую папку
        3. Проверить эту папку на паттерн (Author) и извлечь автора
        4. Все файлы в группе получают одного автора
        
        Папка автора - это первая папка вверх от файлов, имя которой похоже на имя автора
        (т.е. содержит мало слов и выглядит как "Фамилия Имя" или "Имя - Описание")
        
        Args:
            fb2_files: Список всех FB2 файлов
        
        Returns:
            Словарь {путь_к_файлу: {'folder_author': автор или None}}
        """
        analysis = {}
        
        if not fb2_files:
            return analysis
        
        # Сгруппировать файлы по папкам авторов
        author_folders = self._group_files_by_author_folder(fb2_files)
        
        self.logger.log(f"[HIERARCHY] Найдено {len(author_folders)} папок авторов")
        
        # Обработать каждую группу файлов
        for author_folder_path, group_files in author_folders.items():
            self.logger.log(f"[HIERARCHY] Группа: {author_folder_path.name} ({len(group_files)} файлов)")
            
            # Для этой группы найти общую папку
            common_folder = self._find_common_folder(group_files)
            
            if not common_folder:
                self.logger.log(f"[HIERARCHY]   Не удалось найти общую папку")
                for fb2_path in group_files:
                    analysis[str(fb2_path)] = {'folder_author': None}
                continue
            
            # Найти автора в иерархии начиная с общей папки
            # force_dataset=True: если папка явно называет автора, применить без доп. валидации
            # Это гарантирует, что ВСЕ файлы в папке получат одного автора
            folder_author = self._find_dataset_author_in_hierarchy(common_folder, force_dataset=True)
            
            if folder_author:
                self.logger.log(f"[HIERARCHY]   Найден автор: '{folder_author}'")
            else:
                self.logger.log(f"[HIERARCHY]   Автор не найден")
            
            # Все файлы в группе получают одинаковый автор
            for fb2_path in group_files:
                analysis[str(fb2_path)] = {'folder_author': folder_author}
                if folder_author:
                    self.logger.log(f"[HIERARCHY]     {fb2_path.name} -> '{folder_author}'")
        
        return analysis
    
    def _group_files_by_author_folder(self, fb2_files: List[Path]) -> dict:
        """
        Сгруппировать файлы по папкам авторов.
        
        Папка автора определяется так:
        - Идти вверх от файла к корню
        - Найти первую папку, которая выглядит как имя автора
        - Это папка с простым названием (2-4 слова) без описаний
        - Или папка с явно указанным автором в скобках: "Название (Автор)" - но только если один автор
        
        Args:
            fb2_files: Список всех FB2 файлов
        
        Returns:
            Словарь {Path папки автора: [список файлов в этой группе]}
        """
        groups = {}
        
        for fb2_path in fb2_files:
            # Идти вверх от файла к корню
            current = fb2_path.parent
            author_folder = None
            
            # Идем вверх максимум на 5 уровней
            for _ in range(5):
                parent = current.parent
                
                # Если дошли до корня или Test1, остановиться
                if current == parent or current.name == 'Test1':
                    break
                
                # Проверить является ли эта папка "папкой автора"
                folder_name = current.name
                words = folder_name.split()
                
                # Вариант 1: Папка с явно указанным одним автором: "Название (Автор)" - без запятых
                # (запятые указывают на несколько авторов - это не папка одного автора)
                if '(' in folder_name and ')' in folder_name and ',' not in folder_name:
                    # Это может быть папка автора
                    author_folder = current
                    break
                
                # Вариант 2: Папка авто - это папка с простым именем (2-4 слова, начинается с заглавной буквы)
                if 2 <= len(words) <= 4 and folder_name[0].isupper() and '(' not in folder_name:
                    # Дополнительная проверка: не содержит ли много цифр или нестандартных слов
                    digit_count = sum(1 for w in words if w.isdigit())
                    if digit_count == 0:
                        author_folder = current
                        break
                
                current = parent
            
            if author_folder:
                if author_folder not in groups:
                    groups[author_folder] = []
                groups[author_folder].append(fb2_path)
            else:
                # Если не найдена папка автора, группировать по Test1
                # (это не должно происходить в нормальной структуре)
                test1_parent = fb2_path.parent
                while test1_parent.name != 'Test1' and test1_parent != test1_parent.parent:
                    test1_parent = test1_parent.parent
                if test1_parent not in groups:
                    groups[test1_parent] = []
                groups[test1_parent].append(fb2_path)
        
        return groups
    
    def _find_common_folder(self, paths: List[Path]) -> Optional[Path]:
        """
        Найти БЛИЖАЙШУЮ общую папку для всех путей (Lowest Common Ancestor).
        Ищет от файлов ВВЕРХ, не от корня диска.
        
        Args:
            paths: Список путей файлов
        
        Returns:
            Ближайшая общая папка или None
        """
        if not paths:
            return None
        
        if len(paths) == 1:
            return paths[0].parent
        
        # Получить цепи папок от каждого файла вверх
        parent_chains = []
        for p in paths:
            chain = []
            current = p.parent
            while current != current.parent:  # До корня диска
                chain.append(current)
                current = current.parent
            parent_chains.append(chain)
        
        if not parent_chains:
            return None
        
        # Найти общую часть - начиная с ближайшей папки (начало каждой цепи)
        # Все цепи отсортированы от файла вверх к корню
        common = None
        for candidate in parent_chains[0]:  # Проверяем каждую папку первого файла
            # Проверить есть ли эта папка у всех остальных файлов
            if all(candidate in chain for chain in parent_chains):
                # Найдена общая папка - это самая близкая
                common = candidate
                break  # Первая найденная - ближайшая
        
        return common
    
    def _find_dataset_author_in_hierarchy(self, start_folder: Path, force_dataset: bool = False) -> Optional[str]:
        """
        Подняться вверх от папки и найти автора в паттерне (Author).
        
        Алгоритм:
        1. Начать с start_folder
        2. Проверить папку на паттерн (Author)
        3. Если найден → применить конвертацию для ЦЕЛОГО значения (с скобками)
        4. Проверить валидность (в all_names)
        5. Если валиден → вернуть и нормализовать
        6. Если нет → поднять на уровень выше
        7. Повторить не более folder_parse_limit раз
        
        Args:
            start_folder: Папка откуда начать поиск
            force_dataset: Если True, применить автора БЕЗ проверки валидности
        
        Returns:
            Имя автора или None
        """
        current_folder = start_folder
        depth = 0
        max_depth = self.folder_parse_limit
        
        while depth < max_depth:
            folder_name = current_folder.name
            
            # Попытаться применить точную конвертацию для ЦЕЛОГО названия папки
            author_converted = self._apply_surname_conversions(folder_name)
            
            if author_converted != folder_name:
                # Точная конвертация сработала, например "Гоблин (MeXXanik)" → "Гоблин MeXXanik"
                self.logger.log(f"[HIERARCHY] Уровень {depth}: Точная конвертация '{folder_name}' → '{author_converted}'")
                
                # Если force_dataset, применить БЕЗ проверки
                if force_dataset:
                    author_normalized = self.extractor._normalize_author_format(author_converted)
                    self.logger.log(f"[HIERARCHY] Уровень {depth}: force_dataset=True, применяем '{author_converted}' → '{author_normalized}' без проверки")
                    return author_normalized
                
                # Проверить валидность преобразованного значения
                if self._validate_author_name(author_converted):
                    # Применить нормализацию
                    author_normalized = self.extractor._normalize_author_format(author_converted)
                    self.logger.log(f"[HIERARCHY] Уровень {depth}: Валид '{author_converted}' → '{author_normalized}' (нормализация)")
                    return author_normalized
                else:
                    self.logger.log(f"[HIERARCHY] Уровень {depth}: Преобразовано но не валидно '{author_converted}' (не в all_names)")
            else:
                # Нет точной конвертации - попытаться извлечь паттерн (Author)
                author_raw = self._extract_author_from_folder_name(folder_name)
                
                if author_raw:
                    # Найден паттерн (Author) - например "MeXXanik" из "Гоблин (MeXXanik)"
                    self.logger.log(f"[HIERARCHY] Уровень {depth}: Найден паттерн '{author_raw}' из '{folder_name}'")
                    
                    # Если force_dataset, применить БЕЗ проверки
                    if force_dataset:
                        author_normalized = self.extractor._normalize_author_format(author_raw)
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: force_dataset=True, применяем паттерн '{author_raw}' → '{author_normalized}' без проверки")
                        return author_normalized
                    
                    # Проверить валидность
                    if self._validate_author_name(author_raw):
                        # Применить нормализацию
                        author_normalized = self.extractor._normalize_author_format(author_raw)
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: Валид '{author_raw}' → '{author_normalized}' (нормализация)")
                        return author_normalized
                    else:
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: Паттерн найден но не валиден '{author_raw}' (не в all_names)")
                else:
                    # Нет паттерна - проверить если это простой формат "Фамилия Имя"
                    # Попробовать использовать имя папки как есть если оно валидно
                    if self._validate_author_name(folder_name):
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: Папка '{folder_name}' валидна как имя автора")
                        
                        # Применить нормализацию
                        author_normalized = self.extractor._normalize_author_format(folder_name)
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: Нормализация '{folder_name}' → '{author_normalized}'")
                        return author_normalized
                    else:
                        self.logger.log(f"[HIERARCHY] Уровень {depth}: Папка '{folder_name}' не валидна как имя автора")
            
            # Поднять на уровень выше
            parent = current_folder.parent
            if parent == current_folder:  # Достигли корня диска
                break
            
            current_folder = parent
            depth += 1
        
        return None
        return None
    
    def _validate_author_name(self, author_name: str) -> bool:
        """
        Проверить валидность имени автора.
        
        Автор считается валидным если:
        1. Это не просто число/год
        2. Он есть в all_names (список известных авторов)
           - Может быть конвертирован через конвертацию сурнейма перед проверкой
           - Для формата "Фамилия Имя" - проверяет второе слово (имя)
        
        Args:
            author_name: Имя автора для проверки
        
        Returns:
            True если автор валиден, False иначе
        """
        # Проверить что не пустое
        if not author_name or not author_name.strip():
            return False
        
        # Проверить что содержит буквы (не только цифры/год)
        if not any(c.isalpha() for c in author_name):
            return False
        
        # Проверить в all_names
        all_names = self.extractor.all_names if hasattr(self.extractor, 'all_names') else set()
        
        # Разбить на слова (формат может быть "Фамилия Имя")
        words = author_name.split()
        
        # Для проверки берем:
        # - если 2 слова: второе слово (имя)
        # - иначе: всё значение
        check_name = words[-1] if len(words) == 2 else author_name
        check_name_lower = check_name.lower()
        
        # Проверить оригинальное имя (после преобразования в нижний регистр)
        if check_name_lower in all_names:
            return True
        
        # Нормализовать и проверить
        author_normalized = self.extractor._normalize_author_format(author_name)
        if author_normalized:
            normalized_words = author_normalized.split()
            normalized_check = normalized_words[-1] if len(normalized_words) == 2 else author_normalized
            normalized_check_lower = normalized_check.lower()
            if normalized_check_lower in all_names:
                return True
        
        # Также проверить конвертированный вариант
        if self.surname_conversions:
            author_converted = self._apply_surname_conversions(author_name)
            if author_converted != author_name:
                # Попробовать конвертированный вариант (второе слово если 2 слова)
                converted_words = author_converted.split()
                converted_check = converted_words[-1] if len(converted_words) == 2 else author_converted
                converted_check_lower = converted_check.lower()
                if converted_check_lower in all_names:
                    return True
                # Нормализовать конвертированный вариант
                author_converted_normalized = self.extractor._normalize_author_format(author_converted)
                if author_converted_normalized:
                    converted_norm_words = author_converted_normalized.split()
                    converted_norm_check = converted_norm_words[-1] if len(converted_norm_words) == 2 else author_converted_normalized
                    converted_norm_check_lower = converted_norm_check.lower()
                    if converted_norm_check_lower in all_names:
                        return True
        
        return False
    
    def _extract_author_from_folder_name(self, folder_name: str) -> Optional[str]:
        """
        Попытаться извлечь автора из названия папки.
        
        Поддерживаемые форматы (в порядке приоритета):
        1. "(Author)" - например "Гоблин (MeXXanik)" → "MeXXanik"
        2. "Author - Description" - например "Максим Шаттам - Собрание сочинений" → "Максим Шаттам"
        3. Иные случаи возвращают None
        
        Args:
            folder_name: Название папки
        
        Returns:
            Имя автора или None
        """
        import re
        
        # Приоритет 1: Ищем паттерн "(Author)" в конце
        match = re.search(r'\(([^)]+)\)\s*$', folder_name)
        if match:
            author_raw = match.group(1).strip()
            # Проверяем что это выглядит как имя автора (содержит буквы)
            if any(c.isalpha() for c in author_raw):
                return author_raw
        
        # Приоритет 2: Ищем паттерн "Author - Description" (тире с пробелами)
        # Это для случаев типа "Максим Шаттам - Собрание сочинений"
        match = re.match(r'^([^-]+?)\s*-\s*(.+)$', folder_name)
        if match:
            author_raw = match.group(1).strip()
            # Проверяем что часть ДО тире выглядит как имя автора
            # Должна содержать буквы и обычно быть относительно короткой (не длинное описание)
            words = author_raw.split()
            if len(words) <= 3 and any(c.isalpha() for c in author_raw):
                return author_raw
        
        return None
    
    def _process_fb2_file(self, fb2_path: Path, folder_analysis: dict) -> BookRecord:
        """
        Обработать один FB2 файл и вернуть BookRecord.
        
        Args:
            fb2_path: Путь к FB2 файлу
            folder_analysis: Результат анализа иерархии папок
        
        Returns:
            BookRecord с информацией из файла
        """
        # Получить имя файла без расширения и пути
        filename = fb2_path.stem
        self.logger.log(f"[REGEN] Обработка файла: {fb2_path.name}")
        
        # Получить информацию из анализа иерархии
        file_info = folder_analysis.get(str(fb2_path), {})
        folder_author = file_info.get('folder_author')
        
        # Если найден автор в иерархии папок - используем его как author_dataset
        proposed_author = None
        author_source = None
        
        if folder_author:
            proposed_author = folder_author
            author_source = 'folder_dataset'
            self.logger.log(f"[REGEN]   Автор из иерархии папок (dataset): '{proposed_author}'")
        
        # Если автор не найден в иерархии папок - используем приоритет
        if not proposed_author:
            proposed_author, author_source = self.extractor.resolve_author_by_priority(
                str(fb2_path),
                folder_parse_limit=self.folder_parse_limit
            )
            if proposed_author:
                self.logger.log(f"[REGEN]   Автор по приоритетам: '{proposed_author}' (источник: {author_source})")
            else:
                self.logger.log(f"[REGEN]   Автор не найден ни из одного источника")
        
        # TODO: Добавить извлечение серии когда будет готово
        # series_result = self.series_processor.extract_series_combined(filename, str(fb2_path))
        
        # Извлечь метаданные из FB2: авторов, название, жанр
        metadata_authors, book_title, metadata_genre = self._extract_fb2_metadata(fb2_path)
        self.logger.log(f"[REGEN]   Метаданные FB2: авторы='{metadata_authors}', название='{book_title}', жанр='{metadata_genre}'")
        
        # Проверить, является ли это сборником
        # ВАЖНО: Правило сборника НЕ применяется если:
        # 1. Автор из folder_dataset (иерархия папок)
        # 2. Автор успешно извлечен из filename (filename или folder)
        # Сборник = "Сборник" только если авторов > 2 в метаданных и нет явного автора в имени файла
        author_count = len([a.strip() for a in metadata_authors.split(';') if a.strip()])
        is_anthology = self.extractor.is_anthology(filename, author_count)
        
        # Проверить: есть ли явный автор в названии файла?
        # Если filename/folder source найден, это не истинная антология
        has_explicit_author_in_filename = author_source in ['filename', 'folder', 'folder_dataset']
        
        if is_anthology and not has_explicit_author_in_filename and author_count > 2:
            # Это истинная антология: есть маркер сборника И нет явного автора И много авторов
            proposed_author = "Сборник"
            author_source = "metadata"  # Источник - метаданные (множество авторов)
            self.logger.log(f"[REGEN]   Обнаружена истинная антология ({author_count} авторов)")
        elif is_anthology and has_explicit_author_in_filename:
            # Маркер сборника найден, НО есть явный автор - это сборник одного автора, сохранить его
            self.logger.log(f"[REGEN]   Слово 'сборник' в названии, но автор явно указан ({author_source}): '{proposed_author}'")
        
        # Применить конвертации фамилий если необходимо
        if proposed_author and proposed_author != "Сборник" and self.surname_conversions:
            original_author = proposed_author
            proposed_author = self._apply_surname_conversions(proposed_author)
            if original_author != proposed_author:
                self.logger.log(f"[REGEN]   После конвертации фамилий: '{original_author}' -> '{proposed_author}'")
        
        # Создать запись
        record = BookRecord(
            file_path=str(fb2_path),
            metadata_authors=metadata_authors,
            proposed_author=proposed_author,
            author_source=author_source,
            metadata_series="",  # TODO: Добавить
            proposed_series="",  # TODO: Добавить
            series_source="",    # TODO: Добавить
            book_title=book_title,
            metadata_genre=metadata_genre
        )
        
        return record
    
    def _extract_fb2_metadata(self, fb2_path: Path) -> tuple:
        """
        Извлечь метаданные из FB2 файла.
        
        Значения извлекаются ТОЛЬКО из тега <title-info>,
        а не из всего документа (ignoring document-info и прочие разделы).
        
        Args:
            fb2_path: Путь к FB2 файлу
        
        Returns:
            (authors_str, title, genre) - метаданные из файла
        """
        try:
            # Прочитаем файл, пытаясь разные кодировки
            content = None
            
            # Попробуем разные кодировки в порядке приоритета
            encodings_to_try = [
                ('cp1251', 'strict'),     # Русская кодировка (cp1251) - часто встречается в старых FB2
                ('utf-8', 'strict'),      # UTF-8 без ошибок
                ('cp1251', 'replace'),    # Русская кодировка с заменой
                ('utf-8', 'replace'),     # UTF-8 с заменой невалидных
                ('latin-1', 'replace'),   # Fallback - latin-1 всегда работает
            ]
            
            for encoding, errors in encodings_to_try:
                try:
                    with open(fb2_path, 'r', encoding=encoding, errors=errors) as f:
                        test_content = f.read(200)  # Прочитаем начало
                        # Проверим, есть ли XML declaration
                        if '<?xml' in test_content or '<FictionBook' in test_content:
                            # Похоже на валидный FB2, прочитаем весь файл
                            with open(fb2_path, 'r', encoding=encoding, errors=errors) as f:
                                content = f.read()
                            break
                except Exception:
                    continue
            
            if not content:
                return "", "", ""
            
            # Извлечем ТОЛЬКО title-info section
            import re
            
            # Найти весь <title-info>...</title-info> блок
            title_info_match = re.search(r'<(?:fb:)?title-info>.*?</(?:fb:)?title-info>', content, re.DOTALL)
            
            if not title_info_match:
                # Не найден title-info, вернуть пустые значения
                return "", "", ""
            
            # Работаем только с содержимым title-info
            title_info_content = title_info_match.group(0)
            
            # Найти всех авторов ВНУ­ТРИ title-info
            authors_list = []
            author_pattern = r'<author>.*?</author>'
            for author_match in re.finditer(author_pattern, title_info_content, re.DOTALL):
                author_text = author_match.group(0)
                
                # Извлечь компоненты имени
                first_name_match = re.search(r'<first-name>(.*?)</first-name>', author_text)
                first_name = first_name_match.group(1) if first_name_match else ''
                
                # Извлечь фамилию
                last_name_match = re.search(r'<last-name>(.*?)</last-name>', author_text)
                last_name = last_name_match.group(1) if last_name_match else ''
                
                # Извлечь отчество (но не используем в имени)
                middle_name_match = re.search(r'<middle-name>(.*?)</middle-name>', author_text)
                middle_name = middle_name_match.group(1) if middle_name_match else ''
                
                # Составить имя автора - используем только first-name и last-name
                # nickname игнорируется полностью
                if first_name or last_name:
                    author_name = f"{first_name} {last_name}".strip()
                    if author_name:
                        authors_list.append(author_name)
            
            # Найти название книги ТОЛЬКО в title-info
            title_match = re.search(r'<book-title>(.*?)</book-title>', title_info_content)
            title = title_match.group(1) if title_match else ""
            
            # Найти жанр ТОЛЬКО в title-info
            genre_match = re.search(r'<genre>(.*?)</genre>', title_info_content)
            genre = genre_match.group(1) if genre_match else ""
            
            authors_str = "; ".join(authors_list) if authors_list else ""
            
            self.logger.log(f"[REGEN]   Найдено авторов в title-info: {len(authors_list)}")
            self.logger.log(f"[REGEN]   Название в title-info: {title if title else '(пусто)'}")
            self.logger.log(f"[REGEN]   Жанр в title-info: {genre if genre else '(пусто)'}")
            self.logger.log(f"[REGEN]   Авторы в title-info: {authors_str if authors_str else '(пусто)'}")
            
            # Применить конвертации фамилий если необходимо
            if authors_str and self.surname_conversions:
                authors_str = self._apply_surname_conversions(authors_str)
                self.logger.log(f"[REGEN]   После конвертации фамилий: {authors_str}")
            
            return authors_str, title or "", genre or ""
        
        except Exception as e:
            self.logger.log(f"ОШИБКА при парсинге FB2 метаданных {fb2_path}: {str(e)}")
            return "", "", ""
    
    def _apply_surname_conversions(self, authors_str: str) -> str:
        """
        Применить конвертации фамилий к строке авторов.
        
        Приоритет:
        1. Точное совпадение целой строки (например "Гоблин (MeXXanik)" -> "Гоблин MeXXanik")
        2. Затем разбор по авторам и поиск фамилий для конвертации
        
        Args:
            authors_str: Строка авторов в формате "Имя Фамилия; Имя2 Фамилия2"
        
        Returns:
            Строка авторов с применёнными конвертациями фамилий
        """
        if not authors_str or not self.surname_conversions:
            return authors_str
        
        # ПРИОРИТЕТ 1: Проверить точное совпадение целой строки
        if authors_str in self.surname_conversions:
            return self.surname_conversions[authors_str]
        
        # ПРИОРИТЕТ 2: Разделить авторов и искать фамилии
        authors = authors_str.split(';')
        converted_authors = []
        
        for author in authors:
            author = author.strip()
            if not author:
                continue
            
            # Попытаться найти фамилию для конвертации
            # Предполагаем формат "Имя Фамилия" или "Фамилия Имя"
            parts = author.split()
            if len(parts) >= 2:
                # Проверить оба варианта: первый и последний элемент могут быть фамилией
                # Сначала проверим последний элемент (обычно фамилия в "Имя Фамилия")
                potential_surname_last = parts[-1]
                # Потом проверим первый элемент (может быть фамилия в "Фамилия Имя")
                potential_surname_first = parts[0]
                
                converted = False
                
                # Проверить последний элемент
                if potential_surname_last in self.surname_conversions:
                    converted_surname = self.surname_conversions[potential_surname_last]
                    converted_author = ' '.join(parts[:-1] + [converted_surname])
                    converted_authors.append(converted_author)
                    converted = True
                # Проверить первый элемент
                elif potential_surname_first in self.surname_conversions:
                    converted_surname = self.surname_conversions[potential_surname_first]
                    converted_author = ' '.join([converted_surname] + parts[1:])
                    converted_authors.append(converted_author)
                    converted = True
                
                if not converted:
                    converted_authors.append(author)
            else:
                # Если только одно слово, проверим его как фамилию
                if author in self.surname_conversions:
                    converted_authors.append(self.surname_conversions[author])
                else:
                    converted_authors.append(author)
        
        return "; ".join(converted_authors)
    
    def _build_authors_map(self, records: List[BookRecord]) -> Dict[str, str]:
        """
        Построить словарь фамилия -> полное имя из всех предложенных авторов.
        
        Args:
            records: Список BookRecord
        
        Returns:
            Словарь {фамилия.lower(): полное_имя}
        """
        authors_map = {}
        
        for record in records:
            if not record.proposed_author or record.proposed_author == "Соавторство":
                continue
            
            # Парсить полные имена (не аббревиатуры)
            if '.' in record.proposed_author:
                # Пропустить аббревиатуры типа "А.Фамилия"
                continue
            
            # Для каждого автора из proposed_author
            for author_part in record.proposed_author.split(','):
                author_part = author_part.strip()
                if not author_part:
                    continue
                
                # Парсить "Фамилия Имя"
                parts = author_part.split()
                if len(parts) >= 2:
                    surname = parts[0].lower()
                    # Сохранить полное имя
                    authors_map[surname] = author_part
        
        # Также собрать из metadata_authors (формат "Имя Фамилия")
        for record in records:
            if not record.metadata_authors:
                continue
            
            for author_part in record.metadata_authors.split(';'):
                author_part = author_part.strip()
                if not author_part or '.' in author_part:
                    continue
                
                # Парсить "Имя Фамилия" и преобразовать в "Фамилия Имя"
                parts = author_part.split()
                if len(parts) >= 2:
                    # В metadata_authors: Имя Фамилия
                    # Преобразовать в: Фамилия Имя
                    first_name = parts[0]
                    surname = parts[-1]
                    
                    surname_lower = surname.lower()
                    
                    # Если фамилия уже есть, не перезаписываем (proposed_author имеет приоритет)
                    if surname_lower not in authors_map:
                        # Попробовать собрать как "Фамилия Имя"
                        full_name = f"{surname} {first_name}"
                        authors_map[surname_lower] = full_name
        
        self.logger.log(f"Построен словарь из {len(authors_map)} авторов: {list(authors_map.keys())[:5]}...")
        return authors_map
    
    def _expand_abbreviated_authors(self, records: List[BookRecord]) -> List[BookRecord]:
        """
        Раскрыть сокращённых авторов типа "А.Фамилия" до полных имён.
        
        Стратегия:
        1. Собрать словарь полных имён из proposed_author и metadata_authors
        2. Для каждого сокращённого автора поискать в словаре
        3. Заменить на полное имя если найдено
        
        Args:
            records: Список BookRecord
        
        Returns:
            Обновленный список с раскрытыми авторами
        """
        # Построить словарь полных имён
        authors_map = self._build_authors_map(records)
        
        if not authors_map:
            self.logger.log("Словарь полных имён пуст, раскрытие невозможно")
            return records
        
        self.logger.log(f"Построен словарь из {len(authors_map)} авторов для раскрытия")
        
        # Раскрыть аббревиатуры в каждой записи
        expanded_count = 0
        for record in records:
            if not record.proposed_author or ',' not in record.proposed_author:
                continue
            
            # Проверить содержит ли вообще аббревиатуры
            if '.' not in record.proposed_author:
                continue
            
            # Раскрыть каждого автора в списке
            authors_list = record.proposed_author.split(',')
            expanded_authors = []
            
            for author in authors_list:
                author = author.strip()
                
                # Если это аббревиатура (содержит точку), раскрыть
                if '.' in author:
                    expanded = self.extractor.expand_abbreviated_author(author, authors_map)
                    if expanded != author:
                        expanded_count += 1
                    expanded_authors.append(expanded)
                else:
                    expanded_authors.append(author)
            
            # Обновить proposed_author
            record.proposed_author = ", ".join(expanded_authors)
        
        self.logger.log(f"Раскрыто аббревиатур: {expanded_count}")
        return records
    
    def _apply_author_consensus(self, records: List[BookRecord]) -> List[BookRecord]:
        """
        Применить консенсус при расхождениях авторов.
        
        Для каждой группы записей с одинаковыми metadata_authors:
        1. Подсчитать количество вхождений каждого proposed_author
        2. Выбрать наиболее частый вариант (консенсус)
        3. Если author отличался от консенсуса - добавить суффикс "_cons" к source
        4. Если author уже совпадал - оставить source без изменений
        
        Args:
            records: Список BookRecord
        
        Returns:
            Обновленный список с применённым консенсусом
        """
        # Группировать по metadata_authors
        groups = {}
        for record in records:
            key = record.metadata_authors
            if key not in groups:
                groups[key] = []
            groups[key].append(record)
        
        consensus_count = 0
        
        # Для каждой группы найти консенсус
        for metadata_key, group_records in groups.items():
            if not metadata_key or len(group_records) == 1:
                # Пропустить единичные записи или пустые metadata
                continue
            
            # ВАЖНО: folder_dataset имеет приоритет над консенсусом
            # Если хотя бы один файл получил автора из folder_dataset, консенсус не применяется
            # Разделить файлы на две группы: с folder_dataset и без
            folder_dataset_records = [r for r in group_records if r.author_source.startswith("folder_dataset")]
            non_folder_records = [r for r in group_records if not r.author_source.startswith("folder_dataset")]
            
            # Определить консенсус:
            # 1. Если есть folder_dataset - используем его автора (folder_dataset имеет приоритет)
            # 2. Иначе - ищем консенсус среди остальных файлов
            
            if folder_dataset_records:
                # Есть folder_dataset - его автор есть консенсус для всей группы
                # Используем автора с наибольшей частотой в folder_dataset
                folder_authors = {}
                for record in folder_dataset_records:
                    author = record.proposed_author or ""
                    folder_authors[author] = folder_authors.get(author, 0) + 1
                
                consensus_author = max(folder_authors.items(), key=lambda x: x[1])[0]
                self.logger.log(f"[CONSENSUS] metadata='{metadata_key}': используем автора из folder_dataset: '{consensus_author}'")
                
                # Применить consensus ко всем файлам БЕЗ folder_dataset
                for record in non_folder_records:
                    if record.proposed_author != consensus_author:
                        old_author = record.proposed_author
                        record.author_source = f"{record.author_source}_cons"
                        record.proposed_author = consensus_author
                        self.logger.log(f"  [CHANGED] '{old_author}' -> '{consensus_author}' (source: {record.author_source})")
                        consensus_count += 1
            else:
                # Нет folder_dataset - ищем консенсус среди остальных
                if len(non_folder_records) <= 1:
                    # Только один файл или нет файлов - консенсус не нужен
                    continue
                
                # Подсчитать вхождения proposed_author в группе
                author_counts = {}
                for record in non_folder_records:
                    author = record.proposed_author or ""
                    if author not in author_counts:
                        author_counts[author] = 0
                    author_counts[author] += 1
                
                if len(author_counts) <= 1:
                    # Все авторы одинаковые - консенсус уже достигнут
                    self.logger.log(f"[CONSENSUS] metadata='{metadata_key}': все файлы имеют одинакового автора ({author_counts}) - пропускаем")
                    continue
                
                # Найти наиболее частый вариант (консенсус)
                consensus_author = max(author_counts.items(), key=lambda x: x[1])[0]
                consensus_count_value = author_counts[consensus_author]
                
                # Вычислить процент согласия
                total_non_folder = len(non_folder_records)
                agreement_percent = (consensus_count_value / total_non_folder) * 100
                
                self.logger.log(f"[CONSENSUS] metadata='{metadata_key}': {author_counts} -> consensus='{consensus_author}' ({consensus_count_value}/{total_non_folder}, {agreement_percent:.0f}%)")
                
                # Применить консенсус к файлам, которые отличаются от консенсуса
                for record in non_folder_records:
                    if record.proposed_author != consensus_author:
                        # Автор отличался от консенсуса - добавить суффикс
                        old_author = record.proposed_author
                        record.author_source = f"{record.author_source}_cons"
                        record.proposed_author = consensus_author
                        self.logger.log(f"  [CHANGED] '{old_author}' -> '{consensus_author}' (source: {record.author_source})")
                        consensus_count += 1
                    # Если совпадает - НИЧ ЕГО не меняем (ни автора, ни source)
        
        self.logger.log(f"Применен консенсус: {consensus_count} записей исправлено")
        return records
    
    def _save_csv(self, records: List[BookRecord], output_path: str):
        """
        Сохранить записи в CSV файл.
        
        Args:
            records: Список BookRecord
            output_path: Путь для сохранения CSV
        """
        try:
            import csv
            # Используем UTF-8 без BOM для совместимости
            with open(output_path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f)
                
                # Заголовки
                headers = [
                    'file_path', 'metadata_authors', 'proposed_author', 'author_source',
                    'metadata_series', 'proposed_series', 'series_source',
                    'book_title', 'metadata_genre'
                ]
                writer.writerow(headers)
                
                # Строки данных
                for record in records:
                    writer.writerow(record.to_tuple())
            
            self.logger.log(f"CSV сохранен в {output_path}")
        except Exception as e:
            self.logger.log(f"Ошибка при сохранении CSV: {str(e)}")
    
    def reload_config(self):
        """Перезагрузить конфигурацию."""
        self.settings.load()
        self.blacklist = self.settings.get_filename_blacklist()
        self.extractor.reload_config()


# Для тестирования
if __name__ == '__main__':
    from pathlib import Path
    
    service = RegenCSVService()
    
    # Использовать last_scan_path из конфига
    library_path = service.settings.get_last_scan_path()
    if not library_path:
        library_path = str(Path.cwd())
    
    generate_csv = service.settings.get_generate_csv()
    
    # Определить путь сохранения CSV
    output_csv_path = None
    if generate_csv:
        output_csv_path = str(Path(__file__).parent / 'regen.csv')
    
    # Запустить генерацию
    import sys
    import io
    # Установить правильную кодировку для вывода
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    print(f"Начало генерации CSV (папка: {library_path})...")
    
    def progress_callback(current, total, status):
        print(f"Прогресс: {current}/{total} - {status}")
    
    records = service.generate_csv(
        library_path,
        output_csv_path=output_csv_path,
        progress_callback=progress_callback
    )
    
    print(f"Генерация завершена: {len(records)} записей обработано")
    if output_csv_path:
        print(f"CSV файл сохранён: {output_csv_path}")
    else:
        print("CSV файл не был сохранён (опция отключена)")





