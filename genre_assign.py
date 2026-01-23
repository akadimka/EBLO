"""
Сервис для присвоения жанра всем FB2 файлам в папке.

Изменяет значение тега <genre> в FB2 файлах:
- Удаляет все существующие теги <genre>
- Добавляет один новый тег <genre> с выбранным жанром
- Сохраняет изменения в файл
"""

import threading
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
            # Регистрировать namespace
            ET.register_namespace('', self.FB2_NAMESPACE)
            
            # Парсить файл
            tree = ET.parse(fb2_path)
            root = tree.getroot()
            
            # Найти раздел title-info
            # Пытаемся с namespace, потом без
            ns = {'fb': self.FB2_NAMESPACE}
            title_info = root.find('.//fb:title-info', ns)
            
            if title_info is None:
                # Попробовать без namespace
                title_info = root.find('.//title-info')
            
            if title_info is None:
                return False
            
            # Найти и удалить все существующие теги <genre>
            for genre_elem in list(title_info.findall('genre')):
                title_info.remove(genre_elem)
            
            # Также попробовать с namespace
            for genre_elem in list(title_info.findall('fb:genre', ns)):
                title_info.remove(genre_elem)
            
            # Добавить новый тег <genre>
            new_genre = ET.Element('genre')
            new_genre.text = genre_name
            title_info.append(new_genre)
            
            # Сохранить файл
            tree.write(
                fb2_path,
                encoding='utf-8',
                xml_declaration=True,
                default_namespace=self.FB2_NAMESPACE
            )
            
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
