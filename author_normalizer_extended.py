#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Author Normalizer Extended - PASS 3, 5, 6 functions for CSV regeneration

Модуль обработки авторов для PASS 3, 5, 6 системы регенерации CSV.
Функции для:
- PASS 3: Нормализация формата авторов (Имя Фамилия → Фамилия Имя)
- PASS 5: Применение конвертаций фамилий (после консенсуса)
- PASS 6: Раскрытие аббревиатур (И.Петров → Иван Петров)

Все функции работают с BookRecord dataclass и используют SettingsManager для конфигурации.
"""

import re
from typing import List, Dict, Set, Optional, Callable, Any
from collections import Counter
from dataclasses import dataclass, field

try:
    from settings_manager import SettingsManager
    from logger import Logger
    from name_normalizer import AuthorName
except ImportError:
    from .settings_manager import SettingsManager
    from .logger import Logger
    from .name_normalizer import AuthorName


@dataclass
class BookRecord:
    """Запись о книге с прогрессивным заполнением на разных PASS.
    
    Evolves through the PASS system:
    - PASS 1: Initialized with author and series determined by priority
    - PASS 3: proposed_author normalized format
    - PASS 4: proposed_author may change due to consensus, author_source = "consensus"
    - PASS 5: proposed_author may be reconverted
    - PASS 6: proposed_author abbreviations expanded
    """
    file_path: str              # Путь к FB2 файлу (относительно library_path)
    file_title: str             # Название книги из title-info
    metadata_authors: str       # Исходные авторы из FB2 XML (неизменяемое!)
    proposed_author: str        # Предложенный автор (эволюционирует через PASS)
    author_source: str          # Источник: "folder_dataset", "filename", "metadata", "consensus"
    metadata_series: str = ""   # Оригинальная серия из FB2 XML (неизменяемое!)
    proposed_series: str = ""   # Предложенная серия (эволюционирует через PASS)
    series_source: str = ""     # Источник серии: "folder_dataset", "filename", "metadata", "consensus"
    file_path_normalized: str = ""  # Опционально: нормализованный путь


class AuthorNormalizer:
    """Helper class for author normalization operations."""
    
    def __init__(self, settings: Optional[SettingsManager] = None):
        """Initialize with SettingsManager.
        
        Args:
            settings: SettingsManager instance, loads from config.json if None
        """
        self.settings = settings or SettingsManager('config.json')
        self.logger = Logger()
        self._init_author_name()
    
    def _init_author_name(self):
        """Initialize AuthorName with config path."""
        config_path = self.settings._config_path if hasattr(self.settings, '_config_path') else 'config.json'
        AuthorName.set_config_path(config_path)
    
    def normalize_format(self, author: str, metadata_authors: str = "") -> str:
        """Нормализовать формат автора.
        
        "Иван Петров" → "Петров Иван"
        Если несколько авторов разделены '; ' → нормализует каждого и разделяет запятой
        "А.Михайловский; А.Харников" → "Михайловский А., Харников А."
        
        Если автор содержит неполное ФИ (только имя), использует metadata_authors для восстановления.
        Пример: "Белаш Александр; Людмила" + metadata_authors="Людмила Белаш; Александр Белаш"
        → "Белаш Александр; Людмила Белаш" (восстановлена фамилия для второго)
        
        Используется в PASS 3.
        
        Args:
            author: Имя автора в любом формате
            metadata_authors: Авторы из метаданных (для восстановления неполных ФИ)
            
        Returns:
            Нормализованное имя
        """
        if not author or author == "Сборник":
            return author
        
        # Проверить есть ли несколько авторов разделённых '; '
        if '; ' in author:
            authors = author.split('; ')
            normalized_authors = []
            
            # Парсируем metadata_authors для восстановления неполных ФИ
            metadata_authors_list = []
            if metadata_authors:
                metadata_authors_list = [a.strip() for a in metadata_authors.replace(';', ',').split(',')]
            
            for single_author in authors:
                single_author = single_author.strip()
                if single_author:
                    # Проверить если это неполное ФИ (одно слово)
                    author_words = single_author.split()
                    if len(author_words) == 1 and metadata_authors_list:
                        # Одно слово - это имя, нужно найти фамилию из metadata
                        single_word = author_words[0]
                        # Ищем в metadata авторов, где это слово есть
                        for meta_author in metadata_authors_list:
                            meta_words = meta_author.split()
                            if single_word in meta_words:
                                # Используем полное ФИ из metadata
                                single_author = meta_author
                                break
                    
                    name_obj = AuthorName(single_author)
                    normalized = name_obj.normalized if name_obj.is_valid else single_author
                    normalized_authors.append(normalized)
            
            # Объединить через запятую
            return ', '.join(normalized_authors)
        
        # Одиночный автор
        name_obj = AuthorName(author)
        return name_obj.normalized if name_obj.is_valid else author
    
    def apply_conversions(self, author: str) -> str:
        """Применить conversions к имени автора.
        
        "Гоблин (MeXXanik)" → "Гоблин MeXXanik"
        Если несколько авторов через запятую → применяет к каждому
        
        Используется в PASS 1, 5.
        
        Args:
            author: Имя автора
            
        Returns:
            Имя с применёнными conversions
        """
        if not author or author == "Сборник":
            return author
        
        conversions = self.settings.get_author_surname_conversions()
        
        # Проверить есть ли несколько авторов разделённых запятой
        if ', ' in author:
            authors = author.split(', ')
            converted_authors = []
            
            for single_author in authors:
                single_author = single_author.strip()
                result = single_author
                
                # Пробуем каждую замену
                for pattern, replacement in conversions.items():
                    if pattern in result:
                        result = result.replace(pattern, replacement)
                
                converted_authors.append(result)
            
            # Объединить через запятую
            return ', '.join(converted_authors)
        
        # Одиночный автор
        result = author
        
        # Пробуем каждую замену
        for pattern, replacement in conversions.items():
            if pattern in result:
                result = result.replace(pattern, replacement)
        
        return result
    
    def expand_abbreviation(self, author: str, authors_map: Dict[str, List[str]]) -> str:
        """Раскрыть аббревиатуру в имени автора.
        
        "И.Петров" → "Иван Петров" (если найдено в authors_map)
        Если несколько авторов через запятую → раскрывает каждого
        
        Используется в PASS 6.
        
        Args:
            author: Имя автора с возможной аббревиатурой
            authors_map: Словарь {фамилия.lower(): [полные имена]}
            
        Returns:
            Имя с раскрытой аббревиатурой или исходное имя
        """
        if not author or "." not in author:
            return author
        
        # Проверить есть ли несколько авторов разделённых запятой
        if ', ' in author:
            authors = author.split(', ')
            expanded_authors = []
            
            for single_author in authors:
                single_author = single_author.strip()
                expanded = self._expand_single_abbreviation(single_author, authors_map)
                expanded_authors.append(expanded)
            
            # Объединить через запятую
            return ', '.join(expanded_authors)
        
        # Одиночный автор
        return self._expand_single_abbreviation(author, authors_map)
    
    def _expand_single_abbreviation(self, author: str, authors_map: Dict[str, List[str]]) -> str:
        """Раскрыть аббревиатуру в одном имени автора.
        
        Args:
            author: Одно имя автора ("А.Харников", "А. Харников", и т.д.)
            authors_map: Словарь {фамилия.lower(): [полные имена]}
                         Ключи и значения в формате "Фамилия Имя"
            
        Returns:
            Раскрытое имя или исходное
        """
        if not author or "." not in author:
            return author
        
        # Паттерн для поиска "X.Фамилия" или "Фамилия X." или "X. Фамилия" или "Фамилия X."
        pattern = r'([А-Я]\.)\s*([А-ЯЁа-яё]+)|([А-ЯЁа-яё]+)\s*([А-Я]\.)'
        match = re.search(pattern, author)
        
        if not match:
            return author
        
        # Определить фамилию и инициал
        if match.group(2):
            # Формат: "И.Фамилия" или "И. Фамилия"
            initial = match.group(1)[0]  # 'А'
            surname = match.group(2)       # 'Харников'
        else:
            # Формат: "Фамилия И." или "Фамилия И."
            surname = match.group(3)       # 'Харников'
            initial = match.group(4)[0]   # 'А'
        
        surname_lower = surname.lower()
        
        # Первый попыт: найти в авторах где фамилия - первое слово, имя начинается с инициала
        if surname_lower in authors_map:
            full_names = authors_map[surname_lower]
            for full_name in full_names:
                parts = full_name.split()
                # full_name = "Харников Александр" (Фамилия Имя)
                if len(parts) >= 2:
                    # Проверяем первая часть - фамилия
                    if parts[0].lower() == surname_lower and parts[1][0].upper() == initial:
                        return full_name
        
        # Второй попыт: найти в авторах где имя - первое слово (обратный порядок)
        # Может быть "Александр Харников"
        if initial.lower() in authors_map:
            full_names = authors_map[initial.lower()]
            for full_name in full_names:
                parts = full_name.split()
                # Проверяем есть ли фамилия в конце
                if len(parts) >= 2 and parts[-1].lower() == surname_lower:
                    return full_name
        
        return author


def apply_author_normalization(record: BookRecord, normalizer: Optional[AuthorNormalizer] = None) -> None:
    """PASS 3: Нормализовать формат автора в записи.
    
    "Иван Петров" → "Петров Иван"
    "А.Михайловский; А.Харников" → "Михайловский А., Харников А." (нормализованные, через запятую)
    
    Если автор содержит неполное ФИ, использует metadata_authors для восстановления:
    "Белаш Александр; Людмила" → "Белаш Александр; Людмила Белаш" → "Белаш Александр, Белаш Людмила"
    
    Args:
        record: BookRecord для обновления
        normalizer: AuthorNormalizer instance (создаётся если None)
    """
    if not normalizer:
        normalizer = AuthorNormalizer()
    
    if record.proposed_author == "Сборник":
        return
    
    original = record.proposed_author
    
    # Проверить если несколько авторов разделены '; ' (временный разделитель из папки)
    if '; ' in record.proposed_author:
        # Передать metadata_authors для восстановления неполных ФИ
        record.proposed_author = normalizer.normalize_format(original, record.metadata_authors)
    else:
        record.proposed_author = normalizer.normalize_format(original, record.metadata_authors)


def apply_surname_conversions_to_records(records: List[BookRecord], 
                                         settings: Optional[SettingsManager] = None) -> None:
    """PASS 5: Применить conversions к авторам во всех записях.
    
    Второе применение conversions (после PASS 4 консенсуса).
    Работает с несколькими авторами разделёнными ', ' (запятая)
    
    Args:
        records: Список BookRecord для обновления
        settings: SettingsManager instance (создаётся если None)
    """
    if not settings:
        settings = SettingsManager('config.json')
    
    normalizer = AuthorNormalizer(settings)
    
    for record in records:
        if record.proposed_author == "Сборник":
            continue
        
        original = record.proposed_author
        
        # Проверить если несколько авторов разделены ', ' (запятая)
        if ', ' in record.proposed_author:
            authors = record.proposed_author.split(', ')
            converted_authors = [normalizer.apply_conversions(a) for a in authors]
            record.proposed_author = ', '.join(converted_authors)
        else:
            record.proposed_author = normalizer.apply_conversions(original)


def apply_author_consensus(records: List[BookRecord], 
                          group_key_func: Callable[[BookRecord], str],
                          settings: Optional[SettingsManager] = None) -> None:
    """PASS 4: Применить консенсус к группам файлов.
    
    Для каждой группы файлов (определяемой group_key_func):
    1. Отфильтровать файлы с определённым источником (folder_dataset, filename, metadata)
       - Эти файлы НЕ меняются, у них уже есть надёжный источник!
    2. Найти консенсусного автора среди файлов БЕЗ источника
    3. Применить консенсус только к файлам без источника
    
    ⚠️ КРИТИЧНО: Файлы с author_source="metadata" (из PASS 2 Fallback) НЕ переписываются!
    Это не "other_records" - это результат fallback механизма и имеют определённый источник.
    
    Args:
        records: Список BookRecord для обновления
        group_key_func: Функция для определения ключа группы (например, file_path.parent)
        settings: SettingsManager instance (создаётся если None)
    """
    if not settings:
        settings = SettingsManager('config.json')
    
    normalizer = AuthorNormalizer(settings)
    logger = Logger()
    
    # Сгруппировать записи по ключу
    groups: Dict[str, List[BookRecord]] = {}
    for record in records:
        key = group_key_func(record)
        if key not in groups:
            groups[key] = []
        groups[key].append(record)
    
    # Обработать каждую группу
    for group_key, group_records in groups.items():
        # ⚠️ ИСПРАВЛЕНИЕ: Исключить файлы с ДЛЮБЫм определённым источником
        # folder_dataset - определён в PASS 1
        # filename - определён в PASS 2
        # metadata - определён в PASS 2 Fallback
        # Консенсус применяется ТОЛЬКО к файлам где source="" (пусто)
        determined_records = [r for r in group_records 
                            if r.author_source in ("folder_dataset", "filename", "metadata")]
        undetermined_records = [r for r in group_records 
                               if r.author_source not in ("folder_dataset", "filename", "metadata")]
        
        if not undetermined_records:
            # Все файлы в группе уже имеют определённый источник - консенсус не нужен
            continue
        
        # Найти консенсусного автора среди файлов БЕЗ источника
        authors = [r.proposed_author for r in undetermined_records]
        authors_normalized = [normalizer.normalize_format(a) for a in authors]
        
        # Найти самого частого автора
        counter = Counter(authors_normalized)
        consensus_author = counter.most_common(1)[0][0]
        consensus_count = counter.most_common(1)[0][1]
        
        # Применить консенсус ТОЛЬКО к файлам без источника
        for record in undetermined_records:
            original = record.proposed_author
            record.proposed_author = consensus_author
            record.author_source = "consensus"
            
            logger.log(f"[PASS 4] Консенсус в {group_key}: {original} → {consensus_author} "
                      f"({consensus_count}/{len(undetermined_records)})")


def build_authors_map(records: List[BookRecord], 
                     settings: Optional[SettingsManager] = None) -> Dict[str, List[str]]:
    """Построить словарь авторов для раскрытия аббревиатур в PASS 6.
    
    Собирает все уникальные авторы и группирует их по фамилии.
    Результат: {"петров": ["Петров Иван", "Петров Сергей"], ...}
    Обрабатывает авторов разделённых запятой.
    
    Args:
        records: Список BookRecord
        settings: SettingsManager instance (создаётся если None)
        
    Returns:
        Словарь {фамилия.lower(): [полные_имена]}
    """
    if not settings:
        settings = SettingsManager('config.json')
    
    normalizer = AuthorNormalizer(settings)
    authors_map: Dict[str, List[str]] = {}
    seen = set()  # Для дедупликации
    
    # Собрать авторов из proposed_author и metadata_authors
    for record in records:
        # Из proposed_author (уже обработано)
        if record.proposed_author and record.proposed_author != "Сборник":
            author = record.proposed_author
            
            # Если несколько авторов через запятую
            if ', ' in author:
                for single_author in author.split(', '):
                    single_author = single_author.strip()
                    if single_author:
                        # Пропустить если это аббревиатура (содержит точку)
                        if '.' not in single_author:
                            normalized = normalizer.normalize_format(single_author)
                            key = normalized.split()[0].lower() if normalized else ""  # фамилия - первое слово (после нормализации)
                            
                            if key and normalized not in seen:
                                if key not in authors_map:
                                    authors_map[key] = []
                                authors_map[key].append(normalized)
                                seen.add(normalized)
            else:
                # Одиночный автор
                # Пропустить если это аббревиатура (содержит точку)
                if '.' not in author:
                    normalized = normalizer.normalize_format(author)
                    key = normalized.split()[0].lower() if normalized else ""  # фамилия - первое слово (после нормализации)
                    
                    if key and normalized not in seen:
                        if key not in authors_map:
                            authors_map[key] = []
                        authors_map[key].append(normalized)
                        seen.add(normalized)
        
        # Из metadata_authors (оригинальные) - главный источник для аббревиатур
        if record.metadata_authors and record.metadata_authors != "Сборник":
            author = record.metadata_authors
            
            # Если несколько авторов через запятую (или точку с запятой из других источников)
            if ', ' in author or '; ' in author:
                sep = ', ' if ', ' in author else '; '
                for single_author in author.split(sep):
                    single_author = single_author.strip()
                    if single_author:
                        normalized = normalizer.normalize_format(single_author)
                        key = normalized.split()[0].lower() if normalized else ""  # фамилия - первое слово (после нормализации)
                        
                        if key and normalized not in seen:
                            if key not in authors_map:
                                authors_map[key] = []
                            authors_map[key].append(normalized)
                            seen.add(normalized)
            else:
                # Одиночный автор
                normalized = normalizer.normalize_format(author)
                key = normalized.split()[0].lower() if normalized else ""  # фамилия - первое слово (после нормализации)
                
                if key and normalized not in seen:
                    if key not in authors_map:
                        authors_map[key] = []
                    authors_map[key].append(normalized)
                    seen.add(normalized)
    
    return authors_map


def expand_abbreviated_authors(records: List[BookRecord],
                               authors_map: Optional[Dict[str, List[str]]] = None,
                               settings: Optional[SettingsManager] = None) -> None:
    """PASS 6: Раскрыть аббревиатуры в именах авторов.
    
    "И.Петров" → "Иван Петров" (поиск в authors_map)
    "А.Михайловский, А.Харников" → "Александр Михайловский, Александр Харников"
    
    Args:
        records: Список BookRecord для обновления
        authors_map: Словарь для поиска полных имён (создаётся если None)
        settings: SettingsManager instance (создаётся если None)
    """
    if not settings:
        settings = SettingsManager('config.json')
    
    normalizer = AuthorNormalizer(settings)
    logger = Logger()
    
    if not authors_map:
        authors_map = build_authors_map(records, settings)
    
    for record in records:
        if record.proposed_author == "Сборник" or "." not in record.proposed_author:
            continue
        
        original = record.proposed_author
        
        # Проверить если несколько авторов разделены ', ' (запятая из PASS 3)
        if ', ' in record.proposed_author:
            authors = record.proposed_author.split(', ')
            expanded_authors = [normalizer.expand_abbreviation(a, authors_map) for a in authors]
            record.proposed_author = ', '.join(expanded_authors)
        else:
            record.proposed_author = normalizer.expand_abbreviation(original, authors_map)
        
        if record.proposed_author != original:
            logger.log(f"[PASS 6] Раскрытие аббревиатуры: {original} → {record.proposed_author}")
