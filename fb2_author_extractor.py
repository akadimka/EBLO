"""
Модуль для парсинга FB2 файлов и извлечения информации об авторах.

Реализует многоуровневую стратегию извлечения авторов:
1. Структура папок (FOLDER_STRUCTURE)
2. Название файла (FILENAME)
3. Метаданные FB2 (FB2_METADATA)

Использует приоритезацию из extraction_constants.AuthorExtractionPriority
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

try:
    from author_processor import AuthorProcessor
    from extraction_constants import (
        AuthorExtractionPriority,
        ConfidenceLevel,
        FilterReason,
        ExtractionResult
    )
    from settings_manager import SettingsManager
except ImportError:
    from .author_processor import AuthorProcessor
    from .extraction_constants import (
        AuthorExtractionPriority,
        ConfidenceLevel,
        FilterReason,
        ExtractionResult
    )
    from .settings_manager import SettingsManager


class FB2AuthorExtractor:
    """Извлечение информации об авторах из FB2 файлов."""
    
    def __init__(self, config_path: str = 'config.json'):
        """
        Инициализация экстрактора авторов FB2.
        
        Args:
            config_path: Путь к файлу конфигурации
        """
        self.settings = SettingsManager(config_path)
        self.author_processor = AuthorProcessor(config_path)
        
        # Загрузить списки имен для определения порядка слов
        self.male_names = set(name.lower() for name in self.settings.get_male_names())
        self.female_names = set(name.lower() for name in self.settings.get_female_names())
        self.all_names = self.male_names | self.female_names
    
    def resolve_author_by_priority(
        self,
        fb2_filepath: str
    ) -> Tuple[str, str]:
        """
        Простой метод для получения автора по приоритетам источников.
        
        Приоритет извлечения:
        1. Структура папок (FOLDER_STRUCTURE) - priority 1, проверяется через метаданные
        2. Название файла (FILENAME) - priority 2, проверяется через метаданные
        3. Метаданные FB2 (FB2_METADATA) - priority 3, источник истины
        
        Для источников 1 и 2 используется fuzzy matching для верификации:
        - Кандидат сравнивается с авторами из метаданных
        - Если похожесть > 70%, принимается
        - Если не похож ни на кого в метаданных, отклоняется
        
        Правило множественных авторов:
        - Если авторов <= 2: берем имена
        - Если авторов > 2: возвращаем "Соавторство"
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            (author_name, source) где source in ['folder', 'filename', 'metadata', '']
            Если ничего не найдено, возвращает ('', '')
        """
        try:
            fb2_path = Path(fb2_filepath)
            
            # Получить авторов из метаданных один раз (источник истины)
            metadata_author = self._extract_author_from_metadata(fb2_path)
            
            # 1. Попытка получить автора из структуры папок
            try:
                author = self._extract_author_from_folder_structure(fb2_path)
                if author and self._verify_author_against_metadata(author, metadata_author):
                    author = self._normalize_author_count(author)
                    author = self._normalize_author_format(author)
                    if author:
                        return author, 'folder'
            except Exception as e:
                pass  # Продолжаем к следующему источнику
            
            # 2. Попытка получить автора из имени файла
            try:
                author = self._extract_author_from_filename(fb2_path)
                if author and self._verify_author_against_metadata(author, metadata_author):
                    author = self._normalize_author_count(author)
                    author = self._normalize_author_format(author)
                    if author:
                        return author, 'filename'
            except Exception as e:
                pass  # Продолжаем к следующему источнику
            
            # 3. Вернуть автора из метаданных (источник истины)
            if metadata_author:
                metadata_author = self._normalize_author_count(metadata_author)
                metadata_author = self._normalize_author_format(metadata_author)
                if metadata_author:
                    return metadata_author, 'metadata'
            
            # Ничего не найдено
            return '', ''
        except Exception as e:
            return '', ''
    
    def _normalize_author_format(self, author_string: str) -> str:
        """
        Нормализовать формат автора/авторов.
        
        Правила:
        1. Если "Соавторство", оставить как есть
        2. Если один автор, нормализовать в формат "Фамилия Имя"
        3. Если два автора, нормализовать каждого и отсортировать по алфавиту
        
        Нормализация ФИ:
        - Взять максимум 2 слова (игнорировать отчество и прочее)
        - Между ними только один пробел
        - Дефис допускается в составных именах/фамилиях
        
        Args:
            author_string: Строка с одним или несколькими авторами
        
        Returns:
            Нормализованная строка
        """
        if not author_string or author_string == "Соавторство":
            return author_string
        
        try:
            # Проверить есть ли несколько авторов (разделены ; или ,)
            authors_list = []
            separator = None
            
            if ';' in author_string:
                separator = ';'
                authors_list = [a.strip() for a in author_string.split(';') if a.strip()]
            elif ',' in author_string:
                separator = ','
                authors_list = [a.strip() for a in author_string.split(',') if a.strip()]
            
            if not authors_list:
                # Нет разделителей - один автор
                authors_list = [author_string.strip()]
            
            # Нормализовать каждого автора
            normalized_authors = []
            for author in authors_list:
                normalized = self._normalize_single_author(author)
                if normalized and normalized != "Соавторство":
                    normalized_authors.append(normalized)
                elif normalized == "Соавторство":
                    return "Соавторство"
            
            if not normalized_authors:
                return ""
            
            # Если авторов > 2 после нормализации
            if len(normalized_authors) > 2:
                return "Соавторство"
            
            # Отсортировать по алфавиту
            normalized_authors.sort()
            
            # Объединить запятой для нескольких авторов
            if len(normalized_authors) > 1:
                return ", ".join(normalized_authors)
            else:
                return normalized_authors[0]
        
        except Exception:
            return author_string
    
    def _normalize_single_author(self, author_name: str) -> str:
        """
        Нормализовать одного автора в формат "Фамилия Имя".
        
        Правила:
        - Результат должен быть ровно 2 слова (Фамилия Имя)
        - Каждое слово должно начинаться с большой буквы
        - Между словами только один пробел
        - Допускаются дефисы в составных именах/фамилиях
        - Порядок определяется по списку имен: если одно из слов есть в списке - оно Имя, другое - Фамилия
        
        Args:
            author_name: Имя автора (может быть в разных форматах)
        
        Returns:
            Нормализованное имя вида "Фамилия Имя" или пустая строка
        """
        if not author_name or author_name == "Соавторство":
            return author_name
        
        try:
            # Убрать лишние пробелы
            author_name = " ".join(author_name.split())
            
            # Разбить на слова
            words = author_name.split()
            
            # Нужно ровно 2 слова
            if len(words) != 2:
                return ""
            
            # Проверить что каждое слово корректное
            cleaned_words = []
            for word in words:
                # Отбросить цифры и специальные символы в конце
                # Оставить только буквы, дефисы
                clean_word = ""
                for char in word:
                    if char.isalpha() or char == '-':
                        clean_word += char
                    else:
                        break  # Остановиться при первом некорректном символе
                
                if not clean_word:
                    return ""  # Слово не содержит букв - отбросить
                
                # Проверить что начинается с большой буквы
                if not clean_word[0].isupper():
                    return ""
                
                cleaned_words.append(clean_word)
            
            if len(cleaned_words) != 2:
                return ""
            
            # Определить порядок слов на основе списка имен
            word1_lower = cleaned_words[0].lower()
            word2_lower = cleaned_words[1].lower()
            
            word1_is_name = word1_lower in self.all_names
            word2_is_name = word2_lower in self.all_names
            
            # Если оба или ни один не в списке имен - оставить как есть
            if word1_is_name and not word2_is_name:
                # Первое слово - имя, второе - фамилия
                # Нужно переставить: фамилия имя
                return f"{cleaned_words[1]} {cleaned_words[0]}"
            elif not word1_is_name and word2_is_name:
                # Первое слово - фамилия, второе - имя (уже правильный порядок)
                return f"{cleaned_words[0]} {cleaned_words[1]}"
            else:
                # Оба в списке имен или оба не в списке - оставить как есть
                return f"{cleaned_words[0]} {cleaned_words[1]}"
        
        except Exception:
            return ""
    
    def _normalize_author_count(self, author_string: str) -> str:
        """
        Нормализовать количество авторов и формат.
        
        Правило:
        - Если авторов <= 2: нормализует формат и возвращает
        - Если авторов > 2: возвращает "Соавторство"
        
        Авторы разделены символом ';' или ','
        
        Args:
            author_string: Строка с одним или несколькими авторами
        
        Returns:
            Нормализованная строка или "Соавторство"
        """
        if not author_string:
            return ""
        
        try:
            # Разбить авторов по разделителям
            authors = []
            for sep in [';', ',']:
                if sep in author_string:
                    authors = [a.strip() for a in author_string.split(sep) if a.strip()]
                    break
            
            # Если разделителей не найдено - это один автор
            if not authors:
                authors = [author_string.strip()]
            
            # Если авторов > 2, то "Соавторство"
            if len(authors) > 2:
                return "Соавторство"
            
            # Нормализовать формат и вернуть
            return self._normalize_author_format(author_string)
        
        except Exception:
            return author_string
    
    def _verify_author_against_metadata(
        self, 
        candidate_author: str, 
        metadata_author: str
    ) -> bool:
        """
        Проверить, похож ли кандидат на автора из метаданных.
        
        Использует несколько стратегий:
        1. Полное совпадение строк (100%)
        2. Проверка что хотя бы одно слово из metadata есть в candidate
        3. Fuzzy matching для похожести (70%)
        
        Если метаданные пусты, кандидат отклоняется.
        
        Args:
            candidate_author: Предполагаемый автор из папки/имени файла
            metadata_author: Автор из метаданных FB2
        
        Returns:
            True если автор подтверждается, False иначе
        """
        if not candidate_author or not metadata_author:
            return False
        
        try:
            from difflib import SequenceMatcher
            
            # Нормализовать строки для сравнения
            cand_lower = candidate_author.lower().strip()
            meta_lower = metadata_author.lower().strip()
            
            # 1. Проверить полное совпадение
            if cand_lower == meta_lower:
                return True
            
            # 2. Проверить что хотя бы одно слово из metadata есть в candidate
            # Это помогает при разном порядке слов: "Иван Петров" vs "Петров Иван"
            meta_words = set(meta_lower.split())
            cand_words = set(cand_lower.replace(',', ' ').split())  # Убрать запятые (для списков авторов)
            
            # Если найдено хотя бы 50% слов из метаданных в кандидате, это хороший знак
            if meta_words and cand_words:
                overlap = len(meta_words & cand_words) / len(meta_words)
                if overlap >= 0.5:  # Хотя бы половина слов совпадает
                    return True
            
            # 3. Fuzzy matching для последней проверки
            similarity = SequenceMatcher(None, cand_lower, meta_lower).ratio()
            if similarity >= 0.70:
                return True
            
            return False
        except Exception:
            return False

    def extract_all_authors(
        self,
        fb2_filepath: str,
        apply_priority: bool = True
    ) -> Dict[str, Any]:
        """
        Комбинированное извлечение авторов из всех источников.
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
            apply_priority: Применять ли приоритизацию результатов
        
        Returns:
            Структурированный результат с авторами и метаданными:
            {
                'primary_author': {
                    'name': str,
                    'priority': int,
                    'source': str,
                    'confidence': float,
                    ...
                },
                'alternative_authors': [...],
                'all_results_by_priority': {
                    priority: [ExtractionResult, ...],
                    ...
                },
                'processing_info': {
                    'fb2_path': str,
                    'file_name': str,
                    'folder_path': str,
                    ...
                }
            }
        """
        # TODO: Реализовать полный процесс извлечения
        # 1. Получить информацию о пути к файлу
        # 2. Вызвать extract_from_folder_structure()
        # 3. Вызвать extract_from_filename()
        # 4. Вызвать extract_from_fb2_metadata()
        # 5. Слить результаты используя merge_results_by_priority()
        # 6. Вернуть структурированный результат
        pass
    
    def extract_from_folder_structure(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из структуры папок.
        
        Приоритет: AuthorExtractionPriority.FOLDER_STRUCTURE (1)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из структуры папок
        # - Получить папку файла
        # - Применить author_processor.extract_author_from_filepath()
        # - Проверить результаты против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FOLDER_STRUCTURE
        pass
    
    def extract_from_filename(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из названия файла.
        
        Приоритет: AuthorExtractionPriority.FILENAME (2)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из названия файла
        # - Получить имя файла без расширения
        # - Применить author_processor.extract_author_from_filename()
        # - Проверить результаты против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FILENAME
        pass
    
    def extract_from_fb2_metadata(self, fb2_filepath: str) -> List[ExtractionResult]:
        """
        Извлечение авторов из метаданных FB2 файла.
        
        Приоритет: AuthorExtractionPriority.FB2_METADATA (3)
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
        
        Returns:
            Список результатов (может быть пуст если ничего не найдено)
        """
        # TODO: Реализовать извлечение из метаданных FB2
        # - Прочитать и спарсить XML FB2 файла
        # - Найти раздел <description>/<title-info>/<author>
        # - Извлечь first-name, last-name, nickname
        # - Применить автора_processor для нормализации
        # - Проверить против filename_blacklist
        # - Вернуть список ExtractionResult с приоритетом FB2_METADATA
        pass
    
    def merge_results_by_priority(
        self,
        results_by_priority: Dict[int, List[ExtractionResult]]
    ) -> Tuple[Optional[ExtractionResult], List[ExtractionResult]]:
        """
        Слить результаты с учетом приоритетов.
        
        Логика:
        - Итерировать по AuthorExtractionPriority.ORDER
        - Первый найденный результат (не отфильтрованный) становится основным
        - Остальные результаты становятся альтернативами
        - Результаты с более низким приоритетом идут в конец
        
        Args:
            results_by_priority: Словарь {priority: [ExtractionResult, ...]}
        
        Returns:
            (primary_result, alternative_results)
        """
        # TODO: Реализовать слияние по приоритетам
        # - Пройти по AuthorExtractionPriority.ORDER
        # - Найти первый не отфильтрованный результат
        # - Этот становится основным
        # - Остальные - альтернативы
        pass
    
    def _apply_blacklist_filter(
        self,
        value: str
    ) -> Tuple[bool, List[str]]:
        """
        Применить фильтр черного списка к значению.
        
        Args:
            value: Значение для фильтрации
        
        Returns:
            (is_filtered, reasons) - был ли отфильтрован и почему
        """
        # TODO: Реализовать фильтрацию
        # - Получить filename_blacklist из конфигурации
        # - Проверить точное совпадение (case-insensitive)
        # - Проверить совпадение подстроки
        # - Вернуть результат
        pass
    
    def _extract_author_from_folder_structure(self, fb2_path: Path) -> str:
        """
        Извлечь автора из структуры папок.
        
        Ищет имя автора в названии папки (не более folder_parse_limit уровней).
        """
        try:
            # Получить путь к файлу
            folder_path = str(fb2_path.parent)
            
            # Попытаться извлечь автора из пути папки
            result = self.author_processor.extract_author_from_filepath(folder_path)
            if result:
                # Результат - список ExtractionResult, берем первый
                author_name = result[0].value if hasattr(result[0], 'value') else str(result[0])
                if author_name:
                    return author_name
        except Exception as e:
            pass
        
        return ''
    
    def _extract_author_from_filename(self, fb2_path: Path) -> str:
        """
        Извлечь автора из названия файла.
        """
        try:
            filename = fb2_path.stem  # Имя без расширения
            
            # Попытаться извлечь автора из названия файла
            result = self.author_processor.extract_author_from_filename(filename)
            if result:
                # Результат - список ExtractionResult, берем первый
                author_name = result[0].value if hasattr(result[0], 'value') else str(result[0])
                if author_name:
                    return author_name
        except Exception as e:
            pass
        
        return ''
    
    def _extract_author_from_metadata(self, fb2_path: Path) -> str:
        """
        Извлечь автора из метаданных FB2 файла.
        
        Значение извлекается ТОЛЬКО из тега <title-info>,
        а не из других разделов (ignoring document-info и т.д.).
        """
        try:
            with open(fb2_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            import re
            
            # Найти весь <title-info>...</title-info> блок
            title_info_match = re.search(r'<(?:fb:)?title-info>.*?</(?:fb:)?title-info>', content, re.DOTALL)
            
            if not title_info_match:
                return ''
            
            # Работаем только с содержимым title-info
            title_info_content = title_info_match.group(0)
            
            # Найти первого автора ТОЛЬКО в title-info
            author_pattern = r'<author>.*?</author>'
            match = re.search(author_pattern, title_info_content, re.DOTALL)
            
            if match:
                author_text = match.group(0)
                
                # Извлечь компоненты имени
                first_name_match = re.search(r'<first-name>(.*?)</first-name>', author_text)
                last_name_match = re.search(r'<last-name>(.*?)</last-name>', author_text)
                nickname_match = re.search(r'<nickname>(.*?)</nickname>', author_text)
                
                first_name = first_name_match.group(1) if first_name_match else ''
                last_name = last_name_match.group(1) if last_name_match else ''
                nickname = nickname_match.group(1) if nickname_match else ''
                
                # Составить имя
                if nickname:
                    author = nickname
                elif first_name or last_name:
                    author = f"{first_name} {last_name}".strip()
                else:
                    return ''
                
                # Проверить черный список
                if not self._is_blacklisted(author):
                    return author
        except Exception:
            pass
        
        return ''
    
    def _is_blacklisted(self, value: str) -> bool:
        """
        Проверить, находится ли значение в черном списке.
        """
        try:
            blacklist = self.settings.get_filename_blacklist()
            value_lower = value.lower()
            
            for item in blacklist:
                if value_lower == item.lower() or item.lower() in value_lower:
                    return True
        except Exception:
            pass
        
        return False
    
    def reload_config(self):
        """Перезагрузить конфигурацию и паттерны."""
        self.settings.load()
        self.author_processor.reload_patterns()


if __name__ == '__main__':
    # Простой тест
    extractor = FB2AuthorExtractor()
    print("FB2AuthorExtractor инициализирован")
    print(f"AuthorProcessor: {extractor.author_processor}")
    print(f"Приоритеты извлечения:")
    for priority in AuthorExtractionPriority.ORDER:
        print(f"  {priority}: {AuthorExtractionPriority.get_name(priority)}")
