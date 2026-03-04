#!/usr/bin/env python3
"""Full debug: trace author extraction for Legion 4-6 and 7-9."""

from pathlib import Path
from passes.pass2_filename import Pass2Filename
from passes.file_structural_analysis import analyze_file_structure, score_pattern_match
from settings_manager import SettingsManager
from logger import Logger

# Initialize
settings = SettingsManager('config.json')
logger = Logger()
pass2 = Pass2Filename(settings, logger, work_dir=Path(r"C:\Users\dmitriy.murov\Downloads\TriblerDownloads\Test1"))

test_files = [
    ("Живой, Прозоров. Легион (Легион 4-6)", "Живой, Прозоров. Легион (Легион 4-6).fb2"),
    ("Живой, Прозоров. Легион (Легион 7-9)", "Живой, Прозоров. Легион (Легион 7-9).fb2"),
]

for filename, fb2_filename in test_files:
    print(f"\n{'='*80}")
    print(f"File: {filename}")
    print("=" * 80)
    
    fb2_path = Path(r"C:\Users\dmitriy.murov\Downloads\TriblerDownloads\Test1\Серия - «Боевая фантастика. Коллекция»") / fb2_filename
    
    # Step 1: Find best pattern
    struct = analyze_file_structure(filename, pass2.service_words)
    best_pattern = None
    best_score = 0
    best_specificity = 0
    
    for pattern_obj in pass2.patterns:
        pattern = pattern_obj.get('pattern', '')
        score = score_pattern_match(struct, pattern, pass2.service_words)
        specificity = pattern.count(',') * 10 + pattern.count('(') * 5 + pattern.count('.') * 2
        
        if score > best_score or (score == best_score and specificity > best_specificity):
            best_score = score
            best_pattern = pattern
            best_specificity = specificity
    
    print(f"\n1. PATTERN SELECTION:")
    print(f"   Best: '{best_pattern}' (score={best_score:.4f}, specificity={best_specificity})")
    
    # Step 2: Extract by pattern
    author = pass2._extract_by_pattern(filename, best_pattern, struct)
    print(f"\n2. EXTRACT BY PATTERN:")
    print(f"   Result: '{author}'")
    
    # Step 3: Validate each author
    if author and ', ' in author:
        authors = [a.strip() for a in author.split(', ')]
        print(f"\n3. VALIDATION:")
        print(f"   Split into: {authors}")
        
        validated_authors = []
        for single_author in authors:
            looks_like = pass2._looks_like_author_name(single_author)
            from name_normalizer import validate_author_name
            is_valid = validate_author_name(single_author)
            print(f"   - '{single_author}': looks_like={looks_like}, valid={is_valid}")
            
            if single_author and looks_like and is_valid:
                expanded = pass2._validate_and_expand_author(single_author, fb2_path)
                print(f"     → Expanded: '{expanded}'")
                validated_authors.append(expanded)
            elif single_author:
                print(f"     → Keeping as-is")
                validated_authors.append(single_author)
        
        if validated_authors:
            final = ', '.join(validated_authors)
            print(f"\n4. FINAL RESULT: '{final}'")
    else:
        print(f"\n3. SINGLE AUTHOR (no comma): '{author}'")
