#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import csv

csv_path = r'C:\Temp\fb2parser\regen.csv'
out_path = 'legion_rows.txt'

with open(csv_path, encoding='utf-8') as f, open(out_path, 'w', encoding='utf-8') as out:
    reader = csv.reader(f)
    header = next(reader)
    out.write('|'.join(header) + '\n')
    for row in reader:
        if any('егион' in cell for cell in row):
            out.write('|'.join(row) + '\n')

print("Done, written to", out_path)
