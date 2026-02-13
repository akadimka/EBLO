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
        
        # Загрузить паттерны извлечения авторов из названий ПАПОК
        self.folder_patterns = self._load_folder_patterns()
        
        # Загрузить список известных имён авторов (для проверки наличия имени)
        self.author_names = self._load_author_names()
        
        # Загрузить паттерны распознавания структуры имён
        self.author_name_patterns = self._load_author_name_patterns()
    
    def _load_author_patterns(self) -> List[Dict]:
        """Загрузить паттерны извлечения авторов из имён ФАЙЛОВ.
        
        Returns:
            List of pattern dicts with 'pattern' key
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            patterns = config_data.get('author_series_patterns_in_files', [])
            return patterns if patterns else []
        except Exception as e:
            self.logger.log(f"⚠️ Ошибка загрузки паттернов авторов в файлах: {e}")
            return []
    
    def _load_folder_patterns(self) -> List[Dict]:
        """Загрузить паттерны извлечения авторов из имён ПАПОК.
        
        Returns:
            List of pattern dicts with 'pattern' key
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            patterns = config_data.get('author_series_patterns_in_folders', [])
            return patterns if patterns else []
        except Exception as e:
            self.logger.log(f"⚠️ Ошибка загрузки паттернов авторов в папках: {e}")
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
        
        words = re.split(r'[,\-\.\s«»();]+', text_normalized)
        
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
    
    def _folder_pattern_to_regex(self, pattern_desc: str) -> Optional[Tuple[str, List[str]]]:
        """Конвертировать описание паттерна ПАПКИ в regex с группами.
        
        Args:
            pattern_desc: Description like "(Surname) (Name)" или "Author - Folder Name" или "Series (Author)"
            
        Returns:
            Tuple (regex_pattern, group_names) или None если не распознан
        """
        # Маппинг описаний паттернов папок на regex с именованными группами
        patterns_map = {
            "Author, Author": (
                r'^(?P<author>[^,]+?)\s*,\s*(?P<author2>.+)$',
                ['author', 'author2']
            ),
            "(Surname) (Name)": (
                r'^(?P<author>\S+)\s+(?P<author2>\S+)$',
                ['author', 'author2']
            ),
            "Author - Folder Name": (
                r'^(?P<author>[^-]+?)\s*-\s*(?P<folder_name>.+)$',
                ['author', 'folder_name']
            ),
            "Series (Author)": (
                r'^(?P<series>[^(]+?)\s*\((?P<author>[^)]+)\)$',
                ['series', 'author']
            ),
            "(Series) Author": (
                r'^\((?P<series>[^)]+)\)\s*(?P<author>.+)$',
                ['series', 'author']
            ),
            "Series": (
                r'^(?P<series>.+)$',
                ['series']
            ),
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
            "Author, Author. Title": (
                r'^(?P<author>[^.]+\s*,\s*[^.]+)\.\s*(?P<title>.+?)(?:\(.+\))?$',
                ['author', 'title']
            ),
            "Author, Author. Title. (Series)": (
                r'^(?P<author>[^.]+\s*,\s*[^.]+)\.\s*(?P<title>[^.]+)\.\s*\((?P<series>[^)]+)\)$',
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
        best_pattern_desc = None
        
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
                            
                            # СТРОГАЯ ВАЛИДАЦИЯ: автор должен содержать известные слова авторов
                            # Это предотвращает ложное извлечение названий серий или описаний
                            has_known_author_words = self._contains_author_name(author)
                            looks_like_author_structurally = self._looks_like_author_name(author)
                            is_blacklisted = self._looks_like_series_name(author)  # Проверка blacklist И серийности
                            
                            # ВАЖНО: Требуем чтобы ЛИБО:
                            # 1. Автор содержит известные авторские слова (высокая уверенность)
                            #    ИТо НЕ содержит blacklist слова вроде "Сборник", "СССР" и т.д.
                            # 2. Структурно выглядит как имя И не похож на серию/описание
                            
                            should_accept = False
                            
                            # ⚠️ КРИТИЧНО: Сначала проверяем БЕЗ blacklist слов!
                            if is_blacklisted:
                                # Содержит blacklist слова или похоже на серию → отвергаем
                                should_accept = False
                            elif has_known_author_words:
                                # У нас есть известные авторские слова И нет blacklist слов
                                should_accept = True
                            elif looks_like_author_structurally:
                                # Структурно похоже на имя И не похоже на серию/описание
                                should_accept = True
                            
                            if not should_accept:
                                # Автор не прошел валидацию - пропустить этот паттерн
                                continue
                            
                            # ПРОШЛА ВАЛИДАЦИЯ! Сохранить как лучший результат
                            best_author = author
                            best_group_count = matched_groups
                            best_pattern_desc = pattern_desc
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
            print("\n" + "="*80, flush=True)
            print("\n  CSV REGENERATION - 6-PASS SYSTEM", flush=True)
            print(f"  Work folder: {self.work_dir}\n", flush=True)
            print("="*80 + "\n", flush=True)
            
            self.logger.log("=== Starting CSV regeneration ===")
            
            # PASS 1: Инициализация - чтение FB2 файлов и определение авторов
            self._pass1_read_fb2_files()
            if not self.records:
                self.logger.log("[X] No FB2 files found")
                return False
            
            self.logger.log(f"[OK] PASS 1: Read {len(self.records)} files")
            
            # PASS 2: Extract authors from filename
            self._pass2_extract_from_filename()
            self.logger.log(f"[OK] PASS 2: Authors extracted from filenames")
            
            # PASS 2 Fallback: Если после PASS 1 + PASS 2 proposed_author еще пуст, используем metadata
            self._pass2_fallback_to_metadata()
            self.logger.log(f"[OK] PASS 2 Fallback: Metadata applied for remaining records")
            
            # PASS 3: Normalize author names
            self._pass3_normalize_authors()
            self.logger.log(f"[OK] PASS 3: Authors normalized")
            
            # PASS 4: Apply consensus
            self._pass4_apply_consensus()
            self.logger.log(f"[OK] PASS 4: Consensus applied")
            
            # PASS 5: Re-apply conversions
            self._pass5_apply_conversions()
            self.logger.log(f"[OK] PASS 5: Conversions re-applied")
            
            # PASS 6: Expand abbreviations
            self._pass6_expand_abbreviations()
            self.logger.log(f"[OK] PASS 6: Abbreviations expanded")
            
            # Sort authors alphabetically when there are multiple
            self._sort_authors_in_records()
            self.logger.log(f"[OK] Authors sorted alphabetically")
            
            # Sort records: single files alphabetically, then folders alphabetically
            self._sort_records()
            self.logger.log(f"[OK] Records sorted")
            
            # Сохранение в CSV
            csv_path = output_csv or self._get_output_csv_path()
            self._save_csv(csv_path)
            
            self.logger.log(f"[OK] CSV saved: {csv_path}")
            self.logger.log("=== Regeneration completed successfully ===")
            
            # Final output
            print("="*80, flush=True)
            print("[OK] REGENERATION COMPLETED SUCCESSFULLY!", flush=True)
            print("="*80 + "\n", flush=True)
            
            return True
            
        except Exception as e:
            self.logger.log(f"❌ Ошибка при регенерации: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _parse_author_from_folder_name(self, folder_name: str) -> str:
        """Распарсить автора из названия папки, подбирая наиболее полное совпадение.
        
        Логика (АНАЛОГИЧНО _extract_author_from_filename_by_patterns):
        1. Перебрать ВСЕ паттерны из author_series_patterns_in_folders
        2. Найти ЛУЧШИЙ паттерн (с наибольшим количеством совпадающих групп)
        3. Извлечь группу 'author' из наиболее полного паттерна
        4. Проверить что это действительно имя автора (используя _contains_author_name)
        5. ФИЛЬТР: Отклонить если это просто описание (типа "Другой мир", "Парижский отдел")
        
        Поддерживаемые форматы:
        - "Максим Шаттам" (просто имя)
        - "Максим Шаттам - Собрание сочинений" (автор перед дефисом)
        - "Защита Периметра (Абенд Эдвард)" (автор в скобках)
        - "(Боевой отряд) Петров И." (автор после скобок)
        
        Args:
            folder_name: Название папки
            
        Returns:
            Имя автора из папки, или "" если не найдено имя
        """
        if not folder_name or not self.folder_patterns:
            return ""
        
        # Отслеживаем лучшее совпадение
        best_author = ""
        best_group_count = 0
        
        # Перебрать ВСЕ паттерны и выбрать наиболее полный
        for pattern_dict in self.folder_patterns:
            pattern_desc = pattern_dict.get('pattern', '')
            
            # Конвертировать описание в regex
            regex_data = self._folder_pattern_to_regex(pattern_desc)
            if not regex_data:
                continue
            
            regex_pattern, group_names = regex_data
            
            # Попытаться совпоставить с паттерном
            try:
                match = re.match(regex_pattern, folder_name, re.IGNORECASE)
                if match:
                    # Проверяем есть ли группа 'author' в этом паттерне
                    if 'author' not in group_names:
                        continue  # Этот паттерн не имеет автора (например "Series")
                    
                    # Считаем сколько групп совпадало (сколько информации извлекли)
                    matched_groups = len([g for g in match.groups() if g is not None])
                    
                    # Если это лучше чем предыдущее совпадение - запомнить
                    if matched_groups > best_group_count:
                        author = match.group('author')
                        if author:
                            author = author.strip()
                            
                            # НОВОЕ: Проверить есть ли второй автор (для папок типа "Author1, Author2" или "(Surname) (Name)")
                            if 'author2' in group_names and match.group('author2'):
                                author2 = match.group('author2').strip()
                                
                                pattern_name = pattern_dict.get('pattern', '')
                                
                                # Для паттерна "(Surname) (Name)" - проверить что оба слова похожи на авторские
                                if pattern_name == "(Surname) (Name)":
                                    # Оба слова должны быть похожи на имена/фамилии
                                    # Либо оба содержать известные авторские слова, либо оба - капитализированные
                                    author_looks_like_name = (
                                        self._contains_author_name(author) or 
                                        self._looks_like_author_name(author)
                                    )
                                    author2_looks_like_name = (
                                        self._contains_author_name(author2) or 
                                        self._looks_like_author_name(author2)
                                    )
                                    
                                    # Если оба слова похожи на авторские - это вероятно Фамилия Имя
                                    if not (author_looks_like_name and author2_looks_like_name):
                                        # Одно или оба слова не похожи на авторские - пропустить
                                        continue
                                    
                                    # Это ОДН автор в двух словах - объединяем с ПРОБЕЛОМ
                                    author = author + " " + author2  # "Волков Тим" (один автор)
                                else:
                                    # Для других паттернов (Author, Author) - это два разных автора
                                    # Логика восстановления полного ФИ для второго автора
                                    # Если author2 - только одно слово (имя), добавить фамилию из author1
                                    author2_words = author2.split()
                                    if len(author2_words) == 1:
                                        # author2 - только имя, добавить фамилию из author
                                        author_words = author.split()
                                        if author_words:
                                            # Фамилия обычно первое слово в формате "Фамилия Имя"
                                            surname = author_words[0]
                                            author2 = surname + " " + author2  # "Белаш Людмила"
                                    
                                    # Объединить двух авторов через ";"
                                    author = author + "; " + author2  # Разные авторы
                            
                            # Проверить что это действительно имя автора
                            # ПРИОРИТЕТ: 1) известное имя, 2) похоже на имя по структуре
                            if self._contains_author_name(author) or self._looks_like_author_name(author):
                                # DEBUG
                                if folder_name.startswith("Белаш") or folder_name.startswith("Бирюков"):
                                    self.logger.log(f"[DEBUG] Author passed validation: {author}")
                                
                                # ДОПОЛНИТЕЛЬНЫЙ ФИЛЬТР: Проверить не это ли просто описание?
                                # "Другой мир" vs "Максим Шаттам" - первое это описание, второе имя
                                # Эвристит: если слова не в known_authors И совпадает с blacklist - это описание
                                if self._looks_like_series_name(author):
                                    # Это похоже на название серии/описание, а не имя автора
                                    if folder_name.startswith("Белаш") or folder_name.startswith("Бирюков"):
                                        self.logger.log(f"[DEBUG] Author looks like series, skipping: {author}")
                                    continue
                                
                                best_author = author
                                best_group_count = matched_groups
            except Exception:
                # Если проблема с regex - пропустить этот паттерн
                continue
        
        return best_author
    
    def _looks_like_series_name(self, text: str) -> bool:
        """Проверить похоже ли это на название серии, а не имя автора.
        
        Эвристики:
        - Содержит слова из blacklist (названия папок, серий) - проверяем ЦЕЛЫЕ СЛОВА
        - Все слова известные нарицательные (не имена собственные)
        - Совпадает с существующими серийными паттернами
        
        ⚠️ ВАЖНО: Одно слово (фамилия вроде "Жеребьёв") НЕ должно автоматически считаться серией!
        
        Args:
            text: Текст для проверки
            
        Returns:
            True если похоже на серию, False если на автора
        """
        if not text:
            return False
        
        blacklist = self.settings.get_filename_blacklist()
        text_words = [w.lower() for w in text.split()]  # Разбиваем на слова
        
        # Проверить сколько ЦЕЛЫХ СЛОВ из blacklist содержится
        # ВАЖНО: проверяем целые слова, не подстроки!
        # Пример: "логин" в blacklist НЕ должно исключать "Логинов"
        blacklist_word_count = 0
        for word in blacklist:
            if word.lower() in text_words:  # ← Проверяем целое слово в списке слов
                blacklist_word_count += 1
        
        # Если много слов blacklist - это серия/описание
        if blacklist_word_count >= 1:
            return True
        
        # Проверить слова в author_names
        words_in_author_names = sum(1 for w in text_words if w in self.author_names)
        
        # ⚠️ ИСПРАВЛЕНО: Одно слово с капиталом может быть фамилией, не серией!
        # Проверяем ТОЛЬКО для 2-3 слов из общих (нецентральных) слов
        # ИСКЛЮЧАЕМ: одно слово (фамилия "Жеребьёв", "Иванов", etc)
        if words_in_author_names == 0 and 2 <= len(text_words) <= 3:
            # Типа "Другой мир", "Парижский отдел" - общие русские слова, не имена
            # Срабатывает ТОЛЬКО для 2-3 слов, НЕ для одного (фамилий)
            return True
        
        return False
    
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
    
    def _normalize_surname_endings(self, surname: str) -> str:
        """Нормализовать окончания русских фамилий для сравнения.
        
        Удаляет типичные окончания русских фамилий чтобы получить корень:
        - Каменские → Каменск (множественное число)
        - Каменский → Каменск (мужское)
        - Каменская → Каменск (женское)
        - Кольцкие → Кольц
        - Кольцкий → Кольц
        - Кольцкая → Кольц
        
        Args:
            surname: Фамилия с окончанием
            
        Returns:
            Фамилия с удаленным окончанием (корень)
        """
        if not surname:
            return surname
        
        # Типичные окончания русских фамилий в порядке специфичности
        # (более специфичные в начале)
        patterns = [
            (r'ские$', ''),   # Каменские → Каменск
            (r'ский$', ''),   # Каменский → Каменск
            (r'ская$', ''),   # Каменская → Каменск
            (r'цкие$', ''),   # Кольцкие → Кольц
            (r'цкий$', ''),   # Кольцкий → Кольц
            (r'цкая$', ''),   # Кольцкая → Кольц
        ]
        
        normalized = surname
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
            # Если что-то заменилось - возвращаем сразу (не применяем больше паттернов)
            if normalized != surname:
                return normalized
        
        return surname
    
    def _extract_surname_from_fullname(self, full_name: str) -> str:
        """Извлечь фамилию из полного имени, проверяя каждое слово против known_names.
        
        Логика: 
        1. Разбиваем имя на слова
        2. Ищем какое слово есть в known_names (это имя)
        3. Остальные слова = фамилия
        4. Работает для любого порядка: "Юрий Каменский" и "Каменский Юрий"
        5. Инициалы (А.В.) не считаются за имена
        
        Пример:
        - "Юрий Каменский" → фамилия = "Каменский"
        - "Каменский Юрий" → фамилия = "Каменский"
        - "А.В. Чехов" → фамилия = "Чехов" (А.В. - инициалы, игнорируются)
        - "Чехов А.В." → фамилия = "Чехов"
        - "Чехов" → фамилия = "Чехов" (если не найдено имён)
        
        Args:
            full_name: Полное имя вроде "Юрий Каменский"
            
        Returns:
            Фамилия или исходное имя если не смогли разобрать
        """
        if not full_name:
            return full_name
        
        words = full_name.split()
        if len(words) <= 1:
            return full_name  # Одно слово - оставляем как есть
        
        # Ищем какое слово есть в known_names (КРОМЕ инициалов)
        found_name_words = []
        
        for i, word in enumerate(words):
            word_lower = word.lower()
            
            # Пропускаем инициалы (А, А., В., А.В., А.В.М., и т.п.)
            # Инициалы: только буквы и точки, максимум 3 буквы
            letter_count = sum(1 for c in word_lower if c.isalpha())
            punct_count = word_lower.count('.')
            
            # Если это похоже на инициалы (мало букв, много точек относительно букв)
            if letter_count <= 3 and punct_count >= letter_count - 1 and '.' in word_lower:
                continue  # Это инициалы, не считаем
            
            word_clean = re.sub(r'[^\w]', '', word_lower)  # Удаляем пунктуацию
            
            if word_clean and word_clean in self.author_names:
                # Нашли известное имя - добавляем индекс этого слова
                found_name_words.append(i)
        
        # Если нашли известное имя - остальное = фамилия
        if found_name_words:
            # Собираем остальные слова как фамилию
            surname_words = [word for i, word in enumerate(words) if i not in found_name_words]
            if surname_words:
                return ' '.join(surname_words)
        
        # Если не нашли в known_names - используем последнее слово как фамилию
        # (это мало вероятно, но имеет смысл для неизвестных авторов)
        if len(words) >= 2:
            # Удаляем инициалы (А, А., В., А.В., и т.п.)
            non_initial_words = []
            for w in words:
                w_lower = w.lower()
                letter_count = sum(1 for c in w_lower if c.isalpha())
                punct_count = w_lower.count('.')
                # Если это НЕ инициалы - добавляем
                if not (letter_count <= 3 and punct_count >= letter_count - 1 and '.' in w_lower):
                    non_initial_words.append(w)
            
            if len(non_initial_words) >= 1:
                # Если есть слова кроме инициалов - последнее из них = фамилия
                return non_initial_words[-1]
        
        return full_name
    
    def _expand_author_to_full_name(self, partial_author: str, metadata_authors: str) -> str:
        """Расширить partial author name до полного формата "Фамилия Имя" используя metadata.
        
        Логика:
        - Если одно слово (только фамилия) → найти в metadata и вернуть полное имя
        - Если 2 слова → проверить, совпадает ли с metadata author. Если нет → попытаться разобрать как несколько авторов
        - Если 2+ слова и совпадает с metadata → вернуть как есть
        
        Поддерживает нюансы русских фамилий:
        - "Каменские" (множественное число) → совпадает с "Каменский" и "Каменская"
        
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
                
                # Нормализуем фамилию из filename (может быть "Каменские")
                surname_normalized = self._normalize_surname_endings(surname)
                
                for full_name in metadata_authors_list:
                    full_lower = full_name.lower()
                    surname_lower = surname.lower()
                    surname_normalized_lower = surname_normalized.lower()
                    
                    # Извлекаем фамилию из полного имени, правильно обрабатывая разные порядки слов
                    # "Юрий Каменский" → фамилия = "Каменский"
                    # "Каменский Юрий" → фамилия = "Каменский"
                    metadata_surname = self._extract_surname_from_fullname(full_name)
                    metadata_surname_lower = metadata_surname.lower()
                    metadata_surname_normalized = self._normalize_surname_endings(metadata_surname)
                    metadata_surname_normalized_lower = metadata_surname_normalized.lower()
                    
                    # Проверяем разные варианты совпадения:
                    # 1. Точное совпадение фамилий
                    if surname_lower == metadata_surname_lower:
                        matching_authors.append(full_name)
                    # 2. Совпадение нормализованных корней (Каменские == Каменский + Каменская)
                    elif surname_normalized_lower == metadata_surname_normalized_lower:
                        matching_authors.append(full_name)
                    # 3. Старая логика - для остальных случаев
                    elif full_lower.endswith(surname_lower) or full_lower.startswith(surname_lower):
                        matching_authors.append(full_name)
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
        
        Логика:
        1. Для каждой TOP-LEVEL папки (прямых подпапок work_dir) 
        2. Найти первый FB2 файл и идти вверх по иерархии от этого файла
        3. Если найдено имя АВТОРА (не серии) - это авторская папка
        4. Все подпапки авторской папки считаются папками серий
        
        Оптимизация: использует многопоточность для параллельного парсинга папок.
        
        ВАЖНО: Не используем folder_parse_limit - проверяем ВСЕ top-level папки!
        folder_parse_limit применяется в PASS 2 для файлов.
        
        Returns:
            Dict[Path, str]: Словарь {папка_путь: имя_автора}
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        folder_authors = {}
        folder_authors_lock = threading.Lock()  # Для потокобезопасного доступа
        
        try:
            # Найти все TOP-LEVEL папки (прямые подпапки work_dir)
            top_level_dirs = sorted([d for d in self.work_dir.iterdir() if d.is_dir()])
            
            # Использовать многопоточность если папок много (>10)
            use_threading = len(top_level_dirs) > 10
            
            if use_threading:
                # МНОГОПОТОЧНЫЙ режим для больших датасетов
                max_workers = min(4, len(top_level_dirs))  # Не более 4 потоков
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(self._parse_single_top_level_dir, top_dir, folder_authors_lock): top_dir 
                        for top_dir in top_level_dirs
                    }
                    
                    for future in as_completed(futures):
                        result = future.result()
                        if result:
                            with folder_authors_lock:
                                folder_authors.update(result)
            else:
                # ОДНОПОТОЧНЫЙ режим для маленьких датасетов (быстрее из-за отсутствия overhead)
                for top_dir in top_level_dirs:
                    result = self._parse_single_top_level_dir(top_dir, folder_authors_lock)
                    if result:
                        folder_authors.update(result)
        
        except Exception as e:
            self.logger.log(f"[Структура] Ошибка при построении структуры папок: {e}")
        
        self.logger.log(f"[Структура] Найдено авторских папок: {len(folder_authors)}")
        return folder_authors
    
    def _parse_single_top_level_dir(self, top_dir: Path, folder_authors_lock) -> Dict[Path, str]:
        """Парсить одну top-level папку и найти все авторские папки (прямые подпапки).
        
        Логика:
        1. СНАЧАЛА проверить сам top_dir - парсится ли как автор? Если да - добавить
        2. Если top_dir не автор - итерировать ВСЕ его прямые подпапки (не рекурсивно)
        3. Для каждой подпапки - применить conversions
        4. Парсить название папки - если парсится как автор - это авторская папка
        5. Добавить в результат
        
        Args:
            top_dir: Одна из top-level папок (контейнер для всех авторов)
            folder_authors_lock: Lock для потокобезопасного доступа
            
        Returns:
            Dict со найденными авторскими папками {папка: название_автора}
        """
        result = {}
        
        try:
            conversions = self.settings.get_author_surname_conversions()
            
            # ЭТАП 1: Проверить сам top_dir - это авторская папка?
            top_dir_name = top_dir.name
            top_dir_name_to_parse = conversions.get(top_dir_name, top_dir_name)
            top_author = self._parse_author_from_folder_name(top_dir_name_to_parse)
            
            if top_author:
                # Сам top_dir это авторская папка!
                result[top_dir] = top_author
            else:
                # ЭТАП 2: top_dir не авторская папка - проверить его подпапки
                # Это папки авторов или контейнеры серий
                direct_subdirs = sorted([d for d in top_dir.iterdir() if d.is_dir()])
                
                for subdir in direct_subdirs:
                    folder_name = subdir.name
                    
                    # Применить конвертацию к названию папки
                    # Например: "Гоблин (MeXXanik)" → "Гоблин MeXXanik"
                    folder_name_to_parse = conversions.get(folder_name, folder_name)
                    
                    # Проверить: парсится ли это как автор?
                    author_name = self._parse_author_from_folder_name(folder_name_to_parse)
                    
                    if author_name:
                        # Нашли авторскую папку!
                        result[subdir] = author_name
        
        except Exception as e:
            self.logger.log(f"[Структура] Ошибка при парсинге {top_dir}: {e}")
        
        return result
    
    def _contains_known_author_words(self, text: str) -> bool:
        """Проверить содержит ли текст слова из списка известных авторов.
        
        Это повышает уверенность, что найденное имя - это действительно автор, 
        а не случайное название серии.
        
        Args:
            text: Текст для проверки
            
        Returns:
            True если найдены известные авторские слова, False иначе
        """
        text_lower = text.lower()
        # Нормализировать диакритику (Жеребьёв → жеребьев)
        text_normalized = self._normalize_diacritics(text_lower)
        
        # Разбить на слова
        words = re.split(r'[,\-\.\s«»();]+', text_normalized)
        
        # Проверить: найдены ли известные авторские слова?
        for word in words:
            word_clean = word.strip()
            if word_clean and word_clean in self.author_names:
                return True
        
        return False
    
    def _get_author_for_file(self, fb2_file: Path, folder_authors: Dict[Path, str], metadata_authors: str = "") -> tuple:
        """Определить автора для конкретного файла, идя вверх по иерархии папок.
        
        Алгоритм:
        1. Начинаем с папки файла
        2. Проверяем эту папку - парсится ли как автор?
        3. ВАЖНО: Если найденное имя есть в metadata_authors → это подтверждение, что это автор!
        4. Если нет metadata - применяем фильтры (серия / не серия)
        5. Если да - это авторская папка, возвращаем автора (source='folder_dataset')
        6. Если нет - идем на уровень вверх
        7. Повторяем до folder_parse_limit или пока не найдем авторскую папку
        8. Если авторская папка не найдена - используем resolve_author_by_priority
        
        Args:
            fb2_file: путь к FB2 файлу
            folder_authors: словарь авторских папок из _build_folder_structure() (не используется)
            metadata_authors: строка авторов из метаданных FB2 (разделены '; ')
            
        Returns:
            (author, source) где source in ['folder_dataset', 'filename', 'metadata', '']
        """
        conversions = self.settings.get_author_surname_conversions()
        
        # Разбить metadata_authors на отдельные значения для проверки
        metadata_authors_list = []
        if metadata_authors and metadata_authors != "[неизвестно]":
            # Разбить по "; " и по ","
            metadata_authors_list = [
                a.strip() for a in re.split(r'[;,]', metadata_authors) 
                if a.strip() and a.strip() != "[неизвестно]"
            ]
        
        # Начинаем с родительской папки файла и идем вверх
        current_dir = fb2_file.parent
        parse_levels = 0
        
        while parse_levels < self.folder_parse_limit:
            # Получить название папки
            folder_name = current_dir.name
            
            # Применить conversions перед парсингом
            folder_name_to_parse = conversions.get(folder_name, folder_name)
            
            # Проверить: парсится ли эта папка как автор?
            author_name = self._parse_author_from_folder_name(folder_name_to_parse)
            
            if author_name:
                # КЛЮЧЕВАЯ ПРОВЕРКА: Есть ли найденное имя в metadata_authors?
                # Если да - это ПОДТВЕРЖДЕНИЕ, что это действительно автор!
                is_in_metadata = False
                if metadata_authors_list:
                    # Проверить: содержится ли author_name в любом из metadata авторов?
                    for meta_author in metadata_authors_list:
                        meta_lower = meta_author.lower()
                        author_lower = author_name.lower()
                        # Проверяем содержание (автор может быть частью)
                        if author_lower in meta_lower or meta_lower in author_lower:
                            is_in_metadata = True
                            break
                
                if is_in_metadata:
                    # НАЙДЕНО В METADATA! Это 100% подтверждение, что это автор
                    return author_name, 'folder_dataset'
                
                # Иначе применяем фильтры
                # Интеллектуальная проверка: это действительно имя автора, а не название серии?
                is_series_like = self._looks_like_series_name(author_name)
                
                if not is_series_like:
                    # Не похоже на серию - это вероятно автор
                    return author_name, 'folder_dataset'
                # Иначе: это название серии, игнорируем и идем дальше вверх
            
            # Идем на уровень вверх
            try:
                parent_dir = current_dir.parent
                if parent_dir == current_dir:
                    # Достигли корня файловой системы
                    break
                current_dir = parent_dir
                parse_levels += 1
            except Exception:
                break
        
        # Авторская папка не найдена
        # ВАЖНО: По архитектуре, PASS 1 должен быть консервативен:
        # - PASS 1 ищет ТОЛЬКО в папке
        # - Если папка не дала результата → возвращаем пусто
        # - Filename-извлечение - это работа PASS 2, а не PASS 1
        # - Metadata используется только для подтверждения найденного в папке
        # - Fallback на metadata происходит только если PASS 1 + PASS 2 оба дали пусто
        
        return "", ""
    
    def _pass1_read_fb2_files(self) -> None:
        """PASS 1: Чтение FB2 файлов и определение авторов по приоритету.
        
        Алгоритм:
        1. Построить логическую структуру папок с определением авторских папок
        2. Для каждого файла использовать инфо об авторской папке
        3. Если файл в авторской папке → author_source = "folder_dataset"
        4. Если файл вне авторской папки → пробовать filename → metadata
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 1] Scanning FB2 files...", flush=True)
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
                
                # Сначала получить все нужные метаданные из FB2 файла
                title = self.extractor._extract_title_from_fb2(fb2_file)
                metadata_authors = self.extractor._extract_all_authors_from_metadata(fb2_file)
                
                # Теперь определить автора, используя структуру папок и metadata для подтверждения
                author, source = self._get_author_for_file(fb2_file, folder_authors, metadata_authors or "")
                
                # TODO: Извлечь серию из метаданных FB2 (пока пусто)
                metadata_series = ""
                
                # Создать BookRecord
                record = BookRecord(
                    file_path=str(rel_path),
                    file_title=title or "[без названия]",
                    metadata_authors=metadata_authors or "[неизвестно]",
                    proposed_author=author or "",  # ← PASS 1 результат (может быть пусто!)
                    author_source=source or "",  # ← PASS 1 источник (может быть пусто!)
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
        
        print(f"\n[OK] PASS 1 complete: {fb2_count} files read (errors: {error_count})\n", flush=True)
        self.logger.log(f"[PASS 1] Прочитано {fb2_count} файлов (ошибок: {error_count})")
    
    def _pass2_extract_from_filename(self) -> None:
        """PASS 2: Извлечение авторов из имён файлов.
        
        Алгоритм:
        1. Для каждого файла с пустым proposed_author (не найдёно в PASS 1)
        2. Пытаемся извлечь автора из имени файла по паттернам
        3. Используем extracted автора независимо от metadata confirmation
        
        Файлы с author_source="folder_dataset" пропускаются (уже определены в PASS 1).
        Сборники определяются по markers в имени + количеству авторов в metadata.
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 2] Extracting authors from filenames...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 2] Starting extraction of authors from filenames...")
        
        extracted_count = 0
        collection_count = 0
        
        # Получить conversions для применения перед парсингом
        conversions = self.settings.get_author_surname_conversions()
        
        for record in self.records:
            # Пропустить файлы с folder_dataset - они уже определены надёжно в PASS 1
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
            
            # Не сборник - попытаться найти автора в ИМЕНИ ФАЙЛА (PASS 2 работает только с filename)
            
            # Сначала попробовать извлечь из ИМЕНИ ФАЙЛА по паттернам
            extracted_author = self._extract_author_from_filename_by_patterns(file_name)
            
            if extracted_author:
                # Успешно извлекли из имени файла
                # Шаг 1: Очистить от паразитных символов
                cleaned_author = self._clean_author_name(extracted_author)
                
                # Шаг 2: Обработать несколько авторов и убрать дубликаты
                final_author = self._process_and_expand_authors(cleaned_author, record, self.records)
                
                # ВАЖНО: Архитектура PASS 2
                # - Извлечение из filename - это основной результат PASS 2
                # - Metadata используется для подтверждения/расширения, но НЕ для отказа
                # - Если extraction успешен → используем его, независимо от metadata
                # - Metadata confirmation используется только для расширения (co-авторы)
                
                # Проверяем metadata для логирования/отладки
                is_metadata_confirmed = False
                if record.metadata_authors and record.metadata_authors not in ("Сборник", "[неизвестно]"):
                    metadata_lower = record.metadata_authors.lower()
                    final_author_lower = final_author.lower()
                    is_in_metadata = (
                        final_author_lower in metadata_lower or
                        metadata_lower in final_author_lower or
                        any(word in metadata_lower for word in final_author_lower.split())
                    )
                    is_metadata_confirmed = is_in_metadata
                
                # ИСПОЛЬЗУЕМ extracted author независимо от metadata confirmation
                # Metadata confirmation используется только для расширения, а не для отказа
                record.proposed_author = final_author
                record.author_source = "filename"
                extracted_count += 1
                continue
            
            # Если extraction из имени файла не сработал, остаётся пусто
            # PASS 2 работает ТОЛЬКО с filename, не с папками
            # Папки уже обработаны в PASS 1
            # Fallback на metadata происходит после PASS 2
        
        print(f"[OK] PASS 2 complete: {extracted_count} authors + {collection_count} collections extracted\n", flush=True)
        self.logger.log(f"[PASS 2] Извлечено {extracted_count} авторов и {collection_count} сборников")
    
    def _pass2_fallback_to_metadata(self) -> None:
        """PASS 2 Fallback: Применить metadata как последний источник для файлов без автора.
        
        Если после PASS 1 + PASS 2 proposed_author остался пустым → используем metadata.
        Metadata затем пройдет через PASS 3-6 вместе с остальными авторами.
        
        Это происходит ТОЛЬКО если оба основных PASS нашли ничего.
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 2 Fallback] Applying metadata for records without authors...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 2 Fallback] Применение metadata для файлов без автора...")
        
        fallback_count = 0
        
        for record in self.records:
            # Пропустить если уже есть author
            if record.proposed_author and record.proposed_author not in ("", "Сборник"):
                continue
            
            # Пропустить "Сборник" - это финальное значение
            if record.proposed_author == "Сборник":
                continue
            
            # Применить metadata если он есть
            if record.metadata_authors and record.metadata_authors not in ("[неизвестно]", "Сборник"):
                record.proposed_author = record.metadata_authors
                record.author_source = "metadata"
                fallback_count += 1
        
        print(f"[OK] PASS 2 Fallback complete: {fallback_count} records using metadata\n", flush=True)
        self.logger.log(f"[PASS 2 Fallback] Применено {fallback_count} записей с metadata")
    
    def _pass3_normalize_authors(self) -> None:
        """PASS 3: Нормализовать формат авторов.
        
        "Иван Петров" → "Петров Иван"
        Использует AuthorName класс для логики.
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 3] Normalizing author formats...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 3] Начало нормализации формата...")
        
        changed_count = 0
        for record in self.records:
            original = record.proposed_author
            apply_author_normalization(record)
            if record.proposed_author != original:
                changed_count += 1
        
        print(f"[OK] PASS 3 complete: {changed_count} authors normalized\n", flush=True)
        self.logger.log(f"[PASS 3] Изменено {changed_count} авторов")
    
    def _pass4_apply_consensus(self) -> None:
        """PASS 4: Применить консенсус к группам файлов.
        
        Файлы с author_source="folder_dataset" НЕ меняются.
        Консенсус применяется только к файлам в одной папке с source="filename" или "metadata".
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 4] Applying consensus to groups...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 4] Начало применения консенсуса...")
        
        # Функция для определения группы - parent folder
        def group_by_folder(record: BookRecord) -> str:
            return str(Path(record.file_path).parent)
        
        # Применить консенсус
        apply_author_consensus(self.records, group_by_folder, self.settings)
        
        # Статистика
        consensus_count = sum(1 for r in self.records if r.author_source == "consensus")
        print(f"[OK] PASS 4 complete: {consensus_count} files processed by consensus\n", flush=True)
        self.logger.log("[PASS 4] Завершено")
    
    def _pass5_apply_conversions(self) -> None:
        """PASS 5: Переприменить conversions после консенсуса.
        
        Это нужно потому что консенсус может изменить автора на другого,
        и нужно переприменить conversions для новой фамилии.
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 5] Re-applying conversions...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 5] Начало переприменения conversions...")
        
        changed_count = 0
        original_authors = {id(r): r.proposed_author for r in self.records}
        
        apply_surname_conversions_to_records(self.records, self.settings)
        
        for record in self.records:
            if record.proposed_author != original_authors.get(id(record)):
                changed_count += 1
        
        print(f"[OK] PASS 5 complete: {changed_count} authors re-applied conversions\n", flush=True)
        self.logger.log(f"[PASS 5] Переприменено conversions к {changed_count} авторам")
    
    def _pass6_expand_abbreviations(self) -> None:
        """PASS 6: Раскрыть аббревиатуры в именах авторов.
        
        "И.Петров" → "Иван Петров"
        Требует построения словаря полных имён из всех авторов.
        """
        print("\n" + "="*80, flush=True)
        print("[PASS 6] Expanding abbreviations...", flush=True)
        print("="*80, flush=True)
        
        self.logger.log("[PASS 6] Начало раскрытия аббревиатур...")
        
        # Построить словарь авторов
        authors_map = build_authors_map(self.records, self.settings)
        print(f"  Построено {len(authors_map)} уникальных фамилий", flush=True)
        self.logger.log(f"  [PASS 6] Построено {len(authors_map)} уникальных фамилий")
        
        # Раскрыть аббревиатуры
        expand_abbreviated_authors(self.records, authors_map, self.settings)
        
        print(f"[OK] PASS 6 complete\n", flush=True)
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
        """Отсортировать записи по иерархии папок и файлов.
        
        Сортировка: все файлы в папке идут подряд, затем подпапки и их файлы.
        Пример результата:
        - Папка1/файл1.fb2
        - Папка1/файл2.fb2
        - Папка1/Подпапка1/файл3.fb2
        - Папка1/Подпапка1/файл4.fb2
        - Папка2/файл5.fb2
        """
        # Простая сортировка по пути файла (естественная иерархия)
        self.records.sort(key=lambda r: r.file_path)
    
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
        print("[CSV] Saving results to CSV...", flush=True)
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
        print(f"\n[OK] CSV saved: {total} records", flush=True)
        print(f"   Путь: {output_path}", flush=True)
        print(f"\n   Статистика по источникам:", flush=True)
        for source, count in sorted(by_source.items()):
            print(f"   • {source:20s}: {count:4d} ({count*100//total}%)", flush=True)
        print()
        
        self.logger.log(f"[OK] CSV saved: {total} records")
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
