#!/usr/bin/env python3
"""Summary of series extraction after the fix."""

import csv

with open('regen.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Count by source
by_source = {}
for r in rows:
    if r.get('proposed_series', '').strip():
        src = r.get('series_source', 'unknown')
        by_source[src] = by_source.get(src, 0) + 1

total_with_series = sum(by_source.values())
total_empty = len(rows) - total_with_series

print('Series extraction results:')
print('-' * 40)
for source in sorted(by_source.keys()):
    print(f'  {source:20s}: {by_source[source]:3d} files')
print(f'  {"(no series)":20s}: {total_empty:3d} files')
print('-' * 40)
print(f'  Total with series   : {total_with_series:3d} files')
print(f'  Total all files     : {len(rows):3d}')
pct = 100.0 * total_with_series / len(rows)
print(f'  Coverage            : {pct:5.1f}%')
