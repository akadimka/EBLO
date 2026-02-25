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
        # Both authors separated by comma, normalize to "; " separator
        # "Земляной Андрей, Орлов Борис" → "Земляной Андрей; Орлов Борис"
        author = name.replace(', ', '; ')
    
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
        # Fallback: if there are NO parentheses with AUTHORS, don't extract anything
        # This is just a series name, not an author name
        # Only extract if text_before_first has something meaningful (like before parentheses)
        text_before_first = struct_info['text_before_first']
        if text_before_first and struct_info['paren_count'] > 0:
            # Text before brackets: "Максим Шаттам - Собрание сочинений" → extract "Максим Шаттам"
            author = text_before_first.strip()
        else:
            # No parentheses with author info, don't parse the folder name
            author = ""
    
    return author.strip() if author else ""
