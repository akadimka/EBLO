#!/usr/bin/env python3
"""
Генерация analysis-файлов из regen.csv для ручного анализа качества серий.

Файлы:
  analysis_missing_series.csv     — записи без серии + соседи по папке
  analysis_filename_source.csv    — серии из имени файла
  analysis_year_numbers.csv       — series_number похож на год/большое число
  analysis_short_series.csv       — слишком короткие названия серий
  analysis_series_eq_author.csv   — серия совпадает с автором
  analysis_folder_dataset_series.csv — серии из folder_dataset
"""

import csv
import re
from pathlib import Path
from collections import defaultdict

INPUT_CSV = 'regen.csv'

FIELDS = ['file_path', 'proposed_author', 'proposed_series', 'series_source',
          'metadata_series', 'metadata_series_number', 'series_number']


def read_regen():
    with open(INPUT_CSV, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)
    print(f"  -> {path}: {len(rows)} rows")


def norm(s):
    return (s or '').rstrip('. ').strip().lower().replace('ё', 'е')


# ─────────────────────────────────────────────
# analysis_missing_series.csv
# Проблемная запись + все соседи из той же папки
# ─────────────────────────────────────────────
def make_missing(rows):
    # Сгруппировать все записи по папке
    by_folder = defaultdict(list)
    for r in rows:
        folder = str(Path(r['file_path']).parent)
        by_folder[folder].append(r)

    missing_paths = {r['file_path'] for r in rows
                     if not r['proposed_series'].strip()
                     and r['series_source'] != 'no_series_folder'}

    MAX_CONTEXT = 3  # максимум не-проблемных соседей на блок
    fieldnames = ['row_type'] + FIELDS
    out = []
    seen_folders = set()

    for r in rows:
        if r['file_path'] not in missing_paths:
            continue
        folder = str(Path(r['file_path']).parent)
        if folder in seen_folders:
            continue
        seen_folders.add(folder)

        # Все PROBLEM из этой папки
        problems = [nb for nb in by_folder[folder] if nb['file_path'] in missing_paths]
        for p in problems:
            out.append({'row_type': 'PROBLEM', **{f: p.get(f, '') for f in FIELDS}})

        # До MAX_CONTEXT не-проблемных соседей как контекст
        context = [nb for nb in by_folder[folder] if nb['file_path'] not in missing_paths]
        for nb in context[:MAX_CONTEXT]:
            out.append({'row_type': 'context', **{f: nb.get(f, '') for f in FIELDS}})

    write_csv('analysis_missing_series.csv', fieldnames, out)


# ─────────────────────────────────────────────
# analysis_filename_source.csv
# ─────────────────────────────────────────────
def make_filename_source(rows):
    out = [r for r in rows if 'filename' in (r.get('series_source') or '')]
    write_csv('analysis_filename_source.csv', FIELDS, out)


# ─────────────────────────────────────────────
# analysis_year_numbers.csv
# series_number >= 100 или выглядит как год
# ─────────────────────────────────────────────
def make_year_numbers(rows):
    out = []
    for r in rows:
        sn = (r.get('series_number') or '').strip()
        if sn and re.match(r'^\d+$', sn) and int(sn) >= 100:
            out.append(r)
    write_csv('analysis_year_numbers.csv', FIELDS, out)


# ─────────────────────────────────────────────
# analysis_short_series.csv
# Очень короткие серии (1-2 символа или одна цифра)
# ─────────────────────────────────────────────
def make_short_series(rows):
    out = []
    for r in rows:
        s = (r.get('proposed_series') or '').strip()
        if s and (len(s) <= 2 or re.match(r'^\d{1,2}$', s)):
            out.append(r)
    write_csv('analysis_short_series.csv', FIELDS, out)


# ─────────────────────────────────────────────
# analysis_series_eq_author.csv
# ─────────────────────────────────────────────
def make_series_eq_author(rows):
    out = []
    for r in rows:
        s = norm(r.get('proposed_series') or '')
        a = norm(r.get('proposed_author') or '')
        if s and a and s == a:
            out.append(r)
    write_csv('analysis_series_eq_author.csv', FIELDS, out)


# ─────────────────────────────────────────────
# analysis_folder_dataset_series.csv
# ─────────────────────────────────────────────
def make_folder_dataset(rows):
    out = [r for r in rows if (r.get('series_source') or '') == 'folder_dataset']
    write_csv('analysis_folder_dataset_series.csv', FIELDS, out)


# ─────────────────────────────────────────────

if __name__ == '__main__':
    print(f"Reading {INPUT_CSV}...")
    rows = read_regen()
    print(f"  {len(rows)} records")

    make_missing(rows)
    make_filename_source(rows)
    make_year_numbers(rows)
    make_short_series(rows)
    make_series_eq_author(rows)
    make_folder_dataset(rows)

    print("Done.")
