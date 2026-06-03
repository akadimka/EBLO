"""Сравнение двух CSV-снапшотов: эталон vs текущий regen.csv.

Использование:
    python compare_csv.py                    # сравнить regen_golden.csv vs regen.csv
    python compare_csv.py before.csv after.csv
"""
import csv
import sys

def load(path):
    with open(path, encoding='utf-8') as f:
        return {row['file_path']: row for row in csv.DictReader(f)}

def main():
    before_path = sys.argv[1] if len(sys.argv) > 1 else 'regen_golden.csv'
    after_path  = sys.argv[2] if len(sys.argv) > 2 else 'regen.csv'

    before = load(before_path)
    after  = load(after_path)

    keys_before = set(before)
    keys_after  = set(after)

    added   = keys_after  - keys_before
    removed = keys_before - keys_after
    common  = keys_before & keys_after

    changed_author = []
    changed_series = []

    for fp in sorted(common):
        b, a = before[fp], after[fp]
        if b.get('proposed_author','') != a.get('proposed_author',''):
            changed_author.append((fp, b.get('proposed_author',''), a.get('proposed_author','')))
        if b.get('proposed_series','') != a.get('proposed_series',''):
            changed_series.append((fp, b.get('proposed_series',''), a.get('proposed_series','')))

    print(f'Records before: {len(before)},  after: {len(after)}')
    print(f'Added: {len(added)},  Removed: {len(removed)}')
    print(f'proposed_author changes: {len(changed_author)}')
    print(f'proposed_series changes: {len(changed_series)}')

    if added:
        print('\n--- ADDED (first 10) ---')
        for fp in sorted(added)[:10]:
            print(f'  + {fp.split(chr(92))[-1]}')

    if removed:
        print('\n--- REMOVED (first 10) ---')
        for fp in sorted(removed)[:10]:
            print(f'  - {fp.split(chr(92))[-1]}')

    if changed_author:
        print(f'\n--- proposed_author CHANGES (first 20 of {len(changed_author)}) ---')
        for fp, old, new in changed_author[:20]:
            print(f'  {fp.split(chr(92))[-1]}')
            print(f'    before: {old}')
            print(f'    after:  {new}')

    if changed_series:
        print(f'\n--- proposed_series CHANGES (first 20 of {len(changed_series)}) ---')
        for fp, old, new in changed_series[:20]:
            print(f'  {fp.split(chr(92))[-1]}')
            print(f'    before: {old}')
            print(f'    after:  {new}')

    if not added and not removed and not changed_author and not changed_series:
        print('\nOK: Identical — no differences found.')
    else:
        total = len(added) + len(removed) + len(changed_author) + len(changed_series)
        print(f'\nTotal differences: {total}')

if __name__ == '__main__':
    main()
