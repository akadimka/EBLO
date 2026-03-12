#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Читаем CSV правильно"""

import csv
from pathlib import Path

csv_file = Path('regen.csv')

with open(csv_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    zurkov_rows = []
    
    for row in reader:
        if 'Зурков' in row['file_path'] and 'Черепнев' in row['file_path']:
            zurkov_rows.append(row)

print("=" * 120)
print("ДАННЫЕ CSV ДЛЯ ФАЙЛОВ ZURKOV")
print("=" * 120)

for idx, row in enumerate(zurkov_rows, 1):
    print(f"\n📄 ФАЙЛ {idx}:")
    print(f"  file_path: {row['file_path']}")
    print(f"  metadata_series: '{row['metadata_series']}'")
    print(f"  proposed_series: '{row['proposed_series']}'")
    print(f"  series_source: '{row['series_source']}'")
    print(f"  file_title: {row['file_title']}")
