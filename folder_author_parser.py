"""
Парсинг имени папки для извлечения автора.
Использует структурный анализ PASS0+PASS1+PASS2 с blacklist для категорий.
"""


def parse_author_from_folder_name(folder_name: str) -> str:
    """
    Parses author name from a folder name using structural analysis.
    
    Returns empty string if:
    - folder_name is in the blacklist (category folders like "Серия", "Сборник")
    - folder_name doesn't match any known pattern
    - folder_name is too generic/not an author name
    
    Args:
        folder_name: The folder name to parse
        
    Returns:
        Author name (surname + name) or empty string
    """
    if not folder_name or not folder_name.strip():
        return ""
    
    name = folder_name.strip()
    
    # ==================== BLACKLIST: Не парсим категории как авторов ====================
    blacklist_starts = [
        'Серия',
        'Сборник', 
        'Коллекция',
        'Антология',
        'Цикл',
        'Подборка',
        'Архив',
        'Разное',
        'Другое',
        'Unknown',
        'Various',
    ]
    
    name_lower = name.lower()
    for word in blacklist_starts:
        if name_lower.startswith(word.lower()):
            return ""  # Это категория, не автор
    
    # ==================== PASS0: Структурный анализ ====================
    
    # Найти все КРУГЛЫЕ скобки ()
    paren_positions = []
    paren_contents = []
    
    i = 0
    while i < len(name):
        if name[i] == '(':
            j = i + 1
            while j < len(name) and name[j] != ')':
                j += 1
            if j < len(name):  # Найдена закрывающая скобка
                content = name[i+1:j]
                paren_positions.append((i, j+1, content))
                paren_contents.append(content)
                i = j + 1
            else:
                i += 1
        else:
            i += 1
    
    paren_count = len(paren_contents)
    
    # Определить позиционирование скобок
    bracket_positioning = 'none'
    if paren_count > 0:
        first_paren_start = paren_positions[0][0]
        last_paren_end = paren_positions[-1][1]
        
        if paren_count == 1:
            if first_paren_start == 0:
                bracket_positioning = 'start'
            elif last_paren_end == len(name):
                bracket_positioning = 'end'
            else:
                bracket_positioning = 'middle'
        else:
            if first_paren_start == 0 and last_paren_end == len(name):
                bracket_positioning = 'wrap'
            else:
                bracket_positioning = 'multiple'
    
    # Текст ДО первой и ПОСЛЕ последней скобки
    text_before_first = ""
    text_after_last = ""
    
    if paren_count > 0:
        text_before_first = name[:paren_positions[0][0]].strip()
        text_after_last = name[paren_positions[-1][1]:].strip()
    
    # Проверить наличие запятой и дефиса
    has_comma = ',' in name
    has_comma_in_parens = any(',' in content for content in paren_contents)
    has_dash_with_spaces = ' - ' in name
    
    # ==================== PASS1: Выбор паттерна ====================
    
    pattern = None
    
    # 1. "Author, Author" (100) - запятая без скобок
    if pattern is None:
        if not paren_count and has_comma:
            pattern = "Author, Author"
    
    # 2. "(Surname) (Name)" (100) - ровно 2 слова, нет скобок
    if pattern is None:
        if not paren_count:
            words = name.split()
            if len(words) == 2:
                pattern = "(Surname) (Name)"
    
    # 3. "Series (Author, Author)" (100) - скобки в конце с запятой внутри
    if pattern is None:
        if (paren_count >= 1 and 
            bracket_positioning in ['end', 'multiple'] and
            has_comma_in_parens and
            not text_after_last):
            pattern = "Series (Author, Author)"
    
    # 4. "Series (Author)" (95/90) - скобки в конце БЕЗ запятой БЕЗ текста после
    if pattern is None:
        if (bracket_positioning in ['end', 'multiple'] and
            not has_comma_in_parens and
            not text_after_last):
            pattern = "Series (Author)"
    
    # 5. "(Series) Author" (90) - скобки в начале с текстом после
    if pattern is None:
        if (bracket_positioning == 'start' and text_after_last):
            pattern = "(Series) Author"
    
    # 6. "Author - Folder Name" (50) - дефис СО ПРОБЕЛАМИ!!!
    # НО: если после дефиса есть кавычки « » - это серия, не автор!
    if pattern is None:
        if has_dash_with_spaces:
            parts = name.split(' - ', 1)
            if len(parts) == 2:
                after_dash = parts[1].strip()
                # Если после дефиса есть кавычки « » или » - это серия
                if '«' not in after_dash and '»' not in after_dash:
                    pattern = "Author - Folder Name"
    
    # 7. Series (fallback) - одно слово или просто текст
    if pattern is None:
        # Если только одно слово - это вероятно не автор, а название серии
        words = name.split()
        if len(words) == 1:
            return ""  # Fallback - не парсим одиночные слова
        pattern = "Series"
    
    # ==================== PASS2: Извлечение автора ====================
    
    author = ""
    
    if pattern == "Author, Author":
        # Первый автор
        author = name.split(',')[0].strip()
    
    elif pattern == "(Surname) (Name)":
        # Оба слова как есть
        author = name.strip()
    
    elif pattern == "Series (Author, Author)":
        # Содержимое первых скобок (авторы)
        if paren_contents:
            author = paren_contents[0].strip()
    
    elif pattern == "Series (Author)":
        # ПОСЛЕДНЯЯ скобка ← КЛЮЧЕВО для МВП-2 (1) Одиссея (Чернов) 
        if paren_contents:
            author = paren_contents[-1].strip()
    
    elif pattern == "(Series) Author":
        # Текст ПОСЛЕ скобок
        author = text_after_last.strip()
    
    elif pattern == "Author - Folder Name":
        # Текст ДО дефиса
        if ' - ' in name:
            author = name.split(' - ')[0].strip()
    
    elif pattern == "Series":
        # Fallback: текст перед скобками или всё целиком
        author = text_before_first.strip() or name.strip()
    
    return author.strip() if author else ""
