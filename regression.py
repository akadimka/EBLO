"""
Regression testing для EBLO pipeline.

Использование:
  python regression.py snapshot [--stage=csv|groups|all] [--dir=Test1]
  python regression.py compare  [--stage=csv|groups|all] [--baseline=<file>]
  python regression.py approve  [--stage=csv|groups|all]
  python regression.py run      [--stage=csv|groups|all] [--dir=Test1]
    (snapshot + compare + отчёт в одном шаге)
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
import json
import re
import csv
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

# ── Пути ──────────────────────────────────────────────────────────────────────
PROJECT_DIR  = Path(__file__).parent
SNAPSHOTS_DIR = PROJECT_DIR / 'test_snapshots'
SNAPSHOTS_DIR.mkdir(exist_ok=True)

# ── Импорты пайплайна ─────────────────────────────────────────────────────────
sys.path.insert(0, str(PROJECT_DIR))

def _import_pipeline():
    from regen_csv import RegenCSVService
    from fb2_compiler import FB2CompilerService
    from logger import Logger
    return RegenCSVService, FB2CompilerService, Logger

# ── Предсказание имени файла (реплика gui_compiler._on_select) ─────────────────
def _predict_filename(service, group) -> str:
    """Вычислить предсказанное имя файла для группы (без GUI)."""
    try:
        clean_series = service._clean_series_name(group.series)
        safe_author  = re.sub(r'[\\/:*?"<>|]', '_', group.author)
        part_count   = getattr(group, 'part_count', 0)
        top_lo, top_hi, n_volumes, has_subseries, n_top_arcs = service._run_stats(group.books)
        safe_series  = re.sub(r'[/:*?"<>|]', '_', service._series_to_display(clean_series))
        sc = getattr(group, 'series_complete', True)

        _arc_part_count = 0
        def _is_arc_unit(b):
            lo, hi = service._precompiled_range(b, group.series)
            if lo == hi > 0:
                return True
            return (b.sort_key[0] == 0 and b.sort_key[1] > 0 and b.sort_key[2] == 0)

        _all_arc_point = bool(group.books) and all(_is_arc_unit(b) for b in group.books)
        if _all_arc_point:
            _swords_idx = {kw.lower(): idx
                           for idx, kw in enumerate(service._SERIES_WORDS) if kw}
            _swords_pat = re.compile('|'.join(re.escape(k) for k in _swords_idx), re.IGNORECASE)
            for b in group.books:
                _lo, _hi = service._precompiled_range(b, group.series)
                if _lo == _hi > 0:
                    _st = (b.abs_path.stem + ' ' + (b.record.file_title or '')).lower()
                    _m = _swords_pat.search(_st)
                    if _m:
                        _arc_part_count += _swords_idx[_m.group(0).lower()]
                    else:
                        _rng = re.search(r'(\d+)\s*[-–—]\s*(\d+)', b.abs_path.stem)
                        if _rng:
                            _r_lo, _r_hi = int(_rng.group(1)), int(_rng.group(2))
                            _arc_part_count += _r_hi - _r_lo + 1 if _r_hi > _r_lo and _r_hi - _r_lo < 50 else 1
                        else:
                            _arc_part_count += 1
                else:
                    _arc_part_count += 1
            if _arc_part_count <= n_volumes:
                _arc_part_count = 0

        _top_arc_pos = sorted({
            b.sort_key[1] for b in group.books
            if b.sort_key[0] == 0 and b.sort_key[1]
        })
        _arc_has_gaps = (
            len(_top_arc_pos) >= 2 and
            _top_arc_pos != list(range(_top_arc_pos[0], _top_arc_pos[-1] + 1))
        )
        _sc = True if _arc_part_count > 0 else sc
        _has_exclusions = bool(getattr(group, 'excluded_paths', None) or
                               getattr(group, 'auto_excluded_paths', None))
        _arc_partial = _all_arc_point and _arc_part_count > 0 and not sc

        if _has_exclusions or _arc_has_gaps or _arc_partial:
            _lbl = 'ч.' if (has_subseries and n_top_arcs and n_top_arcs >= 2) or _arc_partial else 'т.'
            _base = f'{_lbl} {top_lo}' if top_lo == top_hi else f'{_lbl} {top_lo}-{top_hi}'
            suffix = f'{_base} в {_arc_part_count} книгах' if _arc_partial and _arc_part_count > 0 else _base
        elif has_subseries and n_top_arcs and n_top_arcs >= 2:
            suffix = service._series_suffix(n_top_arcs, top_lo, top_hi,
                                            _arc_part_count or n_volumes,
                                            series_complete=_sc, use_parts=True)
        elif has_subseries and n_top_arcs == 1 and n_volumes > 1 and top_lo > 1:
            suffix = f'ч. {top_lo} в {n_volumes} книгах'
        else:
            suffix = service._series_suffix(n_volumes, top_lo, top_hi,
                                            _arc_part_count or part_count,
                                            series_complete=_sc)

        return f'{safe_author} - {safe_series} ({suffix}).fb2'
    except Exception as e:
        return f'ERROR: {e}'


# ── Снапшоты ──────────────────────────────────────────────────────────────────
def _group_to_dict(service, group) -> Dict[str, Any]:
    return {
        'author':           group.author,
        'series':           group.series,
        'volume_range':     group.volume_range or '',
        'series_complete':  getattr(group, 'series_complete', True),
        'cleanup_only':     getattr(group, 'cleanup_only', False),
        'book_count':       len(group.books),
        'books':            sorted(b.abs_path.name for b in group.books),
        'duplicates':       sorted(p.name for p in (group.duplicate_paths or [])),
        'kept':             sorted(p.name for p in (getattr(group, 'kept_paths', None) or [])),
        'predicted_file':   _predict_filename(service, group),
        'sort_sources':     sorted({b.sort_source for b in group.books}),
    }


def snapshot_csv(records, scan_dir: str) -> List[Dict]:
    rows = []
    for r in records:
        rows.append({
            'file':           Path(r.file_path).name,
            'author':         r.proposed_author or '',
            'author_source':  r.author_source or '',
            'series':         r.proposed_series or '',
            'series_source':  r.series_source or '',
            'series_number':  r.series_number or '',
            'file_title':     r.file_title or '',
        })
    return sorted(rows, key=lambda x: (x['file'],))


def snapshot_groups(service, groups) -> List[Dict]:
    return [_group_to_dict(service, g) for g in groups]


def run_pipeline(scan_dir: str, stage: str):
    """Запустить пайплайн и вернуть (records, groups)."""
    RegenCSVService, FB2CompilerService, Logger = _import_pipeline()

    print(f'  [1/3] Запуск passes 1-6 на {scan_dir}...', end='', flush=True)
    svc = RegenCSVService()
    records = svc.generate_csv(scan_dir, output_csv_path=None)
    print(f' {len(records)} записей')

    groups = []
    if stage in ('groups', 'all'):
        print(f'  [2/3] find_groups...', end='', flush=True)
        compiler = FB2CompilerService(logger=Logger())
        groups = compiler.find_groups(records, Path(scan_dir))
        print(f' {len(groups)} групп')

    return records, groups


# ── Сохранение / загрузка снапшотов ──────────────────────────────────────────
def save_snapshot(data: Dict, stage: str, label: str = '') -> Path:
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    name = f'{stage}_{label}_{ts}.json' if label else f'{stage}_{ts}.json'
    path = SNAPSHOTS_DIR / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    return path


def load_snapshot(path: Path) -> Dict:
    return json.loads(path.read_text(encoding='utf-8'))


def get_baseline_path(stage: str) -> Path:
    return SNAPSHOTS_DIR / f'{stage}_baseline.json'


# ── Сравнение ─────────────────────────────────────────────────────────────────
def _key_csv(row):
    return row['file']

def _key_group(row):
    return f"{row['author']}|{row['series']}"


def compare_snapshots(baseline: Dict, current: Dict, stage: str) -> str:
    lines = []
    meta_b = baseline.get('meta', {})
    meta_c = current.get('meta', {})

    lines.append(f'=== {stage.upper()} ===')
    lines.append(f'Baseline:  {meta_b.get("timestamp","?")}  dir={meta_b.get("scan_dir","?")}')
    lines.append(f'Current:   {meta_c.get("timestamp","?")}  dir={meta_c.get("scan_dir","?")}')
    lines.append('')

    if stage == 'csv':
        base_rows = {r['file']: r for r in baseline.get('data', [])}
        curr_rows = {r['file']: r for r in current.get('data', [])}
        added   = sorted(set(curr_rows) - set(base_rows))
        removed = sorted(set(base_rows) - set(curr_rows))
        changed = []
        for k in sorted(set(base_rows) & set(curr_rows)):
            b, c = base_rows[k], curr_rows[k]
            diffs = {f: (b[f], c[f]) for f in b if b.get(f) != c.get(f)}
            if diffs:
                changed.append((k, diffs))

        lines.append(f'Записей: {len(base_rows)} → {len(curr_rows)} '
                     f'(+{len(added)} -{len(removed)} ~{len(changed)})')
        for f in added[:20]:
            lines.append(f'  + {f}')
        for f in removed[:20]:
            lines.append(f'  - {f}')
        for fname, diffs in changed[:30]:
            lines.append(f'  ~ {fname}')
            for field, (old, new) in diffs.items():
                lines.append(f'      {field}: {old!r} → {new!r}')

    elif stage == 'groups':
        base_g = {_key_group(r): r for r in baseline.get('data', [])}
        curr_g = {_key_group(r): r for r in current.get('data', [])}
        added   = sorted(set(curr_g) - set(base_g))
        removed = sorted(set(base_g) - set(curr_g))
        changed = []
        for k in sorted(set(base_g) & set(curr_g)):
            b, c = base_g[k], curr_g[k]
            diffs = {}
            for field in ('predicted_file', 'volume_range', 'series_complete',
                          'book_count', 'books', 'duplicates', 'kept'):
                if b.get(field) != c.get(field):
                    diffs[field] = (b.get(field), c.get(field))
            if diffs:
                changed.append((k, diffs))

        total_b = len(base_g)
        total_c = len(curr_g)
        lines.append(f'Групп: {total_b} → {total_c} '
                     f'(+{len(added)} -{len(removed)} ~{len(changed)})')
        lines.append('')

        if added:
            lines.append(f'── НОВЫЕ ГРУППЫ ({len(added)}) ──')
            for k in added[:20]:
                g = curr_g[k]
                lines.append(f'  + {g["author"]} / {g["series"]}')
                lines.append(f'      → {g["predicted_file"]}')

        if removed:
            lines.append(f'── УДАЛЁННЫЕ ГРУППЫ ({len(removed)}) ──')
            for k in removed[:20]:
                g = base_g[k]
                lines.append(f'  - {g["author"]} / {g["series"]}')
                lines.append(f'      было: {g["predicted_file"]}')

        if changed:
            lines.append(f'── ИЗМЕНИВШИЕСЯ ГРУППЫ ({len(changed)}) ──')
            for k, diffs in changed[:40]:
                author, series = k.split('|', 1)
                lines.append(f'  ~ {author} / {series}')
                for field, (old, new) in diffs.items():
                    if field == 'predicted_file':
                        lines.append(f'      ФАЙЛ:  {old}')
                        lines.append(f'           → {new}')
                    elif field in ('books', 'duplicates', 'kept'):
                        old_s = set(old or [])
                        new_s = set(new or [])
                        for x in sorted(new_s - old_s)[:5]:
                            lines.append(f'      +{field}: {x}')
                        for x in sorted(old_s - new_s)[:5]:
                            lines.append(f'      -{field}: {x}')
                    else:
                        lines.append(f'      {field}: {old!r} → {new!r}')

    if not (added or removed or changed):
        lines.append('  ✓ Изменений нет')

    return '\n'.join(lines)


# ── Команды CLI ───────────────────────────────────────────────────────────────
def cmd_snapshot(args):
    scan_dir = args.dir
    stage    = args.stage
    print(f'Снапшот: stage={stage}, dir={scan_dir}')
    records, groups = run_pipeline(scan_dir, stage)

    RegenCSVService, FB2CompilerService, Logger = _import_pipeline()
    compiler = FB2CompilerService(logger=Logger())

    data = {}
    meta = {'timestamp': datetime.now().isoformat(), 'scan_dir': scan_dir}

    if stage in ('csv', 'all'):
        data['csv'] = {'meta': meta, 'data': snapshot_csv(records, scan_dir)}
    if stage in ('groups', 'all'):
        data['groups'] = {'meta': meta, 'data': snapshot_groups(compiler, groups)}

    stages = ['csv', 'groups'] if stage == 'all' else [stage]
    saved = []
    for s in stages:
        if s in data:
            p = save_snapshot(data[s], s)
            saved.append(p)
            print(f'  Сохранён: {p.name}')
    return saved


def cmd_compare(args):
    stage = args.stage
    stages = ['csv', 'groups'] if stage == 'all' else [stage]
    for s in stages:
        baseline_path = get_baseline_path(s)
        if not baseline_path.exists():
            print(f'  Baseline не найден для {s}: {baseline_path}')
            print(f'  Запустите: python regression.py snapshot --stage={s}  затем approve')
            continue

        # Найти последний снапшот (не baseline)
        candidates = sorted(
            [f for f in SNAPSHOTS_DIR.glob(f'{s}_*.json') if 'baseline' not in f.name],
            key=lambda p: p.stat().st_mtime
        )
        if not candidates:
            print(f'  Нет снапшотов для сравнения ({s}). Запустите snapshot.')
            continue

        current_path = candidates[-1]
        baseline = load_snapshot(baseline_path)
        current  = load_snapshot(current_path)
        print(f'\n{compare_snapshots(baseline, current, s)}')
        print(f'\n  (baseline: {baseline_path.name}, current: {current_path.name})')


def cmd_approve(args):
    stage = args.stage
    stages = ['csv', 'groups'] if stage == 'all' else [stage]
    for s in stages:
        candidates = sorted(
            [f for f in SNAPSHOTS_DIR.glob(f'{s}_*.json') if 'baseline' not in f.name],
            key=lambda p: p.stat().st_mtime
        )
        if not candidates:
            print(f'  Нет снапшотов для approve ({s}).')
            continue
        src = candidates[-1]
        dst = get_baseline_path(s)
        import shutil
        shutil.copy2(src, dst)
        data = load_snapshot(dst)
        n = len(data.get('data', []))
        print(f'  ✓ Baseline обновлён: {dst.name} ({n} записей)')


def cmd_run(args):
    """Snapshot + compare в одном шаге (для CI/pre-commit)."""
    scan_dir = args.dir
    stage    = args.stage
    print(f'Run: stage={stage}, dir={scan_dir}')
    records, groups = run_pipeline(scan_dir, stage)

    RegenCSVService, FB2CompilerService, Logger = _import_pipeline()
    compiler = FB2CompilerService(logger=Logger())

    meta = {'timestamp': datetime.now().isoformat(), 'scan_dir': scan_dir}
    stages = ['csv', 'groups'] if stage == 'all' else [stage]
    has_changes = False

    for s in stages:
        if s == 'csv':
            snap = {'meta': meta, 'data': snapshot_csv(records, scan_dir)}
        else:
            snap = {'meta': meta, 'data': snapshot_groups(compiler, groups)}

        p = save_snapshot(snap, s)
        print(f'  Снапшот сохранён: {p.name}')

        baseline_path = get_baseline_path(s)
        if baseline_path.exists():
            baseline = load_snapshot(baseline_path)
            report = compare_snapshots(baseline, snap, s)
            print(f'\n{report}')
            if 'Изменений нет' not in report:
                has_changes = True
        else:
            print(f'  Baseline не найден — создайте его через approve после первого run.')

    return has_changes


# ── Точка входа ───────────────────────────────────────────────────────────────
def main():
    # Конфиг — папка сканирования по умолчанию
    try:
        import json as _j
        cfg = _j.loads((PROJECT_DIR / 'config.json').read_text(encoding='utf-8'))
        default_dir = cfg.get('last_scan_path', str(PROJECT_DIR / 'Test1'))
    except Exception:
        default_dir = str(PROJECT_DIR / 'Test1')

    parser = argparse.ArgumentParser(description='EBLO Regression Testing')
    sub = parser.add_subparsers(dest='cmd')

    for cmd_name in ('snapshot', 'run'):
        p = sub.add_parser(cmd_name)
        p.add_argument('--stage', default='groups', choices=['csv', 'groups', 'all'])
        p.add_argument('--dir', default=default_dir)

    for cmd_name in ('compare', 'approve'):
        p = sub.add_parser(cmd_name)
        p.add_argument('--stage', default='groups', choices=['csv', 'groups', 'all'])

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        return

    if args.cmd == 'snapshot': cmd_snapshot(args)
    elif args.cmd == 'compare': cmd_compare(args)
    elif args.cmd == 'approve': cmd_approve(args)
    elif args.cmd == 'run':     cmd_run(args)


if __name__ == '__main__':
    main()
