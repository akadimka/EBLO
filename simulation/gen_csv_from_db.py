"""
Генерация regen.csv из metadata_cache.db без доступа к реальным FB2-файлам.

Результат: simulation/regen.csv — пригоден для simulate.py / simulate_rounds.py.

Запуск:
    python simulation/gen_csv_from_db.py [--db simulation/metadata_cache.db] [--out simulation/regen.csv]
"""
import sys
import io
import csv
import json
import sqlite3
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SIM_DIR = Path(__file__).parent

CSV_COLUMNS = [
    'file_path', 'metadata_authors', 'proposed_author', 'author_source',
    'metadata_series', 'proposed_series', 'series_source',
    'series_number', 'file_title', 'metadata_genre', 'delete_flag',
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',  default=str(SIM_DIR / 'metadata_cache.db'))
    parser.add_argument('--out', default=str(SIM_DIR / 'regen.csv'))
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        print(f'ERROR: база не найдена: {db_path}', file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        'SELECT file_path, metadata, content_hash FROM file_metadata ORDER BY file_path'
    ).fetchall()
    conn.close()

    written = skipped = 0
    with out_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for file_path, meta_json, _content_hash in rows:
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (ValueError, TypeError):
                skipped += 1
                continue

            authors = (meta.get('authors') or '').strip()
            series  = (meta.get('series') or '').strip()
            title   = (meta.get('title') or '').strip()
            genre   = (meta.get('genre') or '').strip()
            snum    = str(meta.get('series_number') or '').strip()

            writer.writerow({
                'file_path':        file_path,
                'metadata_authors': authors,
                'proposed_author':  authors,
                'author_source':    'metadata',
                'metadata_series':  series,
                'proposed_series':  series,
                'series_source':    'metadata',
                'series_number':    snum,
                'file_title':       title,
                'metadata_genre':   genre,
                'delete_flag':      '',
            })
            written += 1

    print(f'Записей в БД: {written + skipped}')
    if skipped:
        print(f'Пропущено (нет metadata): {skipped}')
    print(f'Записано в CSV: {written}')
    print(f'Результат: {out_path}')


if __name__ == '__main__':
    main()
