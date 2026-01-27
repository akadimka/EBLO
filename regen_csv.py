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
        
        Определяет для каждого файла:
        1. Папку с разными авторами (граница парсинга)
        2. Автор из названия папки (если есть)
        
        Логика:
        - Если родитель файла или его предки содержат автора в названии → folder_author
        - Если родитель или его предки содержат файлы/подпапки с РАЗНЫМИ авторами → parsing_limit
        - Важно: анализируем ВСЕ файлы в папке (включая подпапки) для определения границы парсинга
        
        Args:
            fb2_files: Список всех FB2 файлов
        
        Returns:
            Словарь {путь_к_файлу: {
                'parsing_limit': папка где остановить парсинг,
                'folder_author': автор из названия папки (если найден)
            }}
        """
        analysis = {}
        
        # Кэш: какие папки уже проанализированы
        folder_analysis_cache: Dict[str, Dict] = {}
        
        for fb2_path in fb2_files:
            # Для каждого файла, идем вверх по иерархии и анализируем каждую папку
            current_folder = fb2_path.parent
            folder_author = None
            parsing_limit = None
            levels_checked = 0
            
            while levels_checked < 3 and current_folder.parent != current_folder:
                folder_path_str = str(current_folder)
                
                # Проверяем кэш
                if folder_path_str not in folder_analysis_cache:
                    # Проверяем название папки на наличие автора
                    extracted_author = self._extract_author_from_folder_name(current_folder.name)
                    
                    # Проверяем, есть ли в этой папке файлы/подпапки с РАЗНЫМИ авторами
                    has_multiple_authors = False
                    if not extracted_author:  # Только если папка сама по себе не имеет автора
                        # Найти ВСЕ файлы в этой папке (включая подпапки)
                        all_files_in_folder = list(current_folder.rglob('*.fb2')) + list(current_folder.rglob('*.FBZ'))
                        
                        if all_files_in_folder:
                            authors_set = set()
                            for f in all_files_in_folder:
                                try:
                                    if self.blacklist and f.name in self.blacklist:
                                        continue
                                    author, _, _ = self._extract_fb2_metadata(f)
                                    authors_set.add(author)
                                except Exception:
                                    authors_set.add(f"ERROR_{f.name}")
                            
                            has_multiple_authors = len(authors_set) > 1
                    
                    # Сохранили в кэш
                    folder_analysis_cache[folder_path_str] = {
                        'folder_author': extracted_author,
                        'has_multiple_authors': has_multiple_authors
                    }
                
                cache_entry = folder_analysis_cache[folder_path_str]
                
                # Если нашли папку с автором - запомним
                if cache_entry['folder_author'] and not folder_author:
                    folder_author = cache_entry['folder_author']
                
                # Если нашли папку с РАЗНЫМИ авторами - это граница парсинга
                if cache_entry['has_multiple_authors'] and not parsing_limit:
                    parsing_limit = current_folder
                
                # Если нашли оба - можем остановиться
                if folder_author and parsing_limit:
                    break
                
                current_folder = current_folder.parent
                levels_checked += 1
            
            analysis[str(fb2_path)] = {
                'parsing_limit': parsing_limit,
                'folder_author': folder_author
            }
        
        return analysis
    
    def _extract_author_from_folder_name(self, folder_name: str) -> Optional[str]:
        """
        Попытаться извлечь автора(ов) из названия папки.
        
        Поддерживаемые форматы:
        - "Series (Author)" → "Author"
        - "Series (Author1, Author2)" → нормализованные оба автора
        - "Series (Author1, Author2, Author3)" → "Соавторство"
        - "Series - (Author)" → "Author"  
        - "(Author)" → "Author"
        - "Number. Title (Author)" → "Author"
        
        Args:
            folder_name: Название папки
        
        Returns:
            Имя автора(ов) или None
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
        
        # Разделяем по разделителям (запятая, "и", "плюс")
        authors_list = re.split(r',\s*|\s+и\s+|\s*\+\s*', author_raw)
        authors_list = [a.strip() for a in authors_list if a.strip()]
        
        if not authors_list:
            return None
        
        # Если 3+ авторов - возвращаем "Соавторство"
        if len(authors_list) > 2:
            self.logger.log(f"[FOLDER_AUTHOR] {folder_name}: найдено {len(authors_list)} авторов → Соавторство")
            return "Соавторство"
        
        # Если 2 автора - нормализуем каждого и объединяем
        if len(authors_list) == 2:
            normalized = []
            for author_raw_name in authors_list:
                normalized_name = self._normalize_folder_author(author_raw_name)
                if normalized_name:
                    normalized.append(normalized_name)
            
            if len(normalized) == 2:
                # Объединяем двух авторов через запятую
                result = f"{normalized[0]}, {normalized[1]}"
                self.logger.log(f"[FOLDER_AUTHOR] {folder_name}: 2 автора → {result}")
                return result
            elif len(normalized) == 1:
                # Один из двух не распознался - берем первого нормализованного
                return normalized[0]
            else:
                # Ни один не распознался
                return None
        
        # 1 автор - нормализуем
        normalized = self._normalize_folder_author(authors_list[0])
        if normalized:
            self.logger.log(f"[FOLDER_AUTHOR] {folder_name}: 1 автор → {normalized}")
        return normalized
    
    def _normalize_folder_author(self, author_raw: str) -> Optional[str]:
        """
        Нормализовать имя автора из названия папки.
        
        Принимает форматы:
        - "Александр Берг" → "Александр Берг" (полные имена)
        - "А.Михайловский" → "А.Михайловский" (инициал+фамилия, оставляем как есть)
        - "А. Михайловский" → "А. Михайловский" (инициал с пробелом, оставляем)
        - Отвергает "А" или "А Иванов" (неоднозначные инициалы)
        
        Args:
            author_raw: Сырое имя автора из папки
        
        Returns:
            Нормализованное имя или None
        """
        import re
        
        author_raw = author_raw.strip()
        if not author_raw:
            return None
        
        # Проверяем формат
        # Должно быть либо:
        # 1. Два слова с заглавными буквами (полные имена): "Александр Берг"
        # 2. Инициал + фамилия: "А.Берг" или "А. Берг" или "А.Михайловский"
        
        # Попытаемся парсить как инициал+фамилия
        match = re.match(r'^([А-Яа-яA-Za-z])[.\s]*([А-Яа-яA-Za-z]\w+)$', author_raw)
        if match:
            # Это "А.Фамилия" или "А Фамилия"
            return author_raw
        
        # Попытаемся парсить как полные имена (2+ слова)
        words = author_raw.split()
        if len(words) >= 2:
            # Все слова должны начинаться с заглавной буквы и быть хотя бы 2 символа
            # (исключаем "А", "Б" и другие одиночные буквы)
            if all(w and w[0].isupper() and len(w) >= 2 for w in words):
                return author_raw
        
        # Одиночное слово с заглавной буквой и длиной >= 2 - это может быть фамилия
        if len(words) == 1 and author_raw and author_raw[0].isupper() and len(author_raw) >= 2:
            return author_raw
        
        # Не подходит
        return None
    
    def _is_compilation(self, filename: str) -> bool:
        """
        Проверить, это ли сборник/компиляция по названию файла.
        
        Признаки сборника:
        - "Хиты" (hits)
        - "Сборник" (collection)
        - "Компиляция" (compilation)
        - "Антология" (anthology)
        - "Best of"
        - "Лучшее" (best)
        - "Подборка" (selection)
        
        Args:
            filename: Название файла без расширения
        
        Returns:
            True если это выглядит как сборник
        """
        import re
        
        filename_lower = filename.lower()
        
        # Ключевые слова, указывающие на сборник
        compilation_keywords = [
            r'\bхиты\b',
            r'\bсборник\b',
            r'\bкомпиляция\b',
            r'\bантология\b',
            r'\bподборка\b',
            r'\bбест[\s-]*оф\b',
            r'\bбest[\s-]*of\b',
            r'\bлучшее\b',
            r'\bcollection\b',
            r'\banthology\b',
        ]
        
        for pattern in compilation_keywords:
            if re.search(pattern, filename_lower):
                return True
        
        return False
    
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
            # folder_author уже нормализован в _normalize_folder_author()
            # Используем его напрямую без дополнительной нормализации
            proposed_author = folder_author
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
        
        # Проверить, это ли сборник/компиляция
        # Если "Соавторство" или источник metadata с множественными авторами и в названии есть признаки сборника
        if (proposed_author == "Соавторство" or 
            (author_source == 'metadata' and ';' in metadata_authors)) and \
           self._is_compilation(filename):
            proposed_author = "Сборник"
            self.logger.log(f"[REGEN]   Переклассифицирован как Сборник (компиляция)")
        
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
            # Прочитаем файл как текст и используем регулярные выражения
            # чтобы обойти проблемы с undefined namespace prefixes
            with open(fb2_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
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





