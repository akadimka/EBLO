#!/usr/bin/env python3
"""Check the Zoric/Zharkovsky file"""

import csv

with open('regen.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    records = list(reader)

# Find the file with multiple authors
print("=" * 90)
print("FILE WITH MULTIPLE AUTHORS")
print("=" * 90)

zoric = [r for r in records if 'Зорич' in r['file_path'] and 'Жарковский' in r['file_path']]

for r in zoric:
    print(f"\nFile: {r['file_path']}")
    print(f"  proposed_author: {r['proposed_author']}")
    print(f"  metadata_authors: {r['metadata_authors']}")
    print(f"  author_source: {r['author_source']}")
    print(f"  Contains Cyrillic OK: {all(ord(c) < 128 or ord(c) > 1000 for c in r['proposed_author'])}")

print("\n" + "=" * 90)
print("OVERALL STATISTICS")
print("=" * 90)

# Count files by source and quality
excellent = sum(1 for r in records if len(r['proposed_author'].split()) >= 2 and all(ord(c) < 128 or ord(c) > 1000 for c in r['proposed_author']))
good = sum(1 for r in records if r['proposed_author'] and all(ord(c) < 128 or ord(c) > 1000 for c in r['proposed_author']))
bad_encoding = sum(1 for r in records if r['proposed_author'] and any(128 <= ord(c) < 1000 for c in r['proposed_author']))

print(f"""
Total files: {len(records)}
  ✅ Excellent (full name + proper encoding): {excellent} ({100*excellent/len(records):.1f}%)
  ✅ Good (named + proper encoding): {good} ({100*good/len(records):.1f}%)
  ❌ Encoding issues: {bad_encoding} ({100*bad_encoding/len(records):.1f}%)

Source breakdown:
  • folder_dataset: {sum(1 for r in records if r['author_source'] == 'folder_dataset')} (reliable)
  • filename: {sum(1 for r in records if r['author_source'] == 'filename')} (context-aware)
  • consensus: {sum(1 for r in records if r['author_source'] == 'consensus')} (multi-author)
""")
