"""
Сервис для присвоения жанра всем FB2 файлам в папке.

Изменяет значение тега <genre> в FB2 файлах:
- Удаляет все существующие теги <genre>
- Добавляет один новый тег <genre> с выбранным жанром
- Сохраняет изменения в файл
"""

import threading
import re
from pathlib import Path
from typing import Optional, Callable, List
import xml.etree.ElementTree as ET

try:
    from logger import Logger
except ImportError:
    from .logger import Logger


class GenreAssignmentService:
    """Сервис для присвоения жанра FB2 файлам."""
    
    # Namespaces для FB2
    FB2_NAMESPACE = 'http://www.gribuser.ru/xml/fictionbook/2.0'
    
    def __init__(self, logger=None):
        """Инициализация сервиса."""
        self.logger = logger if logger is not None else Logger()
        self.processed_count = 0
    
    def assign_genre_to_folder(
        self,
        folder_path: str,
        genre_name: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        completion_callback: Optional[Callable[[int], None]] = None
    ) -> int:
        """
        Присвоить жанр всем FB2 файлам в папке (рекурсивно).
        
        Args:
            folder_path: Путь к папке с FB2 файлами
            genre_name: Название жанра для присвоения
            progress_callback: Функция для обновления прогресса
                Вызывается как: progress_callback(current, total, filename)
            completion_callback: Функция для завершения
                Вызывается как: completion_callback(count)
        
        Returns:
            Количество обработанных файлов
        """
        # Validate input
        if not folder_path or not str(folder_path).strip():
            self.logger.log("ОШИБКА: folder_path не задан или пуст!")
            return 0
        
        if not genre_name or not str(genre_name).strip():
            self.logger.log("ОШИБКА: genre_name не задан или пуст!")
            return 0
        
        # Normalize path - convert mixed slashes to backslashes on Windows
        folder_path_normalized = str(folder_path).strip().replace('/', '\\')
        
        folder = Path(folder_path_normalized)
        
        if not folder.exists():
            self.logger.log(f"Папка не найдена: {folder_path_normalized}")
            return 0
        
        # Найти все FB2 файлы (*.fb2 покрывает оба случая на Windows)
        fb2_files = list(folder.rglob('*.fb2')) + list(folder.rglob('*.FBZ'))
        
        self.logger.log(f"Найдено файлов: {len(fb2_files)}")
        
        if fb2_files:
            for fb2_file in fb2_files[:5]:  # Показать первые 5
                self.logger.log(f"  - {fb2_file.name}")
        
        if not fb2_files:
            self.logger.log(f"FB2 файлы не найдены в {folder_path}")
            return 0
        
        self.logger.log(f"Начато присвоение жанра '{genre_name}' для {len(fb2_files)} файлов")
        
        self.processed_count = 0
        
        for idx, fb2_path in enumerate(fb2_files, start=1):
            filename = fb2_path.name
            
            if progress_callback:
                progress_callback(idx, len(fb2_files), filename)
            
            try:
                if self._assign_genre_to_file(fb2_path, genre_name):
                    self.processed_count += 1
                    self.logger.log(f"  [{idx}/{len(fb2_files)}] Жанр присвоен: {filename}")
                else:
                    self.logger.log(f"  [{idx}/{len(fb2_files)}] ОШИБКА: {filename}")
            except Exception as e:
                self.logger.log(f"  [{idx}/{len(fb2_files)}] ОШИБКА при обработке {filename}: {str(e)}")
        
        self.logger.log(f"Завершено! Жанр изменен у {self.processed_count} файлов")
        
        if completion_callback:
            completion_callback(self.processed_count)
        
        return self.processed_count
    
    def _assign_genre_to_file(self, fb2_path: Path, genre_name: str) -> bool:
        """
        Присвоить жанр одному FB2 файлу.
        
        Логика:
        1. Прочитать XML
        2. Найти все теги <genre> в разделе <description>/<title-info>
        3. Удалить все найденные теги <genre>
        4. Добавить один новый тег <genre> с выбранным жанром
        5. Сохранить файл
        
        Args:
            fb2_path: Путь к FB2 файлу
            genre_name: Название жанра
        
        Returns:
            True если успешно, False при ошибке
        """
        try:
            # Сначала проверить, не ZIP ли это (FBZ или архивированный FB2)
            content = None
            
            try:
                import zipfile
                if zipfile.is_zipfile(fb2_path):
                    # Это ZIP архив
                    with zipfile.ZipFile(fb2_path, 'r') as zf:
                        # Найти XML файл внутри архива
                        xml_files = [f for f in zf.namelist() if f.endswith('.xml') or f.endswith('.fb2')]
                        if not xml_files:
                            self.logger.log(f"ОШИБКА: {fb2_path} - в архиве не найдены XML файлы")
                            return False
                        
                        # Прочитать первый XML файл
                        with zf.open(xml_files[0]) as f:
                            content = f.read().decode('utf-8-sig', errors='replace')
            except (zipfile.BadZipFile, ImportError):
                pass
            
            # Если не ZIP, читаем как обычный текстовый файл
            if content is None:
                # Попробовать разные кодировки
                for encoding in ['utf-8-sig', 'utf-8', 'cp1251', 'latin-1']:
                    try:
                        with open(fb2_path, 'r', encoding=encoding, errors='replace') as f:
                            content = f.read()
                        if content.strip().startswith('<?xml') or content.strip().startswith('<'):
                            break
                    except Exception:
                        continue
                
                if content is None:
                    self.logger.log(f"ОШИБКА: {fb2_path} - не удалось прочитать с известными кодировками")
                    return False
            
            # Проверить, что это валидный XML
            content_stripped = content.strip()
            if not content_stripped.startswith('<?xml') and not content_stripped.startswith('<'):
                self.logger.log(f"ОШИБКА: {fb2_path} - не валидный XML файл")
                return False
            
            # Парсить XML с помощью ElementTree
            try:
                root = ET.fromstring(content)
            except ET.ParseError as e:
                # Проблема может быть в пустых строках - удалим их после XML declaration
                lines = content.split('\n')
                if lines[0].startswith('<?xml'):
                    # Оставляем XML declaration и удаляем пустые строки
                    xml_decl = lines[0]
                    new_lines = [line for line in lines[1:] if line.strip()]
                    content = xml_decl + '\n' + '\n'.join(new_lines)
                    
                    try:
                        root = ET.fromstring(content)
                    except ET.ParseError as e2:
                        self.logger.log(f"ОШИБКА парсинга XML: {fb2_path} - {str(e2)}")
                        return False
                else:
                    self.logger.log(f"ОШИБКА парсинга XML: {fb2_path} - {str(e)}")
                    return False
            
            # Определяем, использует ли файл namespace
            # Проверяем по наличию {} в root tag - это признак namespace в ElementTree
            has_namespace = root.tag.startswith('{')
            
            # Поиск title-info в зависимости от наличия namespace
            if has_namespace:
                # Поиск с явным указанием namespace в синтаксисе {namespace}tag
                title_info = root.find('.//{' + self.FB2_NAMESPACE + '}title-info')
            else:
                # Для файлов без namespace
                title_info = root.find('.//title-info')
            
            if title_info is None:
                self.logger.log(f"ОШИБКА: {fb2_path} - не найден раздел <title-info>")
                return False
            
            # Удалить все существующие теги <genre>
            if has_namespace:
                genre_tags_to_remove = title_info.findall('{' + self.FB2_NAMESPACE + '}genre')
            else:
                genre_tags_to_remove = title_info.findall('genre')
            
            for genre_elem in genre_tags_to_remove:
                title_info.remove(genre_elem)
            
            # Добавить новый тег <genre>
            new_genre = ET.Element('genre')
            new_genre.text = genre_name
            title_info.append(new_genre)
            
            # Сохранить файл - самый надежный способ: заменяем жанры в оригинальном контенте
            # используя regex, чтобы не потерять namespace объявления
            has_bom = content.startswith('\ufeff')
            
            # Найти все существующие genre теги с их значениями в title-info и удалить их
            # Regex ищет <genre ...> ... </genre> с любыми атрибутами и значениями
            # Это работает независимо от namespace префиксов
            genre_pattern = r'<(?:fb:)?genre[^>]*>.*?</(?:fb:)?genre>'
            result_text = re.sub(genre_pattern, '', content, flags=re.DOTALL | re.IGNORECASE)
            
            # Найти позицию для вставки нового genre тега
            # Ищем </title-info> и вставляем перед ней
            title_info_close = re.search(r'</(?:fb:)?title-info>', result_text)
            
            if title_info_close:
                # Вставляем новый genre тег перед </title-info>
                insert_pos = title_info_close.start()
                new_genre_tag = f'<genre>{genre_name}</genre>\n  '
                result_text = result_text[:insert_pos] + new_genre_tag + result_text[insert_pos:]
            else:
                self.logger.log(f"ОШИБКА: не найден </title-info> в {fb2_path}")
                return False
            
            # Сохранить файл с правильной кодировкой
            # utf-8-sig добавит BOM если кодировка включает sig
            encoding_to_use = 'utf-8-sig' if has_bom else 'utf-8'
            with open(fb2_path, 'w', encoding=encoding_to_use, errors='replace') as f:
                f.write(result_text)
            
            return True
        
        except Exception as e:
            self.logger.log(f"Ошибка при обработке {fb2_path}: {str(e)}")
            return False


def assign_genre_threaded(
    folder_path: str,
    genre_name: str,
    progress_callback: Optional[Callable] = None,
    completion_callback: Optional[Callable] = None,
    logger: Optional[object] = None
) -> threading.Thread:
    """
    Запустить присвоение жанра в отдельном потоке.
    
    Args:
        folder_path: Путь к папке
        genre_name: Название жанра
        progress_callback: Callback для прогресса
        completion_callback: Callback для завершения
        logger: Logger instance (optional)
    
    Returns:
        Thread объект (уже запущен)
    """
    service = GenreAssignmentService(logger=logger)
    
    def worker():
        service.assign_genre_to_folder(
            folder_path,
            genre_name,
            progress_callback,
            completion_callback
        )
    
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


if __name__ == '__main__':
    service = GenreAssignmentService()
    print("GenreAssignmentService инициализирован")
