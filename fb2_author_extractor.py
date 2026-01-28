"""
Модуль для парсинга FB2 файлов и извлечения информации об авторах.

Реализует многоуровневую стратегию извлечения авторов:
1. Структура папок (FOLDER_STRUCTURE)
2. Название файла (FILENAME)
3. Метаданные FB2 (FB2_METADATA)

Использует приоритезацию из extraction_constants.AuthorExtractionPriority
"""

import xml.etree.ElementTree as ET
import re
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
        
        # Маркеры сборников/антологий
        self.anthology_markers = [
            'сборник', 'антология', 'коллекция', 'хиты', 'лучшее', 'избранное',
            'сборник рассказов', 'сборник повестей', 'сборник произведений',
            'best of', 'anthology', 'collection', 'digest',
            'сборник военной', 'сборник научной', 'сборник фантастики',
            'избранные произведения', 'лучшие рассказы', 'лучшие повести'
        ]
    
    def resolve_author_by_priority(
        self,
        fb2_filepath: str,
        folder_parse_limit: int = 3
    ) -> Tuple[str, str]:
        """
        Простой метод для получения автора по приоритетам источников.
        
        Приоритет извлечения в зависимости от folder_parse_limit:
        - folder_parse_limit > 0: папка → файл → метаданные (структурированное хранилище)
        - folder_parse_limit == 0: файл → метаданные (неструктурированное, разные авторы в папке)
        
        Для источников 1 и 2 используется fuzzy matching для верификации:
        - Кандидат сравнивается с авторами из метаданных
        - Если похожесть > 70%, принимается
        - Если не похож ни на кого в метаданных, отклоняется
        
        Правило множественных авторов:
        - Если авторов <= 2: берем имена
        - Если авторов > 2: возвращаем "Соавторство"
        
        Args:
            fb2_filepath: Полный путь к FB2 файлу
            folder_parse_limit: Глубина парсинга папок (int):
                - 0: не парсим папки вообще (приоритет: файл → метаданные)
                - N>0: парсим максимум N уровней вверх (приоритет: папка → файл → метаданные)
        
        Returns:
            (author_name, source) где source in ['folder_dataset', 'folder', 'filename', 'metadata', '']
            Если ничего не найдено, возвращает ('', '')
        """
        try:
            fb2_path = Path(fb2_filepath)
            
            # Получить авторов из метаданных один раз (источник истины)
            metadata_author = self._extract_author_from_metadata(fb2_path)
            
            # 1. Попытка получить автора из структуры папок (если folder_parse_limit > 0)
            if folder_parse_limit > 0:
                # folder_parse_limit > 0: парсим папки на N уровней (систематическая структура - folder_dataset)
                try:
                    author = self._extract_author_from_folder_structure(fb2_path, folder_parse_limit)
                    if author:
                        # Проверить: если в папке указано несколько авторов (запятая), не проверять против метаданных
                        # Если это список авторов, мы ему доверяем  
                        if ',' in author or ';' in author:
                            # Это список авторов из папки - принимаем как есть без верификации
                            # (Расширение аббревиатур произойдёт позже в RegenCSVService._expand_abbreviated_authors)
                            author = self._normalize_author_count(author)
                            author = self._normalize_author_format(author) if author else ""
                            if not author:
                                # Если нормализация не сработала, доверяем исходному списку
                                author = " ".join(self._extract_author_from_folder_structure(fb2_path, folder_parse_limit).split())
                            if author:
                                return author, 'folder_dataset'  # ИСПРАВЛЕНО: folder_dataset вместо folder
                        elif self._verify_author_against_metadata(author, metadata_author):
                            # Одиночный автор - проверяем против метаданных
                            author = self._normalize_author_count(author)
                            author = self._normalize_author_format(author)
                            if author:
                                return author, 'folder_dataset'  # ИСПРАВЛЕНО: folder_dataset вместо folder
                except Exception as e:
                    pass  # Продолжаем к следующему источнику
            
            # 2. Попытка получить автора из имени файла
            try:
                author = self._extract_author_from_filename(fb2_path)
                if author:
                    # КЛЮЧЕВОЕ ПРАВИЛО: Если автор ЯВНО указан в скобках "(Автор)" в имени файла,
                    # это ВСЕГДА берется как истина - не нужна верификация против метаданных!
                    # Скобки - это явная аннотация автора, которая имеет приоритет над метаданными.
                    has_explicit_pattern = self._has_explicit_author_in_parentheses(fb2_path)
                    
                    if has_explicit_pattern:
                        # Автор явно в скобках - используем как filename source БЕЗ верификации
                        # НО: Metadata используется для расширения фамилий до полного формата "ФИ"
                        # Получить ВСЕ авторов из метаданных для расширения
                        all_metadata_authors = self._extract_all_authors_from_metadata(fb2_path)
                        expanded_author = self._expand_surnames_from_metadata(author, all_metadata_authors if all_metadata_authors else metadata_author)
                        if expanded_author:
                            # Успешно расширили фамилии - используем расширённую версию
                            normalized = self._normalize_author_format(expanded_author)
                            if normalized:
                                return normalized, 'filename'
                            else:
                                # Нормализация не сработала, но расширение есть
                                return expanded_author, 'filename'
                        else:
                            # Расширение не сработало - возвращаем как есть
                            return author, 'filename'
                    
                    # Если folder_parse_limit == 0 (папка с разными авторами),
                    # принимаем имя файла БЕЗ проверки против метаданных
                    if folder_parse_limit == 0:
                        # Полная граница - принимаем имя файла как источник истины
                        # НО нужно нормализовать если возможно, иначе расширить из метаданных
                        normalized = self._normalize_author_count(author)
                        if not normalized:
                            # Нормализация не сработала (нет полных имён)
                            # Попытаться расширить фамилии из метаданных
                            # Получить ВСЕХ авторов для расширения
                            all_metadata = self._extract_all_authors_from_metadata(fb2_path)
                            expanded = self._expand_surnames_from_metadata(author, all_metadata if all_metadata else metadata_author)
                            if expanded:
                                # Попытаться нормализовать расширенный результат
                                normalized = self._normalize_author_format(expanded)
                                if not normalized:
                                    # Формат не сработал, хранить расширенный как есть
                                    normalized = expanded
                            else:
                                # Расширение не сработало, хранить как есть
                                normalized = " ".join(author.split())
                        else:
                            # Нормализация сработала, применить полный формат
                            normalized = self._normalize_author_format(normalized)
                            if not normalized:
                                # Формат нормализации не сработал, попытаться расширить
                                all_metadata = self._extract_all_authors_from_metadata(fb2_path)
                                expanded = self._expand_surnames_from_metadata(author, all_metadata if all_metadata else metadata_author)
                                if expanded:
                                    normalized = self._normalize_author_format(expanded)
                                    if not normalized:
                                        normalized = expanded
                                else:
                                    normalized = " ".join(author.split())
                        
                        if normalized:
                            return normalized, 'filename'
                    else:
                        # С граничным лимитом - проверяем против метаданных
                        if self._verify_author_against_metadata(author, metadata_author):
                            # Верификация пройдена - используем filename источник
                            # Попытаться нормализовать, но если не получится - все равно используем filename
                            author = self._normalize_author_count(author)
                            if author:
                                normalized_author = self._normalize_author_format(author)
                                # Если нормализация сработала, используем её, иначе используем как есть
                                if normalized_author:
                                    return normalized_author, 'filename'
                                else:
                                    # Нормализация не сработала, но верификация прошла - все равно используем
                                    return " ".join(author.split()), 'filename'
                            else:
                                # normalize_author_count не сработала, используем исходный
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
        - Конвертация ё -> е для нормализации
        
        Args:
            author_string: Строка с одним или несколькими авторами
        
        Returns:
            Нормализованная строка
        """
        if not author_string or author_string == "Соавторство":
            return author_string
        
        try:
            # Конвертировать ё -> е для нормализации
            author_string = author_string.replace('ё', 'е')
            
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
        - Обработка аббревиатур типа "А.Фамилия" (оставить как есть)
        - Конвертация ё -> е для нормализации
        
        Args:
            author_name: Имя автора (может быть в разных форматах)
        
        Returns:
            Нормализованное имя вида "Фамилия Имя" или пустая строка
        """
        if not author_name or author_name == "Соавторство":
            return author_name
        
        try:
            # Конвертировать ё -> е для нормализации
            author_name = author_name.replace('ё', 'е')
            
            # Убрать лишние пробелы
            author_name = " ".join(author_name.split())
            
            # Проверить: если это аббревиатура типа "А.Фамилия", оставить как есть
            if '.' in author_name:
                # Это может быть аббревиатура - проверим
                parts = author_name.split()
                if len(parts) == 2 and parts[0].endswith('.') and len(parts[0]) <= 3:
                    # Формат "А.Фамилия" или "А.B.Фамилия"
                    return author_name
            
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
        Конвертация ё -> е для нормализации
        
        Args:
            author_string: Строка с одним или несколькими авторами
        
        Returns:
            Нормализованная строка или "Соавторство"
        """
        if not author_string:
            return ""
        
        try:
            # Конвертировать ё -> е для нормализации
            author_string = author_string.replace('ё', 'е')
            
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
            
            # Если авторов > 1, нужно нормализовать каждого
            if len(authors) > 1:
                normalized_authors = []
                for author in authors:
                    normalized = self._normalize_author_format(author)
                    if not normalized and author:
                        # Если формальная нормализация не сработала,
                        # но автор содержит точку (вероятно аббревиатура),
                        # оставляем как есть
                        normalized = author.strip()
                    if normalized:
                        normalized_authors.append(normalized)
                
                if normalized_authors:
                    return ", ".join(normalized_authors)
                else:
                    # Если ничего не нормализовалось, оставляем исходное
                    return author_string
            
            # Один автор - нормализовать и вернуть
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
    
    def _extract_author_from_folder_structure(self, fb2_path: Path, folder_parse_limit: int = 3) -> str:
        """
        Извлечь автора из структуры папок.
        
        Ищет имя автора в названии папки, поднимаясь вверх на folder_parse_limit уровней.
        Останавливается на первой папке, где найдены авторы.
        """
        try:
            # Поднимаемся вверх по folder_parse_limit уровней, ищем авторов в названиях папок
            current_path = fb2_path.parent
            for level in range(folder_parse_limit):
                if current_path.parts:
                    folder_name = current_path.name
                    
                    # Паттерн: "(Author)" где может быть несколько авторов
                    import re
                    bracket_patterns = [
                        r'\(([^)]+)\)(?:\s*$|\s+[-–])',  # В конце или перед дефисом: (Author) - или (Author)
                        r'(?:^|\s+)(?:[-–]\s+)?\(([^)]+)\)',  # В начале или после дефиса: - (Author)
                    ]
                    
                    for pattern in bracket_patterns:
                        match = re.search(pattern, folder_name)
                        if match:
                            author_candidate = match.group(1).strip()
                            if author_candidate and not self._is_blacklisted_value(author_candidate):
                                return author_candidate
                    
                    # Поднимаемся на один уровень вверх
                    parent = current_path.parent
                    if parent == current_path:  # Достигли корня
                        break
                    current_path = parent
            
            # Если парсинг скобок в папках не сработал, использовать author_processor
            folder_path = str(fb2_path.parent)
            result = self.author_processor.extract_author_from_filepath(folder_path)
            if result:
                # Результат - список ExtractionResult, берем первый
                author_name = result[0].value if hasattr(result[0], 'value') else str(result[0])
                if author_name:
                    return author_name
        except Exception as e:
            pass
        
        return ''
    
    def _extract_author_from_folder_structure_with_limit(self, fb2_path: Path, limit_folder: Path) -> str:
        """
        Извлечь автора из структуры папок с ограничением до определённой папки.
        
        Ищет автора от файла вверх до папки limit_folder, но не включает саму папку.
        
        Args:
            fb2_path: Путь к FB2 файлу
            limit_folder: Папка, до которой парсить (не включая её)
        
        Returns:
            Имя автора или пустая строка
        """
        try:
            import re
            # Получить путь к файлу
            current_path = fb2_path.parent
            limit_path = limit_folder
            
            # Идем вверх по папкам от файла до лимита
            while current_path != limit_path and current_path != current_path.parent:
                folder_name = current_path.name
                
                # Попытаться прямого парсинга скобок в названии папки
                bracket_patterns = [
                    r'\(([^)]+)\)(?:\s*$|\s+[-–])',  # В конце или перед дефисом
                    r'(?:^|\s+)(?:[-–]\s+)?\(([^)]+)\)',  # В начале или после дефиса
                ]
                
                author_found = False
                for pattern in bracket_patterns:
                    match = re.search(pattern, folder_name)
                    if match:
                        author_candidate = match.group(1).strip()
                        if author_candidate and not self._is_blacklisted_value(author_candidate):
                            return author_candidate
                
                # Если прямой парсинг не дал результата, использовать author_processor
                result = self.author_processor.extract_author_from_filename(folder_name)
                if result:
                    author_name = result[0].value if hasattr(result[0], 'value') else str(result[0])
                    if author_name:
                        return author_name
                
                # Поднимаемся на уровень выше
                current_path = current_path.parent
        except Exception as e:
            pass
        
        return ''
    
    def _extract_author_from_filename(self, fb2_path: Path) -> str:
        """
        Извлечь автора из названия файла.
        Поддерживает паттерны:
        - "Title (Author).fb2"
        - "(Author) Title.fb2"
        - "Title - Author.fb2"
        - "А.Фамилия" (инициалы)
        """
        try:
            filename = fb2_path.stem  # Имя без расширения
            
            # Прямой парсинг скобок: "Title (Author)" или "(Author) Title"
            import re
            
            # Паттерн 1: "(Author)" где Author может быть "А.Фамилия" или "Имя Фамилия"
            bracket_patterns = [
                r'\(([^)]+)\)(?:\s*$|\s+[-–])',  # В конце или перед дефисом: (Author) - или (Author)
                r'(?:^|\s+)(?:[-–]\s+)?\(([^)]+)\)',  # В начале или после дефиса: - (Author)
            ]
            
            for pattern in bracket_patterns:
                match = re.search(pattern, filename)
                if match:
                    author_candidate = match.group(1).strip()
                    if author_candidate and not self._is_blacklisted_value(author_candidate):
                        # Если содержит инициалы "А.Фамилия", попробовать расширить из метаданных
                        if re.match(r'^[А-Яа-я]\.[А-Яа-я]', author_candidate):
                            # Нужно получить полное имя - используем ALL авторов для лучшего совпадения
                            all_metadata_authors = self._extract_all_authors_from_metadata(fb2_path)
                            if all_metadata_authors:
                                # Попробовать найти совпадение по фамилии
                                surname = author_candidate.split('.')[-1]  # "Михайловский"
                                if surname.lower() in all_metadata_authors.lower():
                                    # Нашли соответствие по фамилии - используем полное имя из метаданных
                                    # Найти конкретного автора
                                    authors_list = all_metadata_authors.split('; ')
                                    for auth in authors_list:
                                        if surname.lower() in auth.lower():
                                            return auth
                                    return all_metadata_authors
                        return author_candidate
            
            # Если скобки не дали результата, попробовать author_processor
            result = self.author_processor.extract_author_from_filename(filename)
            if result:
                # Результат - список ExtractionResult, берем первый
                author_name = result[0].value if hasattr(result[0], 'value') else str(result[0])
                if author_name:
                    return author_name
        except Exception as e:
            pass
        
        return ''
    
    def _is_blacklisted_value(self, value: str) -> bool:
        """Проверить, есть ли значение в чёрном списке."""
        blacklist = ['том', 'часть', 'выпуск', 'сборник', 'антология', 
                     'book', 'vol', 'volume', 'part', 'выпуск']
        value_lower = value.lower()
        return any(bl in value_lower for bl in blacklist)
    
    def _has_explicit_author_in_parentheses(self, fb2_path: Path) -> bool:
        """
        Проверить, есть ли явно указанный автор в скобках в конце имени файла.
        
        Паттерн: "название (Автор).fb2"
        
        Args:
            fb2_path: Path к FB2 файлу
        
        Returns:
            True если автор явно указан в скобках в конце, False иначе
        """
        filename = fb2_path.stem
        pattern = r'\(([^()]+)\)\s*$'  # Скобки только в конце
        match = re.search(pattern, filename)
        if match:
            author_candidate = match.group(1).strip()
            # Проверить что это не чёрный список и похоже на имя автора
            if author_candidate and not self._is_blacklisted_value(author_candidate):
                # Простая проверка: содержит буквы и не выглядит как год/номер
                if any(c.isalpha() for c in author_candidate):
                    return True
        return False
    
    def _extract_author_from_metadata(self, fb2_path: Path) -> str:
        """
        Извлечь автора из метаданных FB2 файла.
        
        Значение извлекается ТОЛЬКО из тега <title-info>,
        а не из других разделов (ignoring document-info и т.д.).
        Возвращает ТОЛЬКО ПЕРВОГО АВТОРА для проверки и верификации.
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
                middle_name_match = re.search(r'<middle-name>(.*?)</middle-name>', author_text)
                
                first_name = first_name_match.group(1) if first_name_match else ''
                last_name = last_name_match.group(1) if last_name_match else ''
                middle_name = middle_name_match.group(1) if middle_name_match else ''
                
                # Составить имя - используем только first-name и last-name
                # nickname игнорируется полностью
                if first_name or last_name:
                    author = f"{first_name} {last_name}".strip()
                else:
                    return ''
                
                if not author:
                    return ''
                
                # Проверить черный список
                if not self._is_blacklisted(author):
                    return author
        except Exception:
            pass
        
        return ''
    
    def _extract_all_authors_from_metadata(self, fb2_path: Path) -> str:
        """
        Извлечь ВСЕХ авторов из метаданных FB2 файла.
        
        Значение извлекается ТОЛЬКО из тега <title-info>,
        а не из других разделов.
        Возвращает строку со всеми авторами разделённых '; '
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
            
            # Найти всех авторов в title-info
            author_pattern = r'<author>.*?</author>'
            matches = re.finditer(author_pattern, title_info_content, re.DOTALL)
            
            authors = []
            for match in matches:
                author_text = match.group(0)
                
                # Извлечь компоненты имени
                first_name_match = re.search(r'<first-name>(.*?)</first-name>', author_text)
                last_name_match = re.search(r'<last-name>(.*?)</last-name>', author_text)
                
                first_name = first_name_match.group(1) if first_name_match else ''
                last_name = last_name_match.group(1) if last_name_match else ''
                
                # Составить имя
                if first_name or last_name:
                    author = f"{first_name} {last_name}".strip()
                    if author and not self._is_blacklisted(author):
                        authors.append(author)
            
            if authors:
                return "; ".join(authors)
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
    
    def _expand_surnames_from_metadata(self, surname_string: str, metadata_author: str) -> str:
        """
        Расширить фамилии (например "Харников, Дынин") полными именами из метаданных.
        
        Алгоритм:
        1. Разбить surname_string на отдельные фамилии
        2. Для каждой фамилии найти соответствие в metadata_author
        3. Если найдено - подставить полное имя
        4. Вернуть расширенный список в формате "Фамилия Имя"
        
        Args:
            surname_string: "Харников, Дынин" или "Харников; Дынин"
            metadata_author: "Александр Харников; Максим Дынин" (полные имена)
        
        Returns:
            Расширенная строка типа "Харников Александр; Дынин Максим" или пустая строка
        """
        if not surname_string or not metadata_author:
            return ""
        
        try:
            # Разбить фамилии по разделителям
            import re
            surnames = re.split(r'[,;]', surname_string)
            surnames = [s.strip() for s in surnames if s.strip()]
            
            # Разбить метаданные по авторам
            metadata_authors = re.split(r'[;]', metadata_author)
            metadata_authors = [a.strip() for a in metadata_authors if a.strip()]
            
            expanded = []
            for surname in surnames:
                surname_lower = surname.lower()
                found = False
                
                # Поиск в метаданных: проверить каждого автора
                for meta_author in metadata_authors:
                    meta_lower = meta_author.lower()
                    
                    # Проверка 1: фамилия в конце "Имя Фамилия"
                    if meta_lower.endswith(surname_lower):
                        normalized = self._normalize_single_author(meta_author)
                        if normalized:
                            expanded.append(normalized)
                            found = True
                            break
                    
                    # Проверка 2: фамилия где-то в строке "Имя Фамилия"
                    if ' ' + surname_lower in meta_lower or meta_lower.startswith(surname_lower + ' '):
                        normalized = self._normalize_single_author(meta_author)
                        if normalized:
                            expanded.append(normalized)
                            found = True
                            break
                
                if not found:
                    # Фамилия не найдена в метаданных - хранить как есть
                    expanded.append(surname)
            
            if expanded:
                return "; ".join(expanded)
        except Exception:
            pass
        
        return ""
    
    def is_anthology(self, filename: str, author_count: int = 0) -> bool:
        """
        Определить, является ли файл сборником/антологией.
        
        Критерии:
        1. Имя файла содержит маркеры сборника (сборник, антология, хиты и т.д.)
        2. И авторов > 2 (что указывает на множество авторов)
        
        Args:
            filename: Имя файла без расширения
            author_count: Количество авторов из метаданных (опционально)
        
        Returns:
            True если файл признан сборником
        """
        try:
            filename_lower = filename.lower()
            
            # Проверить маркеры сборников в имени файла
            for marker in self.anthology_markers:
                if marker in filename_lower:
                    # Если есть маркер сборника и авторов > 2, это точно сборник
                    if author_count > 2:
                        return True
                    # Даже без явного маркера количества авторов, наличие маркера сборника = сборник
                    return True
            
            # Если авторов > 4, это скорее всего сборник даже без явных маркеров
            if author_count > 4:
                return True
        except Exception:
            pass
        
        return False
    
    def expand_abbreviated_author(self, abbreviated_author: str, all_authors_map: Dict[str, str]) -> str:
        """
        Раскрыть сокращённого автора (А.Фамилия) до полного имени.
        
        Стратегия:
        1. Парсить "А.Фамилия" - может быть как "А. Фамилия" так и "А.Фамилия"
        2. Извлечь букву инициала и фамилию
        3. Поискать в all_authors_map по фамилии как ключу
        4. Если найдено и инициал совпадает - вернуть полное имя
        5. Если нет - оставить как было
        
        Args:
            abbreviated_author: Сокращённое имя типа "А.Фамилия" или "А. Фамилия"
            all_authors_map: Словарь {фамилия.lower(): полное_имя (Фамилия Имя)}
        
        Returns:
            Полное имя если найдено, иначе исходное
        """
        if not abbreviated_author or '.' not in abbreviated_author:
            return abbreviated_author
        
        try:
            # Парсить "А.Фамилия" или "А. Фамилия"
            # Сначала попробуем с пробелом (А. Фамилия)
            parts = abbreviated_author.split()
            if len(parts) == 2:
                # Формат "А. Фамилия"
                init_part = parts[0]
                surname = parts[1]
            elif len(parts) == 1:
                # Формат "А.Фамилия" (без пробела)
                # Нужно парсить вручную
                s = abbreviated_author
                
                # Найти позицию точки
                dot_pos = s.find('.')
                if dot_pos == -1:
                    return abbreviated_author
                
                init_part = s[:dot_pos+1]  # "А."
                surname = s[dot_pos+1:].lstrip()  # "Фамилия"
                
                if not surname:
                    return abbreviated_author
            else:
                return abbreviated_author
            
            # Проверить что первая часть заканчивается точкой
            if not init_part.endswith('.'):
                return abbreviated_author
            
            # Получить первую букву инициала
            first_letter = init_part[0].upper()
            
            # Поискать в словаре по фамилии как ключу
            surname_lower = surname.lower()
            
            # Попытка 1: найти точное совпадение фамилии в словаре (ключи - фамилии)
            if surname_lower in all_authors_map:
                full_name = all_authors_map[surname_lower]
                
                # Парсить полное имя "Фамилия Имя"
                full_parts = full_name.split()
                if len(full_parts) >= 2:
                    first_name = full_parts[1]  # Второе слово - имя
                    
                    # Проверить совпадение первой буквы имени с инициалом
                    if first_name and first_name[0].upper() == first_letter:
                        return full_name
            
            # Если не найдено - вернуть как было
            return abbreviated_author
        
        except Exception:
            return abbreviated_author
    
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
