#!/usr/bin/env python3
"""Simple check for what's extracted from Legion filenames"""
import re
import csv

# Read the CSV and check the Legion files
with open('regen.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    for i, row in enumerate(reader):
        if 'Живой, Прозоров. Легион' in row['file_path']:
            print(f"\nRecord {i+2}:")
            print(f"  File: {row['file_path']}")
            print(f"  metadata_authors: {row['metadata_authors']}")
            print(f"  proposed_author: {row['proposed_author']}")
            print(f"  author_source: {row['author_source']}")
            print(f"  metadata_series: '{row['metadata_series']}'")
            print(f"  proposed_series: '{row['proposed_series']}'")
            print(f"  series_source: '{row['series_source']}'")
            print(f"  file_title: {row['file_title']}")
