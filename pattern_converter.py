"""
Pattern Converter Module / Модуль преобразования шаблонов

Преобразует простые пользовательские шаблоны в регулярные выражения.

/ Converts user-friendly patterns to regex patterns.
"""
import re


def convert_simple_pattern_to_regex(pattern_str: str) -> str:
    """
    Преобразует простой шаблон в регулярное выражение.
    
    Примеры:
    - "(Author) - Title" → "^\\((?P<author>[^)]+)\\)\\s*-\\s+(?P<title>.+)$"
    - "[Series] - (Author)" → "^\\[(?P<series>[^\\]]+)\\]\\s*-\\s+\\((?P<author>[^)]+)\\)$"
    - "Author - Title" → "^(?P<author>.+?)\\s*-\\s+(?P<title>.+)$"
    
    Правила:
    - (Name) - содержимое в круглых скобках, группа = name.lower()
    - [Name] - содержимое в квадратных скобках, группа = name.lower()
    - Name - текст без скобок, группа = name.lower()
    """
    if not pattern_str or not isinstance(pattern_str, str):
        return ""
    
    pattern_str = pattern_str.strip()
    
    # Регулярное выражение для поиска всех групп (с/без скобок)
    # Ищет: (Name), [Name] или просто Name (между разделителями)
    token_pattern = r'\(([^)]+)\)|\[([^\]]+)\]|(\w+)'
    
    # Найти все токены и их позиции
    tokens = []
    last_end = 0
    
    for match in re.finditer(token_pattern, pattern_str):
        # Текст перед этим токеном
        before_text = pattern_str[last_end:match.start()]
        
        # Тип и содержимое токена
        bracket_group = match.group(1)  # (Name)
        square_group = match.group(2)   # [Name]
        plain_group = match.group(3)    # Name
        
        if bracket_group:
            group_name = bracket_group.lower()
            bracket_type = '()'
            tokens.append({
                'before': before_text,
                'name': group_name,
                'bracket_type': bracket_type
            })
        elif square_group:
            group_name = square_group.lower()
            bracket_type = '[]'
            tokens.append({
                'before': before_text,
                'name': group_name,
                'bracket_type': bracket_type
            })
        elif plain_group:
            group_name = plain_group.lower()
            bracket_type = 'plain'
            tokens.append({
                'before': before_text,
                'name': group_name,
                'bracket_type': bracket_type
            })
        
        last_end = match.end()
    
    # Остаток строки после последнего токена
    remaining = pattern_str[last_end:]
    
    if not tokens:
        # Если токенов нет, экранируем строку как есть
        escaped = re.escape(pattern_str)
        return f"^{escaped}$"
    
    # Построить regex из токенов
    regex_parts = ['^']
    
    for i, token in enumerate(tokens):
        # Добавляем текст перед токеном (экранированный с гибким пробелом)
        before = token['before']
        if before:
            # Заменяем пробелы на \\s*
            before_escaped = re.escape(before)
            before_escaped = before_escaped.replace(r'\ ', r'\s*')
            regex_parts.append(before_escaped)
        
        # Добавляем саму группу
        group_name = token['name']
        bracket_type = token['bracket_type']
        
        if bracket_type == '()':
            # (Name) - match content in ()
            regex_parts.append(r'\((?P<' + group_name + r'>[^)]+)\)')
        elif bracket_type == '[]':
            # [Name] - match content in []
            regex_parts.append(r'\[(?P<' + group_name + r'>[^\]]+)\]')
        else:  # plain
            # Name - match any content
            regex_parts.append(r'(?P<' + group_name + r'>.+?)')
    
    # Добавляем остаток (если он есть)
    if remaining:
        remaining_escaped = re.escape(remaining)
        remaining_escaped = remaining_escaped.replace(r'\ ', r'\s*')
        regex_parts.append(remaining_escaped)
    
    # Добавляем конец строки
    regex_parts.append('$')
    
    result = ''.join(regex_parts)
    return result


def extract_group_names(pattern_str: str) -> list:
    """
    Извлекает названия групп из простого шаблона.
    
    Примеры:
    - "(Author) - Title" → ['author', 'title']
    - "[Series] (Author)" → ['series', 'author']
    """
    token_pattern = r'\(([^)]+)\)|\[([^\]]+)\]|(\w+)'
    group_names = []
    
    for match in re.finditer(token_pattern, pattern_str):
        bracket_group = match.group(1)
        square_group = match.group(2)
        plain_group = match.group(3)
        
        if bracket_group:
            group_names.append(bracket_group.lower())
        elif square_group:
            group_names.append(square_group.lower())
        elif plain_group:
            group_names.append(plain_group.lower())
    
    return group_names


def compile_patterns(pattern_strings: list) -> list:
    """
    Преобразует список паттернов в скомпилированные regex.
    
    Принимает:
    - Список строк: ["(Author) - Title", ...] 
    - Список объектов: [{"pattern": "(Author) - Title", "example": "..."}, ...]
    
    Возвращает список кортежей: (pattern_string, compiled_regex, group_names)
    
    Примеры:
    - ["(Author) - Title", "[Series] (Author)"] → 
      [
        ("(Author) - Title", regex_object, ['author', 'title']),
        ("[Series] (Author)", regex_object, ['series', 'author'])
      ]
    """
    if not pattern_strings:
        return []
    
    result = []
    for item in pattern_strings:
        try:
            # Если это объект с 'pattern', извлекаем паттерн
            if isinstance(item, dict):
                pattern_str = item.get('pattern', '').strip()
            else:
                # Если это строка
                pattern_str = str(item).strip()
            
            if not pattern_str:
                continue
            
            regex_str = convert_simple_pattern_to_regex(pattern_str)
            compiled_regex = re.compile(regex_str)
            group_names = extract_group_names(pattern_str)
            result.append((pattern_str, compiled_regex, group_names))
        except Exception as e:
            # Пропускаем невалидные паттерны
            continue
    
    return result
