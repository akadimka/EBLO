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
        
        records = []
        
        for idx, fb2_path in enumerate(fb2_files):
            if progress_callback:
                progress_callback(idx, len(fb2_files), f"Обработка: {fb2_path.name}")
            
            try:
                record = self._process_fb2_file(fb2_path)
                records.append(record)
            except Exception as e:
                self.logger.log(f"Ошибка обработки {fb2_path}: {str(e)}")
                # Добавить запись об ошибке
                records.append(BookRecord(
                    file_path=str(fb2_path),
                    metadata_authors="ERROR",
                    proposed_author="ERROR"
                ))
        
        # Сохранить CSV если путь указан
        if output_csv_path:
            self._save_csv(records, output_csv_path)
        
        if progress_callback:
            progress_callback(len(fb2_files), len(fb2_files), "Завершено")
        
        self.logger.log(f"Обработано {len(records)} файлов")
        return records
    
    def _process_fb2_file(self, fb2_path: Path) -> BookRecord:
        """
        Обработать один FB2 файл и вернуть BookRecord.
        
        Args:
            fb2_path: Путь к FB2 файлу
        
        Returns:
            BookRecord с информацией из файла
        """
        # Получить имя файла без расширения и пути
        filename = fb2_path.stem
        self.logger.log(f"[REGEN] Обработка файла: {fb2_path.name}")
        
        # Извлечь автора по приоритетам источников (folder → filename → metadata)
        proposed_author, author_source = self.extractor.resolve_author_by_priority(str(fb2_path))
        if proposed_author:
            self.logger.log(f"[REGEN]   Автор по приоритетам: '{proposed_author}' (источник: {author_source})")
        else:
            self.logger.log(f"[REGEN]   Автор не найден ни из одного источника")
        
        # TODO: Добавить извлечение серии когда будет готово
        # series_result = self.series_processor.extract_series_combined(filename, str(fb2_path))
        
        # Извлечь метаданные из FB2: авторов, название, жанр
        metadata_authors, book_title, metadata_genre = self._extract_fb2_metadata(fb2_path)
        self.logger.log(f"[REGEN]   Метаданные FB2: авторы='{metadata_authors}', название='{book_title}', жанр='{metadata_genre}'")
        
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
        
        Args:
            fb2_path: Путь к FB2 файлу
        
        Returns:
            (authors_str, title, genre) - метаданные из файла
        """
        try:
            # Прочитаем файл как текст и используем регулярные выражения
            # чтобы обойти проблемы с undefined namespace prefixes
            with open(fb2_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Извлечем title-info section используя регулярные выражения
            import re
            
            # Найти всех авторов в title-info
            authors_list = []
            author_pattern = r'<author>.*?</author>'
            for author_match in re.finditer(author_pattern, content, re.DOTALL):
                author_text = author_match.group(0)
                
                # Извлечь первое имя
                first_name_match = re.search(r'<first-name>(.*?)</first-name>', author_text)
                first_name = first_name_match.group(1) if first_name_match else ''
                
                # Извлечь фамилию
                last_name_match = re.search(r'<last-name>(.*?)</last-name>', author_text)
                last_name = last_name_match.group(1) if last_name_match else ''
                
                # Извлечь nickname
                nickname_match = re.search(r'<nickname>(.*?)</nickname>', author_text)
                nickname = nickname_match.group(1) if nickname_match else ''
                
                # Составить имя автора
                if nickname:
                    authors_list.append(nickname)
                elif first_name or last_name:
                    author_name = f"{first_name} {last_name}".strip()
                    if author_name:
                        authors_list.append(author_name)
            
            # Найти название книги
            title_match = re.search(r'<book-title>(.*?)</book-title>', content)
            title = title_match.group(1) if title_match else ""
            
            # Найти жанр
            genre_match = re.search(r'<genre>(.*?)</genre>', content)
            genre = genre_match.group(1) if genre_match else ""
            
            authors_str = "; ".join(authors_list) if authors_list else ""
            
            self.logger.log(f"[REGEN]   Найдено авторов: {len(authors_list)}")
            self.logger.log(f"[REGEN]   Название: {title if title else '(пусто)'}")
            self.logger.log(f"[REGEN]   Жанр: {genre if genre else '(пусто)'}")
            self.logger.log(f"[REGEN]   Авторы: {authors_str if authors_str else '(пусто)'}")
            
            return authors_str, title or "", genre or ""
        
        except Exception as e:
            self.logger.log(f"ОШИБКА при парсинге FB2 метаданных {fb2_path}: {str(e)}")
            return "", "", ""
    
    def _save_csv(self, records: List[BookRecord], output_path: str):
        """
        Сохранить записи в CSV файл.
        
        Args:
            records: Список BookRecord
            output_path: Путь для сохранения CSV
        """
        try:
            import csv
            with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
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
    
    # Всегда использовать текущую рабочую папку
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





