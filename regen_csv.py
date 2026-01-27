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
        
        # Сохранить CSV если путь указан
        if output_csv_path:
            self._save_csv(records, output_csv_path)
        
        if progress_callback:
            progress_callback(len(fb2_files), len(fb2_files), "Завершено")
        
        self.logger.log(f"Обработано {len(records)} файлов")
        return records
    
    def _analyze_folder_hierarchy(self, fb2_files: List[Path]) -> dict:
        """
        Анализировать иерархию папок.
        
        Определяет:
        1. Папку с разными авторами (граница парсинга)
        2. Подпапки с одинаковыми авторами (для извлечения автора из названия)
        
        Возвращает словарь для каждого файла с информацией об иерархии.
        
        Args:
            fb2_files: Список всех FB2 файлов
        
        Returns:
            Словарь {путь_к_файлу: {
                'parsing_limit': папка где остановить парсинг,
                'folder_for_pattern': папка к которой применить паттерн,
                'folder_author': автор из названия папки (если найден)
            }}
        """
        # Группируем файлы по папкам (ТОЛЬКО прямые файлы)
        files_by_folder: Dict[str, List[Path]] = {}
        for fb2_path in fb2_files:
            folder_key = str(fb2_path.parent)
            if folder_key not in files_by_folder:
                files_by_folder[folder_key] = []
            files_by_folder[folder_key].append(fb2_path)
        
        analysis = {}
        
        # Анализируем каждую папку
        for folder_path, files in files_by_folder.items():
            folder_obj = Path(folder_path)
            
            if len(files) == 1:
                # Один файл в папке - обычный анализ
                analysis[str(files[0])] = {
                    'parsing_limit': None,
                    'folder_for_pattern': folder_obj,
                    'folder_author': None
                }
                continue
            
            self.logger.log(f"[HIERARCHY] Анализируем {folder_obj.name}: {len(files)} файлов")
            
            # ПЕРВЫЙ ЭТАП: Попытаться извлечь автора из названия папки
            folder_author = self._extract_author_from_folder_name(folder_obj.name)
            
            if folder_author:
                # Автор найден в названии папки - используем как author_dataset для всех файлов
                self.logger.log(f"[HIERARCHY] Найден автор в названии папки: '{folder_author}'")
                
                # Проверяем мета только для подтверждения (fuzzy matching)
                all_files_ok = True
                for fb2_path in files:
                    if self.blacklist and fb2_path.name in self.blacklist:
                        continue
                    
                    try:
                        author_meta, _, _ = self._extract_fb2_metadata(fb2_path)
                        # Проверяем похожесть meta на папку (для расшифровки сокращений)
                        if author_meta and not self.extractor._verify_author_against_metadata(folder_author, author_meta):
                            self.logger.log(f"[HIERARCHY] Внимание: {fb2_path.name} - мета '{author_meta}' не похожа на папку '{folder_author}'")
                    except:
                        pass
                
                # Все файлы получают автора из папки независимо от meta
                for fb2_path in files:
                    analysis[str(fb2_path)] = {
                        'parsing_limit': None,
                        'folder_for_pattern': folder_obj,
                        'folder_author': folder_author
                    }
            else:
                # Автора нет в названии папки - анализируем meta для определения границы
                self.logger.log(f"[HIERARCHY] Нет автора в названии папки - анализируем meta")
                
                # Проверяем авторов в метаданных
                authors_in_folder = {}
                for fb2_path in files:
                    try:
                        # Пропускаем BL
                        if self.blacklist and fb2_path.name in self.blacklist:
                            continue
                        
                        author_meta, _, _ = self._extract_fb2_metadata(fb2_path)
                        if author_meta not in authors_in_folder:
                            authors_in_folder[author_meta] = []
                        authors_in_folder[author_meta].append(fb2_path)
                    except Exception as e:
                        key = f"ERROR_{fb2_path.name}"
                        if key not in authors_in_folder:
                            authors_in_folder[key] = []
                        authors_in_folder[key].append(fb2_path)
                
                # Если авторы РАЗНЫЕ в этой папке - она граница парсинга
                if len(authors_in_folder) > 1:
                    self.logger.log(f"[HIERARCHY] Разные авторы в {folder_obj.name} - папка является границей парсинга")
                    for fb2_path in files:
                        analysis[str(fb2_path)] = {
                            'parsing_limit': folder_obj,
                            'folder_for_pattern': folder_obj,
                            'folder_author': None
                        }
                else:
                    # Авторы одинаковые
                    self.logger.log(f"[HIERARCHY] Одинаковые авторы в {folder_obj.name}")
                    for fb2_path in files:
                        analysis[str(fb2_path)] = {
                            'parsing_limit': None,
                            'folder_for_pattern': folder_obj,
                            'folder_author': None
                        }
        
        return analysis
    
    def _extract_author_from_folder_name(self, folder_name: str) -> Optional[str]:
        """
        Попытаться извлечь автора из названия папки.
        
        Поддерживаемые форматы:
        - "Series (Author)" → "Author"
        - "Series - (Author)" → "Author"  
        - "(Author)" → "Author"
        - "Number. Title (Author)" → "Author"
        
        Args:
            folder_name: Название папки
        
        Returns:
            Имя автора или None
        """
        import re
        
        # Ищем паттерн "(Author)" в конце
        match = re.search(r'\(([^)]+)\)\s*$', folder_name)
        if not match:
            return None
        
        author_raw = match.group(1).strip()
        
        # Проверяем что это выглядит как имя автора (не путаем с серией типа "1941")
        # Имя должно содержать буквы
        if not any(c.isalpha() for c in author_raw):
            return None
        
        return author_raw
    
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
        parsing_limit = file_info.get('parsing_limit')
        folder_author = file_info.get('folder_author')
        
        # Если найден автор в названии папки - используем его как author_dataset
        proposed_author = None
        author_source = None
        
        if folder_author:
            # Нормализуем автора из названия папки
            author_normalized = self.extractor._normalize_author_format(folder_author)
            if author_normalized:
                proposed_author = author_normalized
                author_source = 'folder_dataset'
                self.logger.log(f"[REGEN]   Автор из папки (dataset): '{proposed_author}'")
        
        # Если автор не найден в папке - используем приоритет
        if not proposed_author:
            proposed_author, author_source = self.extractor.resolve_author_by_priority(
                str(fb2_path),
                parsing_folder_limit=parsing_limit
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
        author_count = len([a.strip() for a in metadata_authors.split(';') if a.strip()])
        is_anthology = self.extractor.is_anthology(filename, author_count)
        
        if is_anthology:
            # Это сборник - переопределить proposed_author
            proposed_author = "Сборник"
            author_source = "metadata"  # Источник - метаданные (множество авторов)
            self.logger.log(f"[REGEN]   Обнаружен сборник ({author_count} авторов)")
        
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
            
            return authors_str, title or "", genre or ""
        
        except Exception as e:
            self.logger.log(f"ОШИБКА при парсинге FB2 метаданных {fb2_path}: {str(e)}")
            return "", "", ""
    
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





