"""
3-раундовая симуляция компиляции.  Никаких физических файлов не создаётся.

Раунд 1: пайплайн на Test1 «как есть» → какие группы будут скомпилированы
Раунд 2: то же + синтетические записи скомпилированных файлов → что станет дублями
Раунд 3: только скомпилированные файлы (исходники убраны) → что останется

Запуск:
    python simulation/simulate_rounds.py [--dir=<path>]
"""
import sys, re
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

SIM_DIR  = Path(__file__).parent
ROOT_DIR = SIM_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DEFAULT_DIR = 'C:/Users/dmitriy.murov/Downloads/TriblerDownloads/Test1'

# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(scan_dir: str):
    from regen_csv import RegenCSVService
    from fb2_compiler import FB2CompilerService
    from logger import Logger
    svc = RegenCSVService()
    records = svc.generate_csv(scan_dir, output_csv_path=None)
    compiler = FB2CompilerService(logger=Logger())
    groups = compiler.find_groups(records, Path(scan_dir))
    return records, groups, compiler


def make_compiled_record(group, scan_dir: Path, predicted_name: str):
    """Синтетический BookRecord для скомпилированного файла."""
    from passes.pass1_read_files import BookRecord
    # Определяем папку: берём папку первой книги группы
    first_book_abs = group.books[0].abs_path if group.books else None
    if first_book_abs:
        folder = first_book_abs.parent.relative_to(scan_dir)
    else:
        folder = Path(re.sub(r'[\\/:*?"<>|]', '_', group.author))
    rel_path = str(folder / predicted_name)

    # Диапазон томов → series_number формата "lo-hi" (признак предкомпиляции)
    vols = sorted({b.sort_key[1] for b in group.books if b.sort_key[1] > 0})
    sn = f'{vols[0]}-{vols[-1]}' if len(vols) >= 2 else (str(vols[0]) if vols else '1-?')

    return BookRecord(
        file_path        = rel_path,
        file_title       = group.series,
        metadata_authors = group.author,
        proposed_author  = group.author,
        author_source    = 'filename',
        metadata_series  = group.series,
        proposed_series  = group.series,
        series_source    = 'metadata',
        series_number    = sn,
        content_hash     = '',
    )


def describe_group(g, label='') -> List[str]:
    lines = []
    if label:
        lines.append(f'  [{label}]')
    flag = '[CLEANUP]' if g.cleanup_only else '[COMPILE]'
    kept_str = ', '.join(p.name for p in (g.kept_paths or []))
    dup_str  = ', '.join(p.name for p in (g.duplicate_paths or []))
    books_str = ', '.join(b.abs_path.name for b in g.books)
    lines.append(f'  {flag} {g.author} / {g.series}')
    if g.cleanup_only:
        lines.append(f'    KEEP: {kept_str}')
        lines.append(f'    DEL:  {dup_str}')
    else:
        lines.append(f'    BOOKS ({len(g.books)}): {books_str}')
        if dup_str:
            lines.append(f'    DEL:  {dup_str}')
    return lines


def run_round(label: str, records, scan_dir: Path, compiler, prev_groups=None):
    """Запустить find_groups и вернуть (groups, predicted_names)."""
    import re as _re
    groups = compiler.find_groups(records, scan_dir)

    compile_groups  = [g for g in groups if not g.cleanup_only]
    cleanup_groups  = [g for g in groups if g.cleanup_only]
    total_del       = sum(len(g.duplicate_paths or []) for g in groups)

    print(f'\n{"="*70}')
    print(f'РАУНД {label}')
    print(f'  Групп компиляции : {len(compile_groups)}')
    print(f'  Групп cleanup    : {len(cleanup_groups)}')
    print(f'  Всего к удалению : {total_del}')
    print(f'{"="*70}')

    # Predicted names for compile groups
    predicted = {}
    for g in compile_groups:
        try:
            clean  = compiler._clean_series_name(g.series)
            safe_a = _re.sub(r'[\\/:*?"<>|]', '_', g.author)
            safe_s = _re.sub(r'[/:*?"<>|]', '_', compiler._series_to_display(clean))
            lo, hi, nv, hs, na = compiler._run_stats(g.books)
            sc = getattr(g, 'series_complete', True)
            has_excl = bool(g.excluded_paths or g.auto_excluded_paths)
            if has_excl:
                lbl_ = 'т.'
                base_ = f'{lbl_} {lo}' if lo == hi else f'{lbl_} {lo}-{hi}'
                suffix = base_
            elif hs and na and na >= 2:
                suffix = compiler._series_suffix(na, lo, hi, nv, series_complete=sc, use_parts=True)
            else:
                suffix = compiler._series_suffix(nv, lo, hi, getattr(g, 'part_count', 0), series_complete=sc)
            suffix = compiler._suppress_redundant_suffix(safe_s, suffix)
            fname = f'{safe_a} - {safe_s} ({suffix}).fb2' if suffix else f'{safe_a} - {safe_s}.fb2'
            predicted[id(g)] = fname
        except Exception as e:
            predicted[id(g)] = f'ERROR: {e}'

    for g in sorted(compile_groups, key=lambda x: (x.author, x.series)):
        fname = predicted.get(id(g), '?')
        dups  = ', '.join(p.name for p in (g.duplicate_paths or []))
        print(f'\n  COMPILE  {g.author} / {g.series}')
        print(f'    Файл    : {fname}')
        print(f'    Книг    : {len(g.books)}')
        if dups:
            print(f'    Дубли   : {dups}')

    for g in sorted(cleanup_groups, key=lambda x: (x.author, x.series)):
        kept  = ', '.join(p.name for p in (g.kept_paths or []))
        dups  = ', '.join(p.name for p in (g.duplicate_paths or []))
        print(f'\n  CLEANUP  {g.author} / {g.series}')
        print(f'    Оставить: {kept}')
        print(f'    Удалить : {dups}')

    return groups, predicted


# ─────────────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', default=DEFAULT_DIR)
    args = parser.parse_args()

    scan_dir = Path(args.dir)
    print(f'Папка: {scan_dir}')
    print('Запускаю пайплайн…')
    records, _, compiler = run_pipeline(str(scan_dir))
    print(f'Записей: {len(records)}')

    # ── РАУНД 1 ─────────────────────────────────────────────────────────────
    r1_groups, r1_predicted = run_round('1 (исходники, без удаления)', records, scan_dir, compiler)

    # ── РАУНД 2: добавляем скомпилированные файлы к исходникам ───────────────
    r1_compile = [g for g in r1_groups if not g.cleanup_only]
    synth_records = []
    for g in r1_compile:
        fname = r1_predicted.get(id(g), '')
        if not fname or fname.startswith('ERROR'):
            continue
        synth_records.append(make_compiled_record(g, scan_dir, fname))

    print(f'\n  → Добавляю {len(synth_records)} синтетических записей скомпилированных файлов')
    records_r2 = list(records) + synth_records
    r2_groups, r2_predicted = run_round('2 (исходники + скомпилированные, без удаления)',
                                        records_r2, scan_dir, compiler)

    # ── РАУНД 3: только скомпилированные файлы (исходники убраны) ────────────
    # Удаляем:
    #   1. Все книги из compile-групп Раунда 1 (они будут заменены скомпилированными файлами)
    #   2. Все дубликаты из cleanup-групп Раунда 1 (они удаляются в рамках cleanup)
    r1_source_names = {b.abs_path.name for g in r1_compile for b in g.books}
    r1_cleanup_dup_names = {p.name for g in r1_groups if g.cleanup_only for p in (g.duplicate_paths or [])}
    r1_compile_dup_names = {p.name for g in r1_compile for p in (g.duplicate_paths or [])}
    deleted_names = r1_source_names | r1_cleanup_dup_names | r1_compile_dup_names
    records_r3 = [r for r in records_r2 if Path(r.file_path).name not in deleted_names]
    print(f'\n  → Раунд 3: убираем {len(deleted_names)} файлов '
          f'({len(r1_source_names)} compile-исходников + {len(r1_cleanup_dup_names)} cleanup-дублей), '
          f'остаётся {len(records_r3)} записей')
    r3_groups, _ = run_round('3 (только скомпилированные файлы, с удалением исходников)',
                             records_r3, scan_dir, compiler)

    # ── Итог ─────────────────────────────────────────────────────────────────
    r2_compile_count = sum(1 for g in r2_groups if not g.cleanup_only)
    r2_cleanup_count = sum(1 for g in r2_groups if g.cleanup_only)
    r3_total         = len(r3_groups)

    print(f'\n{"="*70}')
    print('ИТОГ')
    print(f'  Раунд 1: {len([g for g in r1_groups if not g.cleanup_only])} compile-групп  '
          f'+ {len([g for g in r1_groups if g.cleanup_only])} cleanup')
    print(f'  Раунд 2: {r2_compile_count} compile-групп  + {r2_cleanup_count} cleanup')
    print(f'    (ожидаем: 0 compile-групп, {len(r1_compile)} cleanup)')
    print(f'  Раунд 3: {r3_total} групп  (ожидаем: 0)')
    print(f'{"="*70}')

    if r2_compile_count == 0:
        print('  ✓ Раунд 2: пайплайн корректно не компилирует повторно')
    else:
        print(f'  ✗ Раунд 2: {r2_compile_count} групп пытаются компилироваться повторно — ПРОБЛЕМА')

    if r3_total == 0:
        print('  ✓ Раунд 3: после удаления исходников нет лишних групп')
    else:
        print(f'  ✗ Раунд 3: {r3_total} групп остаётся — ПРОБЛЕМА')


if __name__ == '__main__':
    main()
