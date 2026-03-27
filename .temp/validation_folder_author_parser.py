"""
Name Validation Module

Validates if extracted author names are actual person names (not series names).
"""

import json
from typing import Optional


def load_name_sets(config_path: str = "config.json") -> tuple:
    """
    Load male and female names from config.
    
    Args:
        config_path: Path to config.json
        
    Returns:
        Tuple of (male_names_set, female_names_set)
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        male_names = set(config.get('male_names', []))
        female_names = set(config.get('female_names', []))
        
        return male_names, female_names
    except Exception as e:
        print(f"Warning: Could not load name sets from {config_path}: {e}")
        return set(), set()


def contains_valid_name(text: str, male_names: set, female_names: set) -> bool:
    """
    Check if text contains at least one valid first name or last name from lists.
    
    Args:
        text: Author name text (e.g., "Олег Сапфир" or "Идеальный мир для Социопата")
        male_names: Set of male names
        female_names: Set of female names
        
    Returns:
        True if text contains at least one recognized name, False otherwise
    """
    if not text:
        return False
    
    # Split text into words
    words = text.split()
    
    # Capitalize variations (first letter uppercase)
    for word in words:
        # Check various capitalizations
        word_caps = word.capitalize()
        word_lower = word.lower()
        word_title = word.title()
        
        # Check direct match with capitalization (most common case)
        if word_caps in male_names or word_caps in female_names:
            return True
        
        # Check title case
        if word_title in male_names or word_title in female_names:
            return True
        
        # For Russian - check exact matches
        for name in male_names | female_names:
            if name.lower() == word_lower:
                return True
    
    return False


def validate_author_name(author_text: str, male_names: Optional[set] = None, 
                        female_names: Optional[set] = None, 
                        config_path: str = "config.json") -> bool:
    """
    Validate if extracted text is an actual author name.
    
    Args:
        author_text: Extracted author name to validate
        male_names: Optional set of male names (loaded from config if not provided)
        female_names: Optional set of female names (loaded from config if not provided)
        config_path: Path to config.json
        
    Returns:
        True if valid author name, False otherwise
    """
    if not author_text or not author_text.strip():
        return False
    
    # Load name sets if not provided
    if male_names is None or female_names is None:
        loaded_male, loaded_female = load_name_sets(config_path)
        if male_names is None:
            male_names = loaded_male
        if female_names is None:
            female_names = loaded_female
    
    # Check if text contains at least one valid name
    return contains_valid_name(author_text, male_names, female_names)
