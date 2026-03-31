"""
PASS1: Pattern Selection

Based on structural analysis, determines which pattern matches the folder name.
7 possible patterns are checked in order of precedence.
"""

from typing import Optional


def _is_person_name(text: str, male_names: set, female_names: set) -> bool:
    """Return True if text looks like a person name (2 words, one in name dictionaries)."""
    if not text:
        return False
    words = text.split()
    if len(words) != 2:
        return False
    for word in words:
        w = word.strip('.,;').lower()
        if w in male_names or w in female_names:
            return True
    return False


def select_pattern(struct_info: dict,
                   male_names: set = None,
                   female_names: set = None) -> Optional[str]:
    """
    Selects appropriate pattern based on structural analysis.

    Args:
        struct_info: Dictionary from pass0_structural_analysis.analyze_structure()
        male_names: Set of male names (lowercase) for co-author detection
        female_names: Set of female names (lowercase) for co-author detection

    Returns:
        One of: "Author, Author", "(Surname) (Name)", "Series (Author, Author)",
                "Author (CoAuthor)", "Series (Author)", "(Series) Author",
                "Author - Folder Name", "Series", or None
    """
    
    paren_count = struct_info['paren_count']
    bracket_positioning = struct_info['bracket_positioning']
    text_before_first = struct_info['text_before_first']
    text_after_last = struct_info['text_after_last']
    has_comma = struct_info['has_comma']
    has_comma_in_parens = struct_info['has_comma_in_parens']
    has_dash_with_spaces = struct_info['has_dash_with_spaces']
    name = struct_info['name']
    
    pattern = None
    
    # 1. "SurnamePlural FirstName и SecondName" (105) - highest priority
    # Format: "Живовы Георгий и Геннадий" → 2 authors with shared surname
    if pattern is None:
        if (not paren_count and 
            ' и ' in name):  # Has " и " (Russian "and")
            parts = name.split(' и ')
            if len(parts) == 2:
                first_part = parts[0].strip()
                second_part = parts[1].strip()
                words_first = first_part.split()
                words_second = second_part.split()
                # Check: first part is "Surname Name", second part is single "Name"
                if len(words_first) >= 2 and len(words_second) == 1:
                    # Extract surname from first part (usually first word)
                    surname = words_first[0]
                    first_name = ' '.join(words_first[1:])
                    second_name = second_part
                    # Construct as "Surname FirstName; Surname SecondName"
                    pattern = "SurnamePlural FirstName и SecondName"
    
    # 2. "Author, Author" (100) - comma without brackets
    if pattern is None:
        if not paren_count and has_comma:
            pattern = "Author, Author"
    
    # 3. "(Surname) (Name)" (100) - exactly 2 words, no brackets
    if pattern is None:
        if not paren_count:
            words = name.split()
            if len(words) == 2:
                pattern = "(Surname) (Name)"
    
    # 3. "Series (Author, Author)" (100) - brackets at end with comma inside
    if pattern is None:
        if (paren_count >= 1 and 
            bracket_positioning in ['end', 'multiple'] and
            has_comma_in_parens and
            not text_after_last):
            pattern = "Series (Author, Author)"

    # 3b. "Author (CoAuthor)" - text before bracket is a person name (2 words, one in dict)
    # Example: "Орлов Алекс (Дарищев Вадим)" → Author=Орлов Алекс, CoAuthor=Дарищев Вадим
    if pattern is None:
        if (paren_count == 1 and
                bracket_positioning == 'end' and
                not has_comma_in_parens and
                not text_after_last and
                male_names is not None and female_names is not None and
                _is_person_name(text_before_first, male_names, female_names)):
            pattern = "Author (CoAuthor)"

    # 4. "Series (Author)" (95/90) - brackets at end WITHOUT comma WITHOUT text after
    if pattern is None:
        if (bracket_positioning in ['end', 'multiple'] and
            not has_comma_in_parens and
            not text_after_last):
            pattern = "Series (Author)"
    
    # 5. "(Series) Author" (90) - brackets at start with text after
    if pattern is None:
        if (bracket_positioning == 'start' and text_after_last):
            pattern = "(Series) Author"
    
    # 6. "Author - Folder Name" (50) - dash WITH SPACES!!!
    # BUT: if after dash there are « » - this is a series, not an author!
    if pattern is None:
        if has_dash_with_spaces:
            parts = name.split(' - ', 1)
            if len(parts) == 2:
                after_dash = parts[1].strip()
                # If after dash there are « » or » - this is a series
                if '«' not in after_dash and '»' not in after_dash:
                    pattern = "Author - Folder Name"
    
    # 7. Series (fallback) - single word or just text
    if pattern is None:
        # If only one word - this is likely not an author, but series name
        words = name.split()
        if len(words) == 1:
            return None  # Fallback - don't parse single words
        pattern = "Series"
    
    return pattern
