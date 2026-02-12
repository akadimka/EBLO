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
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import List, Dict, Optional, Callable, Tuple
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
        self.config_path = Path(config_path)
        self.settings = SettingsManager(config_path)
        self.logger = Logger()
        self.extractor = FB2AuthorExtractor(config_path)
        
        # FB2 файлы сканируются из last_scan_path (рабочей папки), определённой в config.json
        self.work_dir = Path(self.settings.get_last_scan_path())
        self.folder_parse_limit = self.settings.get_folder_parse_limit()
        
        self.records: List[BookRecord] = []
        
        # Загрузить паттерны извлечения авторов из файла/папки
        self.author_patterns = self._load_author_patterns()
        
        # Загрузить список известных имён авторов (для проверки наличия имени)
        self.author_names = self._load_author_names()
        
        # Загрузить паттерны распознавания структуры имён
        self.author_name_patterns = self._load_author_name_patterns()
    
    def _load_author_patterns(self) -> List[Dict]:
        """Загрузить паттерны извлечения авторов из конфига.
        
        Returns:
            List of pattern dicts with 'pattern' key
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            patterns = config_data.get('author_series_patterns_in_files', [])
            return patterns if patterns else []
        except Exception as e:
            self.logger.log(f"⚠️ Ошибка загрузки паттернов авторов: {e}")
            return []
    
    def _load_author_names(self) -> set:
        """Загрузить список всех известных имён авторов (муж. + жен.).
        
        Returns:
            Set имён в нижнем регистре
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            male_names = set(name.lower() for name in config_data.get('male_names', []))
            female_names = set(name.lower() for name in config_data.get('female_names', []))
            return male_names | female_names
        except Exception as e:
            self.logger.log(f"⚠️ Ошибка загрузки списка имён: {e}")
            return set()
    
    def _load_author_name_patterns(self) -> List[Dict]:
        """Загрузить паттерны распознавания структуры имён авторов.
        
        Returns:
            List of name pattern dicts
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            patterns = config_data.get('author_name_patterns', [])
            return patterns if patterns else []
        except Exception as e:
            self.logger.log(f"⚠️ Ошибка загрузки паттернов имён: {e}")
            return []
    
    def _normalize_diacritics(self, text: str) -> str:
        """Нормализовать диакритику (удалить ё→е, и т.д.).
        
        Пример: "Жеребьёв" → "Жеребьев"
        Используем NFD decomposition и отфильтровываем combining marks.
        
        Args:
            text: Текст с возможной диакритикой
            
        Returns:
            Текст без диакритики
        """
        if not text:
            return text
        # NFD разбивает буквы с диакритикой на базовую букву и комбинирующие символы
        nfd = unicodedata.normalize('NFD', text)
        # Отфильтровываем диакритику (категория Mn = combining mark nonspacing)
        return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')
    
    def _looks_like_author_name(self, text: str) -> bool:
        """Проверить выглядит ли текст как имя автора (по структуре только).
        
        На отличие от _contains_author_name, это НЕ проверяет:
        - Наличие в known_authors
        - Сложные паттерны
        
        Проверяет только базовую структуру:
        - Не пусто и не брак
        - Содержит буквы (кириллицу или латиницу)
        - Не содержит подозрительный чисел (999 999)
        - Не очень длинное
        
        Args:
            text: Текст для проверки
            
        Returns:
            True если выглядит как имя, False иначе
        """
        if not text or len(text) < 2:
            return False
        
        # Слишком длинное - вероятно не имя
        if len(text) > 100:
            return False
        
        # Содержит ли хотя бы одну букву (кириллица или латиница)?
        has_letter = any(c.isalpha() for c in text)
        if not has_letter:
            return False
        
        # Содержит ли подозрительные числовые последовательности?
        if re.search(r'\d{3,}', text):  # 999 и более подряд
            return False
        
        # Содержит ли опасные символы?
        dangerous_chars = ['@', '#', '$', '%', '^', '&', '*', '|', '\\', '/']
        if any(c in text for c in dangerous_chars):
            return False
        
        return True
    
    def _contains_author_name(self, text: str) -> bool:
        """Проверить содержит ли текст имя автора (по двум уровням).
        
        Уровень 1: Быстрая проверка - есть ли известное имя в тексте
        Уровень 2: Полная проверка - соответствует ли текст паттернам имён
        
        Args:
            text: Текст для проверки (папка или имя файла)
            
        Returns:
            True если найдено имя, False иначе
        """
        # Уровень 1: Проверка по известным именам
        text_lower = text.lower()
        # ВАЖНО: Нормализировать диакритику! Жеребьёв → жеребьев
        text_normalized = self._normalize_diacritics(text_lower)
        
        words = re.split(r'[,\-\.\s«»()]+', text_normalized)
        
        for word in words:
            word_clean = word.strip()
            if word_clean and word_clean in self.author_names:
                return True
        
        # Уровень 2: Проверка по структурным паттернам
        for pattern_dict in self.author_name_patterns:
            pattern_desc = pattern_dict.get('pattern', '')
            regex = self._pattern_to_regex(pattern_desc)
            if regex and re.search(regex, text, re.IGNORECASE):
                return True
        
        return False
    
    def _pattern_to_regex(self, pattern_desc: str) -> Optional[str]:
        """Конвертировать описание паттерна имени в регулярное выражение.
        
        Args:
            pattern_desc: Description like "(Surname)" or "(Surname) (Name)"
            
        Returns:
            Regex pattern or None
        """
        # Маппинг описаний паттернов на regex
        patterns_map = {
            "(Name)": r'\b[A-ZА-Я][a-zа-я]{1,}\b',  # Одно слово с заглавной буквы
            "(Surname)": r'\b[A-ZА-Я][a-zа-я]{1,}\b',
            "(Surname) (Name)": r'\b[A-ZА-Я][a-zа-я]{1,}\s+[A-ZА-Я][a-zа-я]{1,}\b',
            "(Name) (Surname)": r'\b[A-ZА-Я][a-zа-я]{1,}\s+[A-ZА-Я][a-zа-я]{1,}\b',
            "(Surname) (Name) (Patronymic)": r'\b[A-ZА-Я][a-zа-я]{1,}\s+[A-ZА-Я][a-zа-я]{1,}\s+[A-ZА-Я][a-zа-я]{1,}\b',
            "(Surname) ((Name))": r'\b[A-ZА-Я][a-zа-я]{1,}\s*\([A-ZА-Я][a-zа-я]{1,}\)\b',
            "(Surname) (Initial). (Name)": r'\b[A-ZА-Я][a-zа-я]{1,}\s+[A-ZА-Я]\.?\s+[A-ZА-Я][a-zа-я]{1,}\b',
            "(N). (Surname)": r'\b[A-ZА-Я]\.?\s+[A-ZА-Я][a-zа-я]{1,}\b',
        }
        
        return patterns_map.get(pattern_desc)
    
    def _file_pattern_to_regex(self, pattern_desc: str) -> Optional[Tuple[str, List[str]]]:
        """Конвертировать описание паттерна файла в regex с группами.
        
        Args:
            pattern_desc: Description like "Author - Title" or "Author - Title (Series. service_words)"
            
        Returns:
            Tuple (regex_pattern, group_names) или None если не распознан
        """
        # Маппинг описаний паттернов файлов на regex с именованными группами
        patterns_map = {
            "(Author) - Title": (
                r'^\((?P<author>[^)]+)\)\s*-\s*(?P<title>.+)$',
                ['author', 'title']
            ),
            "Author - Title": (
                r'^(?P<author>.*?)\s*-\s*(?P<title>[^(]+)(?:\(.*\))?$',
                ['author', 'title']
            ),
            "Author. Title": (
                r'^(?P<author>[^.]+)\.\s*(?P<title>.+?)(?:\(.+\))?$',
                ['author', 'title']
            ),
            "Title (Author)": (
                r'^(?P<title>.*?)\s*\((?P<author>[^)]+)\)$',
                ['title', 'author']
            ),
            "Title - (Author)": (
                r'^(?P<title>.*?)\s*-\s*\((?P<author>[^)]+)\)$',
                ['title', 'author']
            ),
            "Author - Series.Title": (
                r'^(?P<author>.*?)\s*-\s*(?P<series>[^.]+)\.\s*(?P<title>.+)$',
                ['author', 'series', 'title']
            ),
            "Author. Series. Title": (
                r'^(?P<author>[^.]+)\.\s*(?P<series>[^.]+)\.\s*(?P<title>.+)$',
                ['author', 'series', 'title']
            ),
            "Author. Title. (Series)": (
                r'^(?P<author>[^.]+)\.\s*(?P<title>[^.]+)\.\s*\((?P<series>[^)]+)\)$',
                ['author', 'title', 'series']
            ),
            "Author - Title (Series. service_words)": (
                r'^(?P<author>[^-]+?)\s*-\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)(?:\s*-\s*.+)?$',
                ['author', 'title', 'series']
            ),
            "Author. Title (Series. service_words)": (
                r'^(?P<author>[^.]+)\.\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)$',
                ['author', 'title', 'series']
            ),
            "Author, Author - Title (Series. service_words)": (
                r'^(?P<author>[^-]+?\s*,\s*[^-]+?)\s*-\s*(?P<title>[^(]+?)\s*\((?P<series>[^)]+)\)(?:\s*-\s*.+)?$',
                ['author', 'title', 'series']
            ),
        }
        
        return patterns_map.get(pattern_desc)
    
    def _extract_author_from_filename_by_patterns(self, filename: str) -> Optional[str]:
        """Извлечь автора из имени файла, подбирая наиболее полное совпадение.
        
        Логика:
        1. Перебрать ВСЕ паттерны из author_series_patterns_in_files
        2. Найти ЛУЧШИЙ паттерн (с наибольшим количеством совпадающих групп)
        3. Извлечь группу 'author' из наиболее полного паттерна
        4. Проверить что это действительно имя автора (используя _contains_author_name)
        
        Приоритет: Паттерн с 3+ группами (author, title, series) > паттерн с 2 группами (author, title)
        
        Args:
            filename: Имя файла без расширения
            
        Returns:
            Имя автора или None
        """
        if not filename or not self.author_patterns:
            return None
        
        # Отслеживаем лучшее совпадение
        best_author = None
        best_group_count = 0
        
        # Перебрать ВСЕ паттерны и выбрать наиболее полный
        for pattern_dict in self.author_patterns:
            pattern_desc = pattern_dict.get('pattern', '')
            
            # Конвертировать описание в regex
            regex_data = self._file_pattern_to_regex(pattern_desc)
            if not regex_data:
                continue
            
            regex_pattern, group_names = regex_data
            
            # Попытаться совпростить с паттерном
            try:
                match = re.match(regex_pattern, filename, re.IGNORECASE)
                if match:
                    # Считаем сколько групп совпадало (сколько информации извлекли)
                    matched_groups = len([g for g in match.groups() if g is not None])
                    
                    # Если это лучше чем предыдущее совпадение - запомнить
                    if matched_groups > best_group_count:
                        author = match.group('author')
                        if author:
                            author = author.strip()
                            # Проверить что это действительно имя автора
                            # ПРИОРИТЕТ: 1) известное имя, 2) похоже на имя по структуре
                            if self._contains_author_name(author) or self._looks_like_author_name(author):
                                best_author = author
                                best_group_count = matched_groups
            except Exception:
                # Если проблема с regex - пропустить этот паттерн
                continue
        
        return best_author
    
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
            
            # Сортировка авторов по алфавиту если их несколько
            self._sort_authors_in_records()
            self.logger.log(f"✅ Авторы отсортированы по алфавиту")
            
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
        
        КРИТИЧНО: Проверяем что это действительно ИМЯ автора (не название папки/серии)
        
        Args:
            folder_name: Название папки
            
        Returns:
            Имя автора/авторов из папки, или "" если не найдено имя
        """
        # Сначала проверить есть ли содержимое в скобках
        # Паттерн: "название (содержимое)" - ищет ПОСЛЕДНИЕ скобки в строке
        # Используем [^)]* чтобы избежать несоответствия с вложенными скобками
        match = re.search(r'\(([^)]*)\)$', folder_name)
        
        if match:
            # Есть скобки с содержимым
            content = match.group(1)  # "А.Михайловский, А.Харников" или "Буланов Константин"
            
            # КРИТИЧНО: Проверить что это действительно содержит имя автора
            if not self._contains_author_name(content):
                # Содержимое в скобках - не имя автора (например "(1)" или "(2021)")
                # Вернём пустую строку чтобы обойти эту папку
                return ""
            
            # Если есть несколько авторов разделённых запятой
            if ',' in content:
                # Разбить на авторов
                authors = [a.strip() for a in content.split(',')]
                
                if len(authors) <= 2:
                    # <= 2 авторов - берём всех через '; ' (временный разделитель для PASS)
                    return '; '.join(authors)
                else:
                    # > 2 авторов - берём только первого
                    return authors[0]
            
            # Иначе просто один автор в скобках
            return content.strip()
        
        # Нет скобок - это обычно название папки/серии, не имя автора
        # Проверили - если это содержит имя автора используем, иначе пустая строка
        if self._contains_author_name(folder_name):
            # Может быть в формате "Имя Фамилия" без скобок
            return folder_name
        
        # Не имя - просто название папки/серии
        return ""
    
    def _clean_author_name(self, author_str: str) -> str:
        """Очистить имя автора от паразитных символов.
        
        Удаляет:
        - Точки в конце строки
        - Скобки и их содержимое (кроме скобок в составных именах)
        - Кавычки в начале/конце
        - Лишние пробелы
        - Запятые в конце
        
        Args:
            author_str: Строка с именем автора
            
        Returns:
            Очищенная строка
        """
        if not author_str:
            return ""
        
        try:
            # Уберём кавычки в начале и конце
            author_str = author_str.strip('«»"\'')
            
            # Уберём скобки с содержимым (для случаев типа "(Легион Живой,")
            # Но будем осторожны - оставляем скобки если это составное имя вроде "А.В. (составное)"
            author_str = re.sub(r'\s*\([^)]*\)\s*', ' ', author_str)
            
            # Уберём точку в конце (для "Метельский." → "Метельский")
            author_str = re.sub(r'\.$', '', author_str)
            
            # Уберём запятую в конце (для случаев типа "Николаев Злотников,")
            author_str = re.sub(r',$', '', author_str)
            
            # Нормализуем пробелы (несколько пробелов → один)
            author_str = re.sub(r'\s+', ' ', author_str)
            
            return author_str.strip()
        except Exception:
            return author_str
    
    def _process_and_expand_authors(self, cleaned_author: str, current_record, all_records) -> str:
        """Обработать авторов: разделить по запятым, расширить, убрать дубли.
        
        Алгоритм:
        1. Убрать дубликаты в исходной строке (например "Автор, Автор" → "Автор")
        2. Разбить по запятым на отдельных авторов
        3. Для каждого: расширить из metadata текущего файла
        4. Если не расширилось - искать в metadata соседних файлов из той же папки
        5. Убрать дубликаты авторов в результате
        6. Объединить с "; " разделителем
        
        Args:
            cleaned_author: Очищенное имя/имена авторов (может быть "Автор1, Автор2")
            current_record: Текущий CV record с metadata_authors
            all_records: Все records для поиска в соседних файлах
            
        Returns:
            Финальное имя автора в формате "ФИ" или "ФИ; ФИ"
        """
        if not cleaned_author:
            return ""
        
        # Шаг 0: Убрать дубликаты в исходной строке (например "Автор, Автор, Автор")
        # Разбиваем, удаляем дубли, и заново объединяем
        initial_parts = [a.strip() for a in cleaned_author.split(',') if a.strip()]
        seen_initial = set()
        unique_initial = []
        for part in initial_parts:
            if part not in seen_initial:
                unique_initial.append(part)
                seen_initial.add(part)
        
        if len(unique_initial) < len(initial_parts):
            # Были дубликаты в исходной строке - использовать очищенную версию
            cleaned_author = ", ".join(unique_initial)
        
        # Шаг 1: Разбить по запятым если есть несколько авторов
        author_parts = [a.strip() for a in cleaned_author.split(',') if a.strip()]
        
        # Шаг 2: Расширить каждого автора
        expanded_parts = []
        for part in author_parts:
            # Сначала пробуем расширить из metadata текущего файла
            expanded = self._expand_author_to_full_name(part, current_record.metadata_authors or "")
            
            # Если не получилось и это одно слово (фамилия) - ищем в соседних файлах
            if expanded == part and len(part.split()) == 1:  # Не расширилось
                # Ищем других файлов в той же папке или начинающихся с этого автора
                current_dir = str(Path(current_record.file_path).parent)
                
                for other_record in all_records:
                    if other_record.file_path == current_record.file_path:
                        continue  # Пропустить сам себя
                    
                    other_dir = str(Path(other_record.file_path).parent)
                    
                    # Если файлы в одной папке - пробуем его metadata
                    if other_dir == current_dir and other_record.metadata_authors:
                        found = self._expand_author_to_full_name(part, other_record.metadata_authors)
                        if found != part:  # Нашли!
                            expanded = found
                            break
            
            if expanded:
                expanded_parts.append(expanded)
        
        # Шаг 3: Убрать дубликаты авторов, сохраняя порядок
        unique_authors = []
        seen = set()
        for author in expanded_parts:
            if author not in seen:
                unique_authors.append(author)
                seen.add(author)
        
        # Шаг 3.5: Отсортировать авторов по алфавиту
        unique_authors.sort()
        
        # Шаг 4: Объединить с разделителем "; "
        if not unique_authors:
            return cleaned_author
        
        return "; ".join(unique_authors)
    
    def _expand_author_to_full_name(self, partial_author: str, metadata_authors: str) -> str:
        """Расширить partial author name до полного формата "Фамилия Имя" используя metadata.
        
        Логика:
        - Если одно слово (только фамилия) → найти в metadata и вернуть полное имя
        - Если 2 слова → проверить, совпадает ли с metadata author. Если нет → попытаться разобрать как несколько авторов
        - Если 2+ слова и совпадает с metadata → вернуть как есть
        
        Args:
            partial_author: Извлечённое имя автора (может быть incomplete)
            metadata_authors: Полные авторы из metadata FB2
            
        Returns:
            Полное имя в формате "Фамилия Имя"
        """
        if not partial_author or not metadata_authors:
            return partial_author
        
        try:
            words = partial_author.split()
            metadata_authors_list = [a.strip() for a in re.split(r'[;,]', metadata_authors) if a.strip()]
            
            # Проверка 1: Одно слово - это фамилия, найти полное имя в metadata
            if len(words) == 1:
                surname = words[0]
                matching_authors = []  # Собираем всех авторов с этой фамилией
                
                for full_name in metadata_authors_list:
                    full_lower = full_name.lower()
                    surname_lower = surname.lower()
                    
                    # Проверяем в конце (обычный порядок Фамилия Имя)
                    if full_lower.endswith(surname_lower) or full_lower.startswith(surname_lower):
                        matching_authors.append(full_name)
                    # Или может быть фамилия прямо в имени
                    elif surname_lower in full_lower.split():
                        matching_authors.append(full_name)
                
                # Если нашли авторов - вернуть их
                if matching_authors:
                    if len(matching_authors) == 1:
                        return matching_authors[0]
                    else:
                        # Несколько авторов с одинаковой фамилией
                        # Отсортировать для стабильности и объединить через "; "
                        matching_authors.sort()
                        return "; ".join(matching_authors)
                
                # Если не нашли - вернуть как есть
                return partial_author
            
            # Проверка 2: Несколько слов - проверить совпадает ли с metadata
            if len(words) >= 2:
                partial_lower = partial_author.lower()
                
                # Проверяем, совпадает ли это с одним из metadata authors
                for full_name in metadata_authors_list:
                    full_lower = full_name.lower()
                    full_name_words = full_name.split()
                    
                    # Точное совпадение?
                    if partial_lower == full_lower:
                        return partial_author
                    
                    # НОВОЕ: Проверка если одни и те же слова в разном порядке?
                    # (например "Тё Илья" vs "Илья Тё" - одни и те же слова)
                    partial_words_set = set(w.lower() for w in words)
                    full_name_words_set = set(w.lower() for w in full_name_words)
                    if (len(words) == len(full_name_words) and 
                        partial_words_set == full_name_words_set):
                        # Одни и те же слова, только в разном порядке
                        # Поскольку filename обычно надёжнее metadata, оставляем partial_author
                        return partial_author
                    
                    # Может быть это обратный порядок? (Живой Алексей vs Алексей Живой)
                    if partial_author in full_name or full_name in partial_author:
                        # ВАЖНО: если partial_author содержит больше информации (больше слов),
                        # чем full_name, то оставить partial_author как более полную версию
                        # Пример: partial="Иванов Дмитрий", full_name="Дмитрий"
                        # Иванов Дмитрий содержит Дмитрий, но имеет больше информации
                        if len(words) > len(full_name_words):
                            return partial_author  # Более полная версия из filename
                        else:
                            return full_name  # Более полная версия из metadata
                
                # Если это 2 слова но НЕ совпадает ни с одним metadata author,
                # это вероятно НЕСКОЛЬКО авторов (типа "Прозоров Живой" = автор1 + автор2)
                # Попробуем найти каждое слово как отдельную фамилию
                if len(words) == 2:
                    found_authors = []
                    for word in words:
                        for full_name in metadata_authors_list:
                            full_lower = full_name.lower()
                            word_lower = word.lower()
                            # Ищем это слово в metadata authors
                            if full_lower.endswith(word_lower) or full_lower.startswith(word_lower) or word_lower in full_lower.split():
                                found_authors.append(full_name)
                                break
                    
                    # Если нашли 2 одинаковых автора - вернуть одного
                    if len(found_authors) == 2:
                        if found_authors[0] == found_authors[1]:
                            return found_authors[0]
                        else:
                            return "; ".join(found_authors)
                    elif len(found_authors) == 1:
                        # Нашли только одного из двух - вернуть его
                        return found_authors[0]
                
                # Если ничего не совпало - вернуть как есть
                return partial_author
            
            return partial_author
        except Exception:
            return partial_author
    
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
        """PASS 2: Извлечение авторов из имён файлов/папок с кешированием.
        
        ОПТИМИЗАЦИЯ: Папки парсятся один раз и кешируются для всех файлов внутри них.
        
        Для файлов, не определённых в PASS 1 (не folder_dataset):
        1. Ищем автора в скобках в пути файла
        2. Проверяем если это сборник (маркеры в имени + авторов > 2)
        3. Если сборник - устанавливаем "Сборник", иначе применяем извлечённого автора
        
        Пропускаем файлы с author_source="folder_dataset" - они уже определены.
        """
        print("\n" + "="*80, flush=True)
        print("📄 PASS 2: Извлечение авторов из имён файлов и папок...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 2] Начало извлечения авторов из имён файлов/папок...")
        
        # КЕШИРОВАНИЕ ПАПОК: Для каждой уникальной папки парсим один раз
        # Ключ: полный путь папки, Значение: извлечённый автор
        folder_cache = {}
        
        extracted_count = 0
        collection_count = 0
        
        for record in self.records:
            # Пропустить файлы с folder_dataset - они уже определены надёжно
            if record.author_source == "folder_dataset":
                continue
            
            # Проверить если это сборник по имени файла
            file_name = Path(record.file_path).stem  # имя файла без расширения
            
            # Считаем количество авторов в metadata
            author_count = 0
            if record.metadata_authors and record.metadata_authors not in ("Сборник", "[неизвестно]"):
                # Считаем авторов (разделены на ; или ,)
                author_count = max(
                    record.metadata_authors.count(';') + 1,
                    record.metadata_authors.count(',') + 1
                )
            
            # Проверить если файл - сборник
            if self.extractor.is_anthology(file_name, author_count):
                record.proposed_author = "Сборник"
                record.author_source = "filename"
                collection_count += 1
                continue
            
            # Не сборник - попытаться найти автора в пути файла
            # ПРИОРИТЕТ: имя_файла → папки
            
            # Сначала попробовать извлечь из ИМЕНИ ФАЙЛА по паттернам
            extracted_author = self._extract_author_from_filename_by_patterns(file_name)
            
            if extracted_author:
                # Успешно извлекли из имени файла
                # Шаг 1: Очистить от паразитных символов
                cleaned_author = self._clean_author_name(extracted_author)
                
                # Шаг 2: Обработать несколько авторов и убрать дубликаты
                final_author = self._process_and_expand_authors(cleaned_author, record, self.records)
                
                record.proposed_author = final_author
                record.author_source = "filename"
                extracted_count += 1
                continue
            
            # Если в имени файла не нашлось - проверить папки
            # Используем кеш для избежания повторного парсинга одной папки
            file_path = Path(record.file_path)
            
            # Проверить все части пути, начиная с самой близкой к файлу (справа)
            # Идём вверх по иерархии папок
            parts_to_check = []
            
            # Затем все папки в пути (от листа к корню)
            for parent in file_path.parents:
                parts_to_check.append(str(parent))
            
            # Попытаться парсить каждую папку, используя кеш
            parsed_author = None
            for folder_path in parts_to_check:
                # Проверить кеш
                if folder_path in folder_cache:
                    parsed_author = folder_cache[folder_path]
                    if parsed_author and parsed_author != "Сборник":
                        break  # Нашли в кеше - используем
                else:
                    # Парсим папку в первый раз и кешируем результат
                    folder_name = Path(folder_path).name
                    parsed_author = self._parse_author_from_folder_name(folder_name)
                    folder_cache[folder_path] = parsed_author  # Кешируем результат
                    
                    if parsed_author and parsed_author != "Сборник":
                        break  # Нашли - используем этого автора
            
            # Если найдено в папке - применить
            if parsed_author and parsed_author != "Сборник":
                record.proposed_author = parsed_author
                record.author_source = "filename"
                extracted_count += 1
        
        print(f"✅ PASS 2 завершён: {extracted_count} авторов + {collection_count} сборников извлечено\n", flush=True)
        print(f"   Кешировано папок: {len(folder_cache)}\n", flush=True)
        self.logger.log(f"[PASS 2] Извлечено {extracted_count} авторов и {collection_count} сборников (кеш: {len(folder_cache)} папок)")
    
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
    
    def _sort_authors_in_records(self) -> None:
        """Отсортировать авторов по алфавиту если их несколько (разделены запятой).
        
        Проходит по всем records и сортирует proposed_author если содержит несколько авторов.
        Разделитель предполагается запятая с пробелом ", ".
        """
        for record in self.records:
            if not record.proposed_author or record.proposed_author in ("Сборник", "[неизвестно]"):
                continue
            
            # Проверить есть ли запятая (несколько авторов)
            if ',' in record.proposed_author:
                # Разбить по запятой
                authors = [a.strip() for a in record.proposed_author.split(',')]
                
                # Убрать пустые
                authors = [a for a in authors if a]
                
                if len(authors) > 1:
                    # Отсортировать по алфавиту
                    authors.sort()
                    # Объединить обратно с запятой
                    record.proposed_author = ", ".join(authors)
    
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
