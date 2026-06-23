"""
Генерация regen.csv через полный 6-пасс пайплайн на основе simulation/metadata_cache.db
без доступа к реальным FB2-файлам.

Pass 1 и PRECACHE заменяются чтением данных из БД; всё остальное (Pass 1.5, 2, 2.5,
серии, Pass 3–6) запускается через RegenCSVService как обычно.

Запуск:
    python simulation/gen_csv_offline.py [--db simulation/metadata_cache.db]
                                          [--out simulation/regen.csv]
                                          [--config config.json]
"""
import sys
import io
import json
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SIM_DIR  = Path(__file__).parent
ROOT_DIR = SIM_DIR.parent
sys.path.insert(0, str(ROOT_DIR))


# ── Шаг 1: читаем данные из БД ───────────────────────────────────────────────

def load_records_from_db(db_path: Path) -> Tuple[List, str]:
    """
    Читает все строки из metadata_cache.db, определяет общий корневой путь,
    возвращает (список BookRecord с относительными путями, корневой путь).
    """
    from passes.pass1_read_files import BookRecord

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        'SELECT file_path, metadata, content_hash FROM file_metadata ORDER BY file_path'
    ).fetchall()
    conn.close()

    if not rows:
        print('ERROR: база пустая', file=sys.stderr)
        sys.exit(1)

    # Определяем общий корневой префикс из всех file_path
    all_paths = [r[0] for r in rows]
    root = _find_common_root(all_paths)
    print(f'[DB] {len(rows)} записей, корневой путь: {root}')

    records: List[BookRecord] = []
    for file_path_abs, meta_json, content_hash in rows:
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except (ValueError, TypeError):
            meta = {}

        authors    = (meta.get('authors') or '').strip()
        series     = (meta.get('series') or '').strip()
        title      = (meta.get('title') or '').strip()
        genre      = (meta.get('genre') or '').strip()
        snum       = str(meta.get('series_number') or '').strip()

        # Относительный путь для folder-parsing логики
        rel = _make_relative(file_path_abs, root)

        rec = BookRecord(
            file_path          = rel,
            file_title         = title,
            metadata_authors   = authors,
            proposed_author    = '',        # Pass 2 заполнит
            author_source      = '',
            metadata_series    = series,
            proposed_series    = '',        # Pass серий заполнит
            series_source      = '',
            metadata_genre     = genre,
            series_number      = snum,
            needs_filename_fallback = True, # Pass 2 попробует имя файла
            content_hash       = content_hash or '',
        )
        records.append(rec)

    return records, root


def _find_common_root(paths: List[str]) -> str:
    """Определить общий корневой каталог для всех путей."""
    if not paths:
        return ''
    # Нормализуем разделители
    norm = [p.replace('\\', '/') for p in paths]
    parts_list = [p.split('/') for p in norm]
    common = parts_list[0][:]
    for parts in parts_list[1:]:
        new_common = []
        for a, b in zip(common, parts):
            if a == b:
                new_common.append(a)
            else:
                break
        common = new_common
        if not common:
            break
    # Возвращаем без trailing slash
    return '/'.join(common)


def _make_relative(abs_path: str, root: str) -> str:
    """Срезать корневой префикс, оставить относительный путь."""
    norm = abs_path.replace('\\', '/')
    if root and norm.startswith(root + '/'):
        return norm[len(root) + 1:].replace('/', '\\')
    return abs_path


# ── Шаг 2: строим author_folder_cache из путей в БД ─────────────────────────

def build_author_cache(records, work_dir: Path, settings, logger) -> Dict:
    """
    Воссоздаём author_folder_cache из уникальных папок БД
    с помощью той же логики что и Precache.
    """
    from passes.folder_author_parser import parse_author_from_folder_name

    # Загружаем имена для валидации (те же что использует Precache)
    male_names:   Set[str] = set(n.lower() for n in (settings.get_male_names() or []))
    female_names: Set[str] = set(n.lower() for n in (settings.get_female_names() or []))

    def _has_valid_name(author: str) -> bool:
        for word in author.replace(',', ' ').split():
            w = word.strip('.-').lower().replace('ё', 'е')
            if w in male_names or w in female_names:
                return True
        return False

    conversions = settings.get_author_surname_conversions() or {}

    # Собираем уникальные папки (от корня до папки файла)
    unique_dirs: Set[str] = set()
    for rec in records:
        parts = Path(rec.file_path).parts
        # Добавляем все промежуточные пути
        for depth in range(1, len(parts)):
            unique_dirs.add('\\'.join(parts[:depth]))

    cache: Dict[Path, Tuple[str, str]] = {}
    for rel_dir in unique_dirs:
        folder_abs = work_dir / rel_dir
        folder_name = Path(rel_dir).name
        folder_name_for_parse = conversions.get(folder_name, folder_name)
        author = parse_author_from_folder_name(
            folder_name_for_parse,
            male_names=male_names,
            female_names=female_names,
        )
        if author and _has_valid_name(author):
            cache[folder_abs] = (author, 'high')

    print(f'[PRECACHE-offline] Папок автора: {len(cache)}')
    return cache, male_names, female_names


# ── Главная функция ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db',     default=str(SIM_DIR / 'metadata_cache.db'))
    parser.add_argument('--out',    default=str(SIM_DIR / 'regen.csv'))
    parser.add_argument('--config', default=str(ROOT_DIR / 'config.json'))
    args = parser.parse_args()

    db_path  = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        print(f'ERROR: база не найдена: {db_path}', file=sys.stderr)
        sys.exit(1)

    # ── Читаем записи из БД ──────────────────────────────────────────────────
    records, root_str = load_records_from_db(db_path)
    work_dir = Path(root_str.replace('/', '\\')) if root_str else Path('.')

    # ── Создаём сервис ───────────────────────────────────────────────────────
    from regen_csv import RegenCSVService
    from precache import Precache

    svc = RegenCSVService(config_path=str(args.config))
    svc.work_dir   = work_dir
    svc.output_csv = out_path
    svc._do_save_csv = True

    # ── Строим author_folder_cache без диска ─────────────────────────────────
    author_cache, male_names, female_names = build_author_cache(
        records, work_dir, svc.settings, svc.logger
    )
    svc.author_folder_cache = author_cache

    # ── Monkey-patch: Pass1 возвращает наши записи ───────────────────────────
    import passes.pass1_read_files as _p1_mod

    class _Pass1FromDB:
        def __init__(self, *a, **kw):
            pass
        def execute(self):
            return records

    _orig_pass1 = _p1_mod.Pass1ReadFiles
    _p1_mod.Pass1ReadFiles = _Pass1FromDB

    # ── Monkey-patch: Precache возвращает готовый кэш ────────────────────────
    class _PrecacheFromDB:
        def __init__(self, *a, **kw):
            self.male_names   = male_names
            self.female_names = female_names
            self.author_folder_cache = author_cache

        def execute(self):
            return author_cache

    _orig_precache = None
    import precache as _precache_mod
    _orig_precache = _precache_mod.Precache
    _precache_mod.Precache = _PrecacheFromDB

    # Также патчим в regen_csv (там уже импортировано)
    import regen_csv as _regen_mod
    _orig_regen_pass1    = getattr(_regen_mod, 'Pass1ReadFiles', None)
    _orig_regen_precache = getattr(_regen_mod, 'Precache', None)
    _regen_mod.Pass1ReadFiles = _Pass1FromDB
    _regen_mod.Precache       = _PrecacheFromDB

    try:
        success = svc.regenerate()
    finally:
        # Восстанавливаем оригиналы
        _p1_mod.Pass1ReadFiles = _orig_pass1
        _precache_mod.Precache = _orig_precache
        if _orig_regen_pass1:
            _regen_mod.Pass1ReadFiles = _orig_regen_pass1
        if _orig_regen_precache:
            _regen_mod.Precache = _orig_regen_precache

    if success:
        print(f'\nГотово: {out_path}')
    else:
        print('\nERROR: regenerate() вернул False', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
