#!/usr/bin/env python3
"""Заменить execute() на правильную depth-independent версию"""

import re

# Новая реализация execute()
NEW_EXECUTE = '''    def execute(self, records: List[BookRecord]) -> None:
        """
        ПРОСТАЯ И ПРАВИЛЬНАЯ ЛОГИКА - независима от папок!
        ===================================================
        Логика:
        1. Если series_source == "folder_dataset" → skip (папка дала series)
        2. Если proposed_series не пусто → skip (уже выбрана)  
        3. ВСЕГДА пробовать паттерны (неважно file_depth!)
        4. Fallback на metadata только если паттерны не дали
        """
        for record in records:
            if record.series_source == "folder_dataset":
                continue  # Папка уже дала series
            
            if record.proposed_series:
                continue  # Серия уже установлена
            
            # ОБЯЗАТЕЛЬНО пробуем паттерны (глубина НЕ влияет!)
            series_candidate = self._extract_series_from_filename(
                record.file_path, validate=False, metadata_series=record.metadata_series
            )
            
            if series_candidate:
                record.extracted_series_candidate = series_candidate
                
                # Базовые фильтры (НЕ валидация)
                if ',' in series_candidate:
                    series_candidate = None  # Список авторов
                elif self._is_author_surname(series_candidate, record.proposed_author):
                    series_candidate = None  # Фамилия
            
            # Если прошел базовые фильтры → валидация
            if series_candidate:
                clean = self._clean_series_name(
                    series_candidate, 
                    keep_trailing_number=self._last_was_hierarchical
                )
                author_for_validation = record.proposed_author or None
                
                if self._is_valid_series(clean, extracted_author=author_for_validation):
                    record.proposed_series = clean
                    record.series_source = "filename"
                    continue
            
            # Fallback: metadata ТОЛЬКО если паттерны не дали
            if record.metadata_series:
                series = self._extract_series_from_metadata(record.metadata_series.strip())
                author_for_validation = record.proposed_author or None
                if self._is_valid_series(series, extracted_author=author_for_validation):
                    record.proposed_series = series
                    record.series_source = "metadata"
        
        # Commented out: folder pattern consensus was also causing issues  
        # self._apply_series_folder_pattern_consensus(records)
        
        # Commented out: consensus logic was overwriting properly extracted series
        # TODO: Review and fix consensus logic before re-enabling
        # self._apply_cross_file_consensus(records)
'''

def fix_pass2():
    with open(r'c:\Temp\fb2parser\passes\pass2_series_filename.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Найти метод execute
    pattern = r'(    def execute\(self, records: List\[BookRecord\]\) -> None:.*?)\n    def _apply_series_folder_pattern_consensus'
    
    # Заменить на новую версию
    new_content = re.sub(
        pattern,
        NEW_EXECUTE + '\n    def _apply_series_folder_pattern_consensus',
        content,
        flags=re.DOTALL
    )
    
    if new_content == content:
        print("ERROR: Pattern not found! File not modified.")
        # Попробуем более простую замену
        pattern2 = r'def execute\(self, records: List\[BookRecord\]\) -> None:'
        if re.search(pattern2, content):
            print("Found execute method, trying simpler replacement...")
            # Найдёме линию execute и строку _apply
            start = content.find('    def execute(self, records: List[BookRecord]) -> None:')
            end = content.find('    def _apply_series_folder_pattern_consensus')
            if start >= 0 and end > start:
                new_content = content[:start] + NEW_EXECUTE + '\n\n' + content[end:]
                print(f"Replacing lines {start} to {end}")
                with open(r'c:\Temp\fb2parser\passes\pass2_series_filename.py', 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print("✓ File updated!")
                return True
        return False
    else:
        with open(r'c:\Temp\fb2parser\passes\pass2_series_filename.py', 'w', encoding='utf-8') as f:
            f.write(new_content)
        print("✓ File updated!")
        return True

if __name__ == '__main__':
    fix_pass2()
