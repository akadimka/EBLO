#!/usr/bin/env python3
"""
Regression tests for series/author extraction pipeline.

Usage:
    python simulation/test_regression.py [--db simulation/metadata_cache.db]

Each test case defines a path substring to locate a record in the output,
then checks proposed_series and series_source against expected values.
A test may specify expected_author / author_source as well.
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import csv
import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent
SIM_DIR  = Path(__file__).parent

# ---------------------------------------------------------------------------
# Test cases
# Each entry: (label, path_needle, checks_dict)
#   checks_dict keys: proposed_series, series_source, proposed_author, author_source
# ---------------------------------------------------------------------------
TEST_CASES = [
    # ── Дефисный автор (Евгеничев-Дмитрий) ─────────────────────────────────
    ("Дефисный автор: серия из папки",
     "Кассия, вернись",
     {"proposed_series": "Приключения девочки Кассии",
      "series_source":   "folder_dataset"}),

    ("Дефисный автор: другая книга той же серии",
     "Кассия, давай",
     {"proposed_series": "Приключения девочки Кассии",
      "series_source":   "folder_dataset"}),

    # ── Мир неправильных магов (СЕРИЯ.LitRPG, Дэорсе-Александр) ───────────
    ("Дефисный автор Дэорсе: книга 2",
     "Не так воспитан",
     {"proposed_series": "Мир неправильных магов",
      "series_source":   "folder_dataset"}),

    ("Дефисный автор Дэорсе: книга 3",
     "Говорят, мы бяки-буки",
     {"proposed_series": "Мир неправильных магов",
      "series_source":   "folder_dataset"}),

    ("Дефисный автор Дэорсе: книга 1",
     "Ну, вот! Опять сломал",
     {"proposed_series": "Мир неправильных магов",
      "series_source":   "folder_dataset"}),

    # ── РОС. Мангуст (filename + uppercase prefix) ──────────────────────────
    ("РОС: uppercase prefix сохранён",
     "РОС. Эра Мангуста 1-9",
     {"proposed_series": "РОС. Мангуст",
      "series_source":   "filename+meta_expanded"}),

    # ── РОС. Хищный клан (filename Rule 1) ─────────────────────────────────
    ("РОС: Хищный клан из filename",
     "Хищный клан 1-5",
     {"proposed_series": "РОС. Хищный клан",
      "series_source":   "filename+meta_expanded"}),

    # ── (Не) Приличный путь героя — скобка в начале папки ──────────────────
    ("Скобка в начале папки — сохранить как есть",
     "Приличный путь героя",
     {"proposed_series": "(Не) Приличный путь героя",
      "series_source":   "folder_dataset"}),

    # ── Проект Э.К.С.П.А.Н.С.И.Я — subfolder hierarchy ────────────────────
    ("Subfolder hierarchy: двухуровневая серия",
     "Проект Э.К.С.П.А.Н.С.И.Я",
     {"proposed_series": "Проект Э.К.С.П.А.Н.С.И.Я\\Путь князя",
      "series_source":   "folder_dataset+subfolder_hierarchy"}),
]


def run_pipeline(db_path: Path, filter_path: str, out_path: Path) -> bool:
    result = subprocess.run(
        [sys.executable, str(SIM_DIR / "gen_csv_offline.py"),
         "--db", str(db_path),
         "--out", str(out_path),
         "--filter-path", filter_path],
        capture_output=True, text=True, encoding="utf-8",
        cwd=str(ROOT_DIR)
    )
    return result.returncode == 0


def load_csv(path: Path) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(SIM_DIR / "metadata_cache.db"))
    parser.add_argument("--fast", action="store_true",
                        help="Reuse existing regen.csv instead of running pipeline per test")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"ERROR: DB not found: {db_path}", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0
    errors = 0

    if args.fast:
        # Load full regen.csv once
        regen_csv = SIM_DIR / "regen.csv"
        if not regen_csv.exists():
            print("ERROR: simulation/regen.csv not found, run without --fast first", file=sys.stderr)
            sys.exit(1)
        all_rows = load_csv(regen_csv)

    print(f"\n{'='*70}")
    print(f"  REGRESSION TEST  ({len(TEST_CASES)} cases)")
    print(f"{'='*70}\n")

    for label, needle, checks in TEST_CASES:
        try:
            if args.fast:
                rows = [r for r in all_rows if needle in r["file_path"]]
            else:
                with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
                    tmp_path = Path(tf.name)
                ok = run_pipeline(db_path, needle, tmp_path)
                if not ok or not tmp_path.exists():
                    print(f"  PIPELINE_ERROR  {label}")
                    errors += 1
                    continue
                rows = load_csv(tmp_path)
                tmp_path.unlink(missing_ok=True)

            if not rows:
                print(f"  NO_MATCH  {label!r}  (needle={needle!r})")
                errors += 1
                continue

            # Find the first matching record
            match_rows = [r for r in rows if needle in r["file_path"]]
            if not match_rows:
                print(f"  NO_MATCH  {label}")
                errors += 1
                continue

            r = match_rows[0]
            mismatches = []
            for key, expected in checks.items():
                actual = r.get(key, "")
                if actual != expected:
                    mismatches.append(f"    {key}:\n      expected: {expected!r}\n      actual:   {actual!r}")

            if mismatches:
                print(f"  FAIL  {label}")
                for m in mismatches:
                    print(m)
                failed += 1
            else:
                print(f"  PASS  {label}")
                passed += 1

        except Exception as e:
            print(f"  ERROR  {label}: {e}")
            errors += 1

    print(f"\n{'='*70}")
    print(f"  Results: {passed} passed, {failed} failed, {errors} errors")
    print(f"{'='*70}\n")

    sys.exit(0 if (failed == 0 and errors == 0) else 1)


if __name__ == "__main__":
    main()
