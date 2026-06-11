"""
Симуляция поиска дубликатов и компиляции на CSV + metadata_cache.db без исходных файлов.

Запуск:
    python simulation/simulate.py [--dupes] [--compile] [--out results.txt]
По умолчанию выполняются оба режима и результат пишется в simulation/results.txt.
"""
import sys
import os
import csv
import re
import sqlite3
import unicodedata
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

import io as _io
sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

SIM_DIR  = Path(__file__).parent
ROOT_DIR = SIM_DIR.parent
sys.path.insert(0, str(ROOT_DIR))

CSV_PATH = SIM_DIR / 'regen.csv'
DB_PATH  = SIM_DIR / 'metadata_cache.db'

# ── Вспомогательные нормализаторы (копия из gui_duplicate_finder) ────────────

def _norm_str(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '').lower().replace('ё', 'е')
    s = re.sub(r'[«»"\'„“”„\(\)\[\]…]', '', s)
    return re.sub(r'\s+', ' ', s).strip()

def _norm_author(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '').lower().replace('ё', 'е')
    s = re.sub(r'\.', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()

def _rec_authors(proposed: str, meta: str) -> frozenset:
    src = proposed if proposed else meta
    parts = re.split(r'[;,]', src)
    return frozenset(a for a in (_norm_author(p) for p in parts) if len(a) >= 3)


# ── Загрузка данных ──────────────────────────────────────────────────────────

@dataclass
class SimRecord:
    file_path: str
    proposed_author: str
    metadata_authors: str
    proposed_series: str
    series_number: str
    file_title: str
    series_source: str
    content_hash: str = ''

def load_records() -> List[SimRecord]:
    records = []
    with open(CSV_PATH, encoding='utf-8', newline='') as f:
        for row in csv.DictReader(f):
            if row.get('delete_flag'):
                continue
            records.append(SimRecord(
                file_path     = row['file_path'],
                proposed_author = row.get('proposed_author', ''),
                metadata_authors= row.get('metadata_authors', ''),
                proposed_series = row.get('proposed_series', ''),
                series_number   = row.get('series_number', ''),
                file_title      = row.get('file_title', ''),
                series_source   = row.get('series_source', ''),
            ))
    return records

def load_hashes() -> Dict[str, str]:
    """file_path → content_hash из metadata_cache.db"""
    hashes: Dict[str, str] = {}
    if not DB_PATH.exists():
        return hashes
    conn = sqlite3.connect(DB_PATH)
    try:
        for fp, ch in conn.execute(
                "SELECT file_path, content_hash FROM file_metadata WHERE content_hash IS NOT NULL AND content_hash != ''"):
            # В DB хранится абсолютный путь; нам нужен относительный хвост.
            # CSV хранит относительный путь вида «Автор\Файл.fb2».
            # Берём последние N компонентов из abs_path.
            p = Path(fp)
            # Ключ — последние 2 части (папка автора + имя файла)
            key2 = str(Path(*p.parts[-2:])) if len(p.parts) >= 2 else p.name
            key3 = str(Path(*p.parts[-3:])) if len(p.parts) >= 3 else key2
            hashes[key2] = ch
            hashes[key3] = ch
            hashes[p.name] = ch  # fallback по имени файла
    finally:
        conn.close()
    return hashes

def attach_hashes(records: List[SimRecord], hashes: Dict[str, str]):
    matched = 0
    for r in records:
        p = Path(r.file_path)
        # Пробуем совпадение по убывающей длине пути
        for parts_n in range(min(4, len(p.parts)), 0, -1):
            key = str(Path(*p.parts[-parts_n:]))
            if key in hashes:
                r.content_hash = hashes[key]
                matched += 1
                break
    return matched


# ── Поиск дубликатов ─────────────────────────────────────────────────────────

@dataclass
class DupResult:
    dup_path: str
    src_path: str
    reason: Set[str]

def find_duplicates(records: List[SimRecord]) -> Dict[str, DupResult]:
    result: Dict[str, DupResult] = {}

    # Канал 1: хэш
    hash_map: Dict[str, List[SimRecord]] = defaultdict(list)
    for r in records:
        if r.content_hash:
            hash_map[r.content_hash].append(r)

    hash_groups = 0
    for ch, group in hash_map.items():
        if len(group) < 2:
            continue
        hash_groups += 1
        # Оригинал — с proposed_series (если есть), иначе первый
        group_s = sorted(group, key=lambda r: (0 if r.proposed_series else 1, r.file_path))
        src = group_s[0]
        for dup in group_s[1:]:
            key = dup.file_path
            if key not in result:
                result[key] = DupResult(dup_path=key, src_path=src.file_path, reason={'Хэш'})
            else:
                result[key].reason.add('Хэш')

    # Канал 2: метаданные (title + пересечение авторов)
    _PLACEHOLDER_TITLES = {'no title', 'без названия', 'untitled', 'unknown'}
    _RNG_SN = re.compile(r'^\d+\s*[-–—]\s*\d+')

    def _is_precomp(r: SimRecord) -> bool:
        return bool(_RNG_SN.match((r.series_number or '').strip()))

    title_map: Dict[str, List[SimRecord]] = defaultdict(list)
    for r in records:
        title = _norm_str(r.file_title)
        if not title or len(title) < 4 or title in _PLACEHOLDER_TITLES:
            continue
        title_map[title].append(r)

    meta_groups = 0
    for title, recs in title_map.items():
        if len(recs) < 2:
            continue
        recs_s = sorted(recs, key=lambda r: r.file_path)
        for i, ra in enumerate(recs_s):
            aa = _rec_authors(ra.proposed_author, ra.metadata_authors)
            if not aa:
                continue
            for rb in recs_s[i + 1:]:
                ab = _rec_authors(rb.proposed_author, rb.metadata_authors)
                if not ab or not (aa & ab):
                    continue
                # Предкомпиляция vs отдельная книга — не дубликаты
                if _is_precomp(ra) != _is_precomp(rb):
                    continue
                meta_groups += 1
                # Оригинал — у кого есть series и глубже путь
                score_a = (1 if ra.proposed_series else 0) + len(Path(ra.file_path).parts) * 0.1
                score_b = (1 if rb.proposed_series else 0) + len(Path(rb.file_path).parts) * 0.1
                if score_a >= score_b:
                    src_path, dup_path = ra.file_path, rb.file_path
                else:
                    src_path, dup_path = rb.file_path, ra.file_path
                if dup_path not in result:
                    result[dup_path] = DupResult(dup_path=dup_path, src_path=src_path, reason={'Метаданные'})
                else:
                    result[dup_path].reason.add('Метаданные')

    return result, hash_groups, meta_groups


# ── Симуляция компиляции ─────────────────────────────────────────────────────

@dataclass
class SimGroup:
    author: str
    series: str
    books: List[SimRecord]

    @property
    def volumes(self) -> List[int]:
        vs = []
        for b in self.books:
            sn = (b.series_number or '').strip()
            m = re.match(r'^(\d+)', sn)
            if m:
                vs.append(int(m.group(1)))
        return sorted(set(vs))

    @property
    def volume_range(self) -> str:
        vs = self.volumes
        if not vs:
            return '?'
        return f'{vs[0]}-{vs[-1]}' if vs[0] != vs[-1] else str(vs[0])

    @property
    def n_volumes(self) -> int:
        vs = self.volumes
        return len(vs) if vs else len(self.books)

    def suffix(self) -> str:
        n = self.n_volumes
        vs = self.volumes
        if not vs:
            return f'в {len(self.books)} книгах'
        lo, hi = vs[0], vs[-1]
        if n == 1:
            return f'в 1 книге'
        suffixes = {
            2: 'Дилогия', 3: 'Трилогия', 4: 'Тетралогия',
            5: 'Пенталогия', 6: 'Гексалогия', 7: 'Гепталогия',
            8: 'Окталогия', 9: 'Эннеалогия', 10: 'Декалогия',
        }
        if lo == 1 and hi == n and n in suffixes:
            return suffixes[n]
        rng = f'т. {lo}-{hi}' if lo != hi else f'т. {lo}'
        return f'{rng} в {n} книгах'


def simulate_compilation(records: List[SimRecord]) -> List[SimGroup]:
    # Группируем по (author, series)
    buckets: Dict[Tuple[str, str], List[SimRecord]] = defaultdict(list)
    for r in records:
        if not r.proposed_series:
            continue
        key = (r.proposed_author or '—', r.proposed_series)
        buckets[key].append(r)

    groups = []
    for (author, series), recs in sorted(buckets.items()):
        if len(recs) < 2:
            continue
        groups.append(SimGroup(author=author, series=series, books=recs))
    return groups


# ── Вывод результатов ─────────────────────────────────────────────────────────

def run(mode_dupes: bool, mode_compile: bool, out_path: Path):
    print(f'Загружаю CSV…', end=' ', flush=True)
    records = load_records()
    print(f'{len(records)} записей')

    print(f'Загружаю хэши из DB…', end=' ', flush=True)
    hashes = load_hashes()
    matched = attach_hashes(records, hashes)
    print(f'{matched}/{len(records)} совпало')

    lines = []

    if mode_dupes:
        print('Ищу дубликаты…', end=' ', flush=True)
        dupes, hash_g, meta_g = find_duplicates(records)
        print(f'найдено {len(dupes)} дубликатов')

        lines.append('=' * 80)
        lines.append(f'ДУБЛИКАТЫ  ({len(dupes)} файлов)')
        lines.append('=' * 80)

        # Сгруппируем по src_path для удобного чтения
        by_src: Dict[str, List[DupResult]] = defaultdict(list)
        for d in dupes.values():
            by_src[d.src_path].append(d)

        for src, dlist in sorted(by_src.items()):
            reasons_all = set().union(*(d.reason for d in dlist))
            lines.append(f'\n  ОРИГИНАЛ: {src}')
            lines.append(f'  Причина:  {", ".join(sorted(reasons_all))}')
            for d in sorted(dlist, key=lambda x: x.dup_path):
                lines.append(f'    ДУБ: {d.dup_path}  [{", ".join(sorted(d.reason))}]')

        lines.append(f'\nИтого: {len(dupes)} дубликатов '
                     f'(хэш-групп: {hash_g}, мета-групп: {meta_g})')

    if mode_compile:
        print('Симулирую компиляцию…', end=' ', flush=True)
        groups = simulate_compilation(records)
        print(f'{len(groups)} групп')

        lines.append('\n' + '=' * 80)
        lines.append(f'КОМПИЛЯЦИЯ  ({len(groups)} групп с ≥2 книгами)')
        lines.append('=' * 80)

        for g in groups:
            fname = f'{g.author} - {g.series} ({g.suffix()}).fb2'
            lines.append(f'\n  {fname}')
            lines.append(f'  Книг в группе: {len(g.books)}  |  Томов: {g.n_volumes}  |  Диапазон: {g.volume_range}')
            for b in sorted(g.books, key=lambda b: b.series_number or ''):
                sn = b.series_number or '?'
                lines.append(f'    [{sn:>4}] {b.file_title}  —  {Path(b.file_path).name}')

    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'\nРезультат → {out_path}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--dupes',   action='store_true', default=False)
    parser.add_argument('--compile', action='store_true', default=False)
    parser.add_argument('--out', default=str(SIM_DIR / 'results.txt'))
    args = parser.parse_args()

    if not args.dupes and not args.compile:
        args.dupes = args.compile = True

    run(args.dupes, args.compile, Path(args.out))
