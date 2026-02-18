"""
PASS1: Pattern Selection

Based on structural analysis, determines which pattern matches the folder name.
7 possible patterns are checked in order of precedence.
"""

from typing import Optional


def select_pattern(struct_info: dict) -> Optional[str]:
    """
    Selects appropriate pattern based on structural analysis.
    
    Args:
        struct_info: Dictionary from pass0_structural_analysis.analyze_structure()
        
    Returns:
        One of: "Author, Author", "(Surname) (Name)", "Series (Author, Author)",
                "Series (Author)", "(Series) Author", "Author - Folder Name",
                "Series", or None
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
    
    # 1. "Author, Author" (100) - comma without brackets
    if pattern is None:
        if not paren_count and has_comma:
            pattern = "Author, Author"
    
    # 2. "(Surname) (Name)" (100) - exactly 2 words, no brackets
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
