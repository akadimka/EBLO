"""
PASS2: Author Extraction

Extracts author name from folder name based on selected pattern and structural info.
"""

from typing import Optional


def extract_author(struct_info: dict, pattern: Optional[str]) -> str:
    """
    Extracts author name based on pattern and structural information.
    
    Args:
        struct_info: Dictionary from pass0_structural_analysis.analyze_structure()
        pattern: Pattern from pass1_pattern_selection.select_pattern()
        
    Returns:
        Author name (surname + name) or empty string
    """
    
    if not pattern:
        return ""
    
    name = struct_info['name']
    paren_contents = struct_info['paren_contents']
    text_after_last = struct_info['text_after_last']
    
    author = ""
    
    if pattern == "Author, Author":
        # First author
        author = name.split(',')[0].strip()
    
    elif pattern == "(Surname) (Name)":
        # Both words as is
        author = name.strip()
    
    elif pattern == "Series (Author, Author)":
        # Content of first parentheses (authors) - normalize to '; ' separator
        if paren_contents:
            # Convert ", " to "; " for unified processing in PASS 3
            author = paren_contents[0].strip().replace(', ', '; ')
    
    elif pattern == "Series (Author)":
        # LAST parentheses ← KEY for МВП-2 (1) Одиссея (Чернов)
        if paren_contents:
            author = paren_contents[-1].strip()
    
    elif pattern == "(Series) Author":
        # Text AFTER parentheses
        author = text_after_last.strip()
    
    elif pattern == "Author - Folder Name":
        # Text BEFORE dash
        if ' - ' in name:
            author = name.split(' - ')[0].strip()
    
    elif pattern == "Series":
        # Fallback: text before parentheses or entire name
        text_before_first = struct_info['text_before_first']
        author = text_before_first.strip() or name.strip()
    
    return author.strip() if author else ""
