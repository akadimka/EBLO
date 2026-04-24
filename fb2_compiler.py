"""
FB2 Compilation Service

Объединяет несколько FB2-файлов одного автора и одной серии в один файл.
Работает исключительно с данными из BookRecord (результат pipeline generate_csv).

Порядок сортировки книг (многоуровневый):
  1. series_number — явный номер тома (целое число)
  2. Число в начале имени файла: "1. Название", "02 Название"
  3. date в <title-info> FB2 (год написания)
  4. date в <publish-info> FB2 (год издания)
  → Если порядок не определён → группа помечается как неопределённая

Выходной файл: UTF-8, структура:
  <description> с метаданными из первого файла группы (автор, жанр)
  <sequence name="Серия" number="1-7"/>
  Один <body> на каждую книгу с <title><p>N. Название</p></title>
"""

import re
import html as _html
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def _norm_key(s: str) -> str:
    """Нормализовать строку для сравнения: NFC + lower + ё→е.

    NFC нужна потому что ё может быть в NFD-форме (е + U+0308),
    при которой обычный replace('ё','е') не работает.
    """
    return unicodedata.normalize('NFC', s).lower().replace('ё', 'е')
from typing import List, Tuple, Optional, Dict

try:
    from passes.pass1_read_files import BookRecord
except ImportError:
    try:
        from .passes.pass1_read_files import BookRecord
    except ImportError:
        BookRecord = None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CompilationBook:
    """Одна книга внутри группы компиляции."""
    record: object          # BookRecord
    abs_path: Path          # Абсолютный путь к файлу
    sort_key: Tuple         # (sort_level 0-3, value) — для сортировки
    sort_source: str        # "series_number" | "filename" | "title_date" | "publish_date"
    order_ambiguous: bool   # True если порядок не определён
    volume_label: str = ''  # Отображаемый номер тома: "1", "1-3", "Свиток 1" и т.п.


@dataclass
class CompilationGroup:
    """Группа файлов для компиляции."""
    author: str
    series: str
    books: List[CompilationBook]
    order_determined: bool  # False если хотя бы у одной книги ambiguous
    volume_range: str       # "1-7" или ""
    duplicate_paths: List[Path] = None  # Файлы-дубликаты для автоматического удаления
    kept_paths: List[Path] = None       # Файлы, которые остаются (для cleanup_only групп)
    alphabetical_order: bool = False    # True — порядок не определён, отсортировано по названию
    cleanup_only: bool = False          # True — новая компиляция не нужна, только удалить дубликаты
    part_count: int = 0                 # > 0 если книги имеют паттерн N.M (том.часть): общее число частей

    def __post_init__(self):
        if self.duplicate_paths is None:
            self.duplicate_paths = []
        if self.kept_paths is None:
            self.kept_paths = []


@dataclass
class CompilationResult:
    """Результат компиляции одной группы."""
    group: CompilationGroup
    output_path: Path
    books_compiled: int
    source_paths: List[Path]
    success: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class FB2CompilerService:
    """Сервис компиляции: анализирует записи и создаёт объединённые FB2."""

    # Regex для извлечения числа из начала stem:
    # "1. Название", "02 - Название", "3 Название", "1 Возмездие неизбежно"
    # Последний вариант: цифра + пробел + заглавная буква (без спецсимвола)
    _STEM_NUM_RE = re.compile(
        r'^(\d{1,4})\s*[.\-–—_)]\s*'           # "1. " / "02 - " / "3_"
        r'|^(\d{1,4})\s+(?=[А-ЯЁA-Z\(])'       # "1 Название" (пробел + заглавная)
        r'|\s+(\d{1,4})\s*[.\-–—_)]\s'          # внутри: " 3. "
        r'|\s+(\d{1,4})$',                       # в конце: "Серия 1"
        re.UNICODE
    )

    # Сервисные слова для N томов (2..N)
    _SERIES_WORDS = [
        None,          # 0 — не используется
        None,          # 1 — одиночная книга
        'Дилогия',    # 2
        'Трилогия',   # 3
        'Тетралогия', # 4
        'Пенталогия', # 5
        'Гексалогия', # 6
        'Гепталогия', # 7
        'Окталогия', # 8
        'Ноналогия', # 9
        'Декалогия', # 10
    ]

    # Regex для очистки сервисных слов/диапазонов из имени серии
    _SERIES_CLEAN_RE = re.compile(
        r'\s*\([^)]*\)\s*$'               # trailing (…)
        r'|\s*[тт]\.\s+\d+[-–]\d+\s*$'   # trailing т. 1-4
        r'|\s*\d+[-–]\d+\s*$',             # trailing 1-4
        re.IGNORECASE | re.UNICODE,
    )

    @classmethod
    def _clean_series_name(cls, series: str) -> str:
        """Убрать сервисные слова и диапазоны из имени серии.

        «Солдат удачи (Тетралогия)»       → «Солдат удачи»
        «Солдат удачи. Тетралогия 1-4»   → «Солдат удачи. Тетралогия» (точечные
        субсерии не трогаем — они часть иерархии).
        """
        cleaned = cls._SERIES_CLEAN_RE.sub('', series).strip()
        # Убрать хвостовое сервисное слово после последней точки, если оно совпадает
        for kw in cls._SERIES_WORDS[2:]:
            if kw and cleaned.rstrip().lower().endswith('.' + kw.lower()):
                cleaned = cleaned[:-(len(kw) + 1)].strip()
                break
            if kw and re.search(
                rf'[.(\s]{re.escape(kw)}$', cleaned, re.IGNORECASE
            ):
                cleaned = re.sub(
                    rf'[.\s]*{re.escape(kw)}\s*$', '', cleaned,
                    flags=re.IGNORECASE
                ).strip()
                break
        return cleaned or series

    @classmethod
    def _series_suffix(cls, book_count: int, volume_range: str, part_count: int = 0) -> str:
        """Вернуть суффикс для имени файла компиляции.

        Служебное слово (Дилогия, Трилогия…) присваивается ТОЛЬКО если:
          1. Диапазон начинается с тома 1 (нумерация с начала серии).
          2. Количество томов ≤ 10 (есть подходящее слово).
        Во всех остальных случаях: «т. X-Y».
        Пустой volume_range → «компиляция романов».

        part_count > 0 → добавляем «из N частей» к служебному слову.
        Пример: Дилогия из 6 частей.

        n вычисляется из диапазона (volume_range), а не из числа файлов, чтобы
        предкомпиляция-диапазон (файл «1-4» + том 5 = 5 томов) считалась верно.
        """
        if not volume_range:
            return 'компиляция романов'
        rng = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', volume_range.strip())
        if rng:
            lo = int(rng.group(1))
            n  = int(rng.group(2)) - lo + 1
        else:
            lo = 1   # одиночный том вида "5" — не начинается с 1
            try:
                lo = int(volume_range.strip())
            except ValueError:
                pass
            n = book_count
        # Служебное слово только если нумерация с тома 1
        if lo == 1 and 2 <= n < len(cls._SERIES_WORDS) and cls._SERIES_WORDS[n]:
            word = cls._SERIES_WORDS[n]
            if part_count > 0:
                return f'{word} из {part_count} частей'
            return word
        return f'т. {volume_range}'

    def __init__(self, logger=None):
        self.logger = logger

    def _log(self, msg: str):
        if self.logger:
            self.logger.log(msg)

    # ------------------------------------------------------------------
    # Группировка записей
    # ------------------------------------------------------------------

    def find_groups(
        self,
        records: List,
        work_dir: Path,
    ) -> List[CompilationGroup]:
        """Найти все группы (автор + серия) с ≥2 файлами.

        Args:
            records: Список BookRecord из pipeline.
            work_dir: Корневая папка (для построения абсолютных путей).

        Returns:
            Список CompilationGroup, отсортированный по (author, series).
        """
        # Пересоздаём debug-файлы при каждом запуске (не дозаписываем)
        import tempfile, os as _os
        _base = Path(__file__).parent
        for _dbg_name in ('fb2_sort_debug.txt', 'fb2_inline_debug.txt'):
            _dbg_path = _base / _dbg_name
            try:
                _tmp_fd, _tmp_path = tempfile.mkstemp(dir=_base, prefix=_dbg_name + '.tmp')
                _os.close(_tmp_fd)
                _os.replace(_tmp_path, _dbg_path)
            except Exception:
                try:
                    _dbg_path.write_text('', encoding='utf-8')
                except Exception:
                    pass

        # Группировка по (author_lower, series_lower)
        # Нормализуем ё→е в ключах, чтобы "Тёмные звёзды" и "Темные звезды" попали в одну группу.
        # Для подсерий ("Серия N\Подсерия") ключ группировки — корневое название без номера,
        # чтобы файлы "Серия 04\Роман" и "Серия" попали в одну компиляцию.
        def _series_group_key(series: str) -> str:
            if '\\' not in series:
                return _norm_key(series)
            root = series.split('\\')[0].strip()
            root_no_num = re.sub(r'\s+\d{1,4}\s*$', '', root).strip()
            return _norm_key(root_no_num) if root_no_num else _norm_key(series)

        buckets: Dict[Tuple[str, str], List] = {}
        for rec in records:
            author = (rec.proposed_author or '').strip()
            series = (rec.proposed_series or '').strip()
            if not author or not series:
                continue
            key = (_norm_key(author), _series_group_key(series))
            buckets.setdefault(key, []).append(rec)

        groups: List[CompilationGroup] = []
        for (_, _), recs in buckets.items():
            if len(recs) < 2:
                continue
            # Используем реальное написание из первой записи без подсерии и номера
            author = recs[0].proposed_author.strip()
            _s0 = recs[0].proposed_series.strip()
            if '\\' in _s0:
                _root = _s0.split('\\')[0].strip()
                series = re.sub(r'\s+\d{1,4}\s*$', '', _root).strip() or _root
            else:
                series = _s0
            # Если в группе есть файлы без подсерии — их название точнее
            _plain = next((r.proposed_series.strip() for r in recs if '\\' not in r.proposed_series), None)
            if _plain:
                series = _plain

            books = [self._make_book(rec, work_dir) for rec in recs]

            duplicate_paths: List[Path] = []

            # Debug: вывести классификацию файлов для конкретной пары автор/серия
            _debug = getattr(self, '_debug_filter', None)
            import sys as _sys
            _dbg_out = _sys.__stdout__  # bypass any stdout redirect
            if _debug and any(kw in author.lower() or kw in series.lower() for kw in _debug):
                print(f"\n[DEBUG] {author} / {series} ({len(books)} файлов):", file=_dbg_out)
                for b in books:
                    lo, hi = self._precompiled_range(b, series)
                    print(f"  {'PRE' if hi>lo else 'REG'} sk={b.sort_key} vl={b.volume_label!r} "
                          f"pre=({lo},{hi}) | {b.abs_path.name}", file=_dbg_out)

            # --- Фильтр 1: обработка заранее скомпилированных файлов ----------
            # Признак: stem/title содержит сервисное слово (Трилогия …) или
            # series_number — диапазон вида "1-3".
            #
            # Три состояния:
            #   1. АКТУАЛЬНА (best_count >= regular_count): компиляция уже
            #      сделана — сохраняем предкомпиляцию, отдельные тома на удаление.
            #   2. ЧАСТИЧНО УСТАРЕЛА (best_count < regular_count, но предкомпиляция
            #      содержит тома которых нет отдельно, например том 1): включаем
            #      предкомпиляцию как источник + добавляем недостающие тома.
            #      Тома, уже покрытые предкомпиляцией, помечаем на удаление.
            #   3. ПОЛНОСТЬЮ УСТАРЕЛА (все тома предкомпиляции есть и по отдельности):
            #      удаляем предкомпиляцию, компилируем из отдельных томов.
            precompiled: List[Tuple[CompilationBook, int, int]] = []  # (book, lo, hi)
            regular_books: List[CompilationBook] = []
            _is_target_series = '\u0422\u044b\u0441\u044f\u0447\u0430' in series  # "Тысяча"
            for book in books:
                lo, hi = self._precompiled_range(book, series)
                if _is_target_series:
                    try:
                        with open(Path(__file__).parent / 'fb2_sort_debug.txt', 'a', encoding='utf-8') as _dbg2:
                            _dbg2.write(f"  PRE_RANGE sk={book.sort_key} vl={book.volume_label!r} pre=({lo},{hi}) | {book.abs_path.name}\n")
                    except Exception:
                        pass
                if hi > lo:
                    # Обновляем sort_key и volume_label по реальному диапазону файла.
                    # Без этого "1-2. Название.fb2" получает sk=(0,2,0) vl='2' вместо
                    # sk=(0,1,0) vl='1-2', и _split_into_consecutive_runs считает
                    # что "1-2" и "3-4" не идут подряд (lo=4 ≠ hi=2+1).
                    book.sort_key = (0, lo, 0)
                    book.volume_label = f'{lo}-{hi}'
                    book.sort_source = 'filename_range'
                    book.order_ambiguous = False
                    precompiled.append((book, lo, hi))
                else:
                    regular_books.append(book)

            if precompiled:
                regular_count = len(regular_books)
                # Берём предкомпиляцию с максимальным охватом
                best_pre, best_lo, best_hi = max(precompiled, key=lambda t: t[2] - t[1])
                best_count = best_hi - best_lo + 1
                # Прочие предкомпиляции — на удаление ТОЛЬКО если их диапазон полностью
                # покрыт хотя бы одной другой предкомпиляцией (best или иной).
                # Пример: [1-42]+[31-43]+[31-45] → [31-43] покрыт [31-45] → дубликат;
                #          [31-45] не покрыт [1-42] (45>42) → источник (содержит тома 43-45).
                other_precompiled: List[Tuple] = []
                for entry in precompiled:
                    book, lo, hi = entry
                    if book is best_pre:
                        continue
                    # Дубликат только если диапазон ПОЛНОСТЬЮ покрыт любой другой предкомпиляцией.
                    # Пример: best=[1-42], other=[31-43] → [31-43] не покрыт [1-42] (43>42).
                    #          Но если есть ещё [31-45], то [31-43] покрыт [31-45] → дубликат.
                    # Это корректнее чем проверять только против best_pre:
                    # [1-42]+[31-43]+[31-45] → [31-43] дублируется [31-45], [31-45] уникален.
                    covered_by_any = any(
                        (o_lo <= lo and hi <= o_hi)
                        for (o_book, o_lo, o_hi) in precompiled
                        if o_book is not book
                    )
                    if covered_by_any:
                        duplicate_paths.append(book.abs_path)
                    else:
                        # Не полностью покрыт ни одной другой предкомпиляцией → источник
                        other_precompiled.append(entry)

                # АКТУАЛЬНА только если ВСЕ обычные тома входят в диапазон предкомпиляции
                # И нет других непокрытых предкомпиляций (other_precompiled пуст).
                # Пример: предкомпиляция 1-3 + обычный том 4 → НЕ актуальна (том 4 не покрыт).
                # Пример: предкомпиляция 1-2 + предкомпиляция 3-4 → НЕ актуальна (нужно объединить).
                def _vol_num_for_check(b: 'CompilationBook') -> Optional[int]:
                    if b.sort_key and b.sort_key[0] == 0:
                        return b.sort_key[1]
                    return None

                all_covered = (
                    not other_precompiled and
                    (all(
                        (n := _vol_num_for_check(r)) is not None and best_lo <= n <= best_hi
                        for r in regular_books
                    ) if regular_books else True)
                )

                if all_covered:
                    # 1. АКТУАЛЬНА — компиляция уже сделана, новая не нужна.
                    # Отдельные тома, уже покрытые компиляцией, — на удаление.
                    for book in regular_books:
                        duplicate_paths.append(book.abs_path)
                    if duplicate_paths:
                        # Есть что удалить — сообщаем через cleanup_only группу
                        groups.append(CompilationGroup(
                            author=author,
                            series=series,
                            books=[],
                            order_determined=True,
                            volume_range=f'{best_lo}-{best_hi}' if best_lo != best_hi else str(best_lo),
                            duplicate_paths=duplicate_paths,
                            kept_paths=[best_pre.abs_path],
                            cleanup_only=True,
                        ))
                    continue
                else:
                    # Определяем, какие тома предкомпиляции присутствуют отдельно
                    def _vol_num(b: CompilationBook) -> Optional[int]:
                        """Номер тома из sort_key[1] если источник надёжен."""
                        if b.sort_key and b.sort_key[0] == 0:
                            return b.sort_key[1]
                        return None

                    # Если regular_books пуст — нечем покрывать тома по отдельности.
                    # all(...) при пустом range даёт vacuous True — это неверно:
                    # «0 книг покрывают 4 тома» не означает «покрыты».
                    pre_covered_individually = bool(regular_books) and all(
                        any(_vol_num(r) == v for r in regular_books)
                        for v in range(best_lo, best_hi + 1)
                    )

                    if pre_covered_individually:
                        # 3. ПОЛНОСТЬЮ УСТАРЕЛА — все её тома есть по отдельности
                        duplicate_paths.append(best_pre.abs_path)
                        books = regular_books
                    else:
                        # 2. ЧАСТИЧНО УСТАРЕЛА
                        covered_individually = [
                            r for r in regular_books
                            if (n := _vol_num(r)) is not None and best_lo <= n <= best_hi
                        ]
                        remaining = [r for r in regular_books if r not in covered_individually]

                        # Проверяем: продолжают ли оставшиеся книги диапазон предкомпиляции?
                        # Пример: предкомп [1-4] + книги [5,6,7] → консекутивны (5 = 4+1)
                        #          → компилируем вместе → один файл 1-7
                        # Пример: предкомп [1-3] + книга [7] → НЕ консекутивны
                        #          → cleanup_only (удаляем покрытые) + книга [7] standalone
                        remaining_known_positions = [
                            n for r in remaining if (n := _vol_num(r)) is not None
                        ]
                        remaining_has_unknown = any(_vol_num(r) is None for r in remaining)
                        remaining_extends_pre = (
                            remaining_known_positions and
                            min(remaining_known_positions) == best_hi + 1
                        )

                        if covered_individually and not remaining_extends_pre and not remaining_has_unknown:
                            # Оставшиеся книги не продолжают предкомпиляцию и нет книг
                            # с неизвестной позицией → cleanup_only: предкомп остаётся,
                            # покрытые тома — на удаление; оставшиеся обрабатываются отдельно.
                            cov_dup_paths = list(duplicate_paths) + [r.abs_path for r in covered_individually]
                            groups.append(CompilationGroup(
                                author=author, series=series, books=[],
                                order_determined=True,
                                volume_range=(
                                    f'{best_lo}-{best_hi}' if best_lo != best_hi else str(best_lo)
                                ),
                                duplicate_paths=cov_dup_paths,
                                kept_paths=[best_pre.abs_path],
                                cleanup_only=True,
                            ))
                            duplicate_paths = []
                            books = remaining
                        else:
                            # Оставшиеся книги продолжают серию (или есть книги без номера)
                            # → включаем предкомпиляцию как источник, компилируем вместе.
                            for r in covered_individually:
                                duplicate_paths.append(r.abs_path)
                            books = [best_pre] + remaining

                    # Добавляем прочие предкомпиляции с непересекающимися диапазонами
                    # как дополнительные источники (они уже НЕ в duplicate_paths).
                    for other_book, other_lo, other_hi in other_precompiled:
                        # Проверяем: все тома этой предкомпиляции уже есть отдельно?
                        other_fully_individual = bool(regular_books) and all(
                            any(_vol_num(r) == v for r in regular_books)
                            for v in range(other_lo, other_hi + 1)
                        )
                        if other_fully_individual:
                            duplicate_paths.append(other_book.abs_path)
                        else:
                            books.append(other_book)
            else:
                books = regular_books

            # --- Фильтр 2: дедупликация по title (нормализованному) ----------
            # Из дублей оставляем первый по алфавиту путь (детерминированный выбор)
            seen_titles: Dict[str, CompilationBook] = {}
            for book in sorted(books, key=lambda b: str(b.abs_path)):
                # Если file_title совпадает с именем серии — он не несёт информации
                # о конкретном томе, используем stem файла как более информативный.
                raw_title = book.record.file_title or book.abs_path.stem
                if _norm_key(raw_title) == _norm_key(series):
                    raw_title = book.abs_path.stem
                title_key = self._normalize_title_key(raw_title, series)
                # Для книг с известной позицией тома (level-0) добавляем позицию к ключу,
                # чтобы не дедуплицировать разные тома с одинаковым названием.
                # Пример: «Маршал 1-5» и «Маршал 6-9» оба имеют file_title="Маршал" —
                # без этой защиты они бы считались дублями.
                if book.sort_key[0] == 0:
                    title_key = f"{title_key}\x00{book.sort_key[1]}"
                if title_key not in seen_titles:
                    seen_titles[title_key] = book
                else:
                    duplicate_paths.append(book.abs_path)
            books = list(seen_titles.values())

            # --- Фильтр 3: дедупликация по позиции тома ----------------------
            # Если после title-дедупликации остались книги с одинаковым sort_key
            # на уровнях 0 (series_number) или 1 (filename number), оставляем
            # первую по алфавиту, остальные помечаем как дубликаты.
            books = self._dedup_by_position(books, duplicate_paths)

            if _is_target_series:
                try:
                    with open(Path(__file__).parent / 'fb2_sort_debug.txt', 'a', encoding='utf-8') as _dbg3:
                        _dbg3.write(f"  AFTER_DEDUP books={[(b.sort_key,b.volume_label) for b in books]} dups={len(duplicate_paths)}\n")
                except Exception:
                    pass

            if len(books) < 2:
                # Если после dedup остался один файл, но есть дубликаты — создаём cleanup_only.
                # Пример: два файла с одинаковым sort_key (01. vs 1.) — dedup оставляет один,
                # другой попадает в duplicate_paths, но без группы они не удаляются.
                if duplicate_paths and books:
                    groups.append(CompilationGroup(
                        author=author,
                        series=series,
                        books=[],
                        order_determined=True,
                        volume_range='',
                        duplicate_paths=duplicate_paths,
                        kept_paths=[books[0].abs_path],
                        cleanup_only=True,
                    ))
                continue
            if _debug and any(kw in author.lower() or kw in series.lower() for kw in _debug):
                print(f"  → to_compile: {[b.abs_path.name for b in books]}", file=_dbg_out)
                print(f"  → to_delete:  {[p.name for p in duplicate_paths]}", file=_dbg_out)

            books_sorted, order_determined, alphabetical_order = self._sort_books(books)

            if alphabetical_order:
                # Порядок по названию — нет номеров томов, пропуски неприменимы
                volume_range = ''
                groups.append(CompilationGroup(
                    author=author,
                    series=series,
                    books=books_sorted,
                    order_determined=order_determined,
                    volume_range=volume_range,
                    duplicate_paths=duplicate_paths,
                    alphabetical_order=True,
                ))
            else:
                # Разбиваем числовые и нечисловые книги независимо:
                #   • числовые (level-0) → непрерывные подгруппы, пропуски не допускаются
                #   • нечисловые (даты / unknown) → отдельная группа «компиляция романов»
                # Это предотвращает ложное смешение диапазона (например, sn=1 + sn=3 + дата
                # дало бы volume_range='1-3' → «Трилогия», хотя тома 1 и 3 не идут подряд).
                numeric = [b for b in books_sorted if b.sort_key[0] == 0]
                others  = [b for b in books_sorted if b.sort_key[0] != 0]

                # Эвристика «неопределённый = том 1»:
                # Если ровно один файл без номера тома (год/неизвестен),
                # а среди числовых нет тома 1 — считаем его первым томом.
                if (len(others) == 1
                        and numeric
                        and min(b.sort_key[1] for b in numeric if b.sort_key[0] == 0) >= 2):
                    lone = others[0]
                    lone.sort_key = (0, 1, 0)
                    lone.sort_source = 'assumed_first'
                    lone.order_ambiguous = False
                    lone.volume_label = '1'
                    numeric = sorted(numeric + [lone], key=lambda b: b.sort_key)
                    others = []

                first_group = True  # для назначения duplicate_paths только один раз

                # ── Числовые книги: непрерывные блоки ──────────────────────
                valid_runs = [r for r in self._split_into_consecutive_runs(numeric) if len(r) >= 2]
                lone_numeric = [b for r in self._split_into_consecutive_runs(numeric) if len(r) < 2 for b in r]

                for run in valid_runs:
                    # Детектируем паттерн N.M (том.часть): если ВСЕ книги в run
                    # получили sort_source='dot_part', то volume_range = диапазон томов,
                    # а part_count = общее число частей (файлов).
                    all_dot_part = run and all(b.sort_source == 'dot_part' for b in run)
                    if all_dot_part:
                        toms = sorted({b.sort_key[1] for b in run})
                        run_range = f'{toms[0]}-{toms[-1]}' if len(toms) > 1 else str(toms[0])
                        run_part_count = len(run)
                    else:
                        run_range = self._compute_volume_range(run)
                        run_part_count = 0
                    groups.append(CompilationGroup(
                        author=author,
                        series=series,
                        books=run,
                        order_determined=True,
                        volume_range=run_range,
                        duplicate_paths=duplicate_paths if first_group else [],
                        alphabetical_order=False,
                        part_count=run_part_count,
                    ))
                    first_group = False

                # ── Нечисловые книги: компиляция по году / по названию ─────
                # Если нечисловых >= 2 — обычная группа
                # Если нечисловых < 2, но есть одиночные числовые книги — объединяем всё вместе.
                # ИСКЛЮЧЕНИЕ: precompiled книги (volume_label содержит диапазон "N-M") не
                # объединяем с нечисловыми — они уже содержат несколько томов и не являются
                # "одиночными" книгами в смысле серии.
                _RANGE_VL = re.compile(r'^\d+\s*[-–—]\s*\d+$')
                lone_regular = [b for b in lone_numeric if not _RANGE_VL.match(b.volume_label or '')]
                all_others = others
                if len(others) < 2 and lone_regular:
                    # Объединяем одиночные обычные (не precompiled) + нечисловые,
                    # НО только если lone_regular ровно один — иначе это несколько томов
                    # с явными номерами и пробелом между ними (например, тома 7 и 9 без 8):
                    # такие группы не компилируем.
                    if len(lone_regular) == 1:
                        all_others = sorted(lone_regular, key=lambda b: b.sort_key) + list(others)
                        lone_numeric = [b for b in lone_numeric if b not in lone_regular]

                if len(all_others) >= 2:
                    all_oth_ambig = all(b.order_ambiguous for b in all_others)
                    if all_oth_ambig:
                        oth_sorted = sorted(
                            all_others,
                            key=lambda b: (b.record.file_title or b.abs_path.stem).lower(),
                        )
                    else:
                        oth_sorted = sorted(all_others, key=lambda b: b.sort_key)
                    groups.append(CompilationGroup(
                        author=author,
                        series=series,
                        books=oth_sorted,
                        order_determined=not any(b.order_ambiguous for b in all_others),
                        volume_range='',
                        duplicate_paths=duplicate_paths if first_group else [],
                        alphabetical_order=all_oth_ambig,
                    ))
                    first_group = False

        groups.sort(key=lambda g: (g.author.lower(), g.series.lower()))
        self._log(f"Найдено групп для компиляции: {len(groups)}")
        return groups

    def _make_book(self, rec, work_dir: Path) -> CompilationBook:
        """Создать CompilationBook из BookRecord."""
        abs_path = work_dir / rec.file_path
        sort_key, sort_source, ambiguous, volume_label = self._determine_sort_key(rec, abs_path)
        return CompilationBook(
            record=rec,
            abs_path=abs_path,
            sort_key=sort_key,
            sort_source=sort_source,
            order_ambiguous=ambiguous,
            volume_label=volume_label,
        )

    # ------------------------------------------------------------------
    # Вспомогательные методы фильтрации
    # ------------------------------------------------------------------

    # Regex для диапазонного series_number вида "1-3", "1–7"
    _RANGE_NUM_RE = re.compile(r'^\d+\s*[-–—]\s*\d+$')

    # Ключевые слова, указывающие на номер тома внутри названия
    # Порядок важен: более специфичные — первыми
    _VOLUME_KEYWORDS_RE = re.compile(
        r'(?:свиток|том|книга|часть|выпуск|арка|цикл|эпизод|volume|book|part|vol\.?)'
        r'\s*[.:-]?\s*(\d{1,4})\b',
        re.IGNORECASE | re.UNICODE,
    )

    # Римские цифры после ключевых слов тома: «Том I», «Том II», «Vol. IV» и т.п.
    _VOLUME_ROMAN_RE = re.compile(
        r'(?:свиток|том|книга|часть|выпуск|арка|цикл|эпизод|volume|book|part|vol\.?)'
        r'\s*[.:-]?\s*(M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))\b',
        re.IGNORECASE | re.UNICODE,
    )

    # Паттерн N.M в начале stem или после разделителя — том.часть (например «1.2_Название»)
    _DOT_PART_RE = re.compile(
        r'(?:^|[\s_\-])([1-9]\d{0,1})\.([1-9]\d{0,1})(?:[\s_\-.]|$)',
        re.UNICODE,
    )

    # Паттерн «Том N. Часть M» / «Vol N. Part M» — два файла одного тома.
    # Группы: (1) номер тома (арабский или римский), (2) номер части (арабский).
    _VOLUME_PART_RE = re.compile(
        r'(?:том|volume|vol\.?)\s*[.:-]?\s*'
        r'(M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})|\d{1,4})'
        r'\s*[.,;]?\s*'
        r'(?:часть|part|ч\.?)\s*[.:-]?\s*(\d{1,4})\b',
        re.IGNORECASE | re.UNICODE,
    )

    @staticmethod
    def _roman_to_int(s: str) -> Optional[int]:
        """Конвертировать римскую цифру в целое. Возвращает None если s пустая или невалидна."""
        s = s.upper().strip()
        if not s:
            return None
        vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        result = 0
        prev = 0
        for ch in reversed(s):
            if ch not in vals:
                return None
            v = vals[ch]
            result += v if v >= prev else -v
            prev = v
        return result if result > 0 else None

    @classmethod
    def _extract_volume_part(cls, title: str, stem: str) -> Optional[Tuple[int, int]]:
        """Извлечь (том, часть) из паттерна «Том N. Часть M» / «Vol N. Part M».

        Возвращает (volume, part) или None если паттерн не найден.
        volume — целое число тома, part — номер части (1, 2, …).
        """
        for text in (title, stem):
            if not text:
                continue
            text_norm = unicodedata.normalize('NFKC', text)
            m = cls._VOLUME_PART_RE.search(text_norm)
            if m:
                vol_str, part_str = m.group(1), m.group(2)
                # vol_str может быть арабским или римским числом
                if vol_str.isdigit():
                    vol = int(vol_str)
                else:
                    vol = cls._roman_to_int(vol_str)
                if vol and 1 <= vol <= 100:
                    part = int(part_str)
                    if 1 <= part <= 20:
                        return vol, part
        return None

    @classmethod
    def _extract_dot_part(cls, stem: str, title: str) -> Optional[Tuple[int, int]]:
        """Извлечь (том, часть) из паттерна N.M в stem или title.

        Распознаёт: «1.2_Название», «Расходники 2.3», «2.1 Название» и т.п.
        Возвращает (том, часть) или None.
        Ограничения: N и M от 1 до 19 (исключаем годы и ISBN).
        """
        for text in (stem, title):
            if not text:
                continue
            m = cls._DOT_PART_RE.search(text)
            if m:
                vol, part = int(m.group(1)), int(m.group(2))
                if 1 <= vol <= 19 and 1 <= part <= 19:
                    return vol, part
        return None

    @classmethod
    def _extract_inline_volume_number(cls, title: str, stem: str) -> Optional[int]:
        """Извлечь номер тома из ключевых слов внутри названия.

        Ищет паттерны «Свиток 1», «Том 3», «Книга 2», «Часть 4» и т.п.,
        а также римские цифры: «Том I», «Том II», «Vol. IV».
        Возвращает число или None, если паттерн не найден.

        Проверяет как file_title, так и stem файла.
        """
        for text in (title, stem):
            if not text:
                continue
            # Нормализовать Unicode-символы римских цифр в ASCII: Ⅻ → XII, Ⅰ → I и т.п.
            text_norm = unicodedata.normalize('NFKC', text)
            # TEMP DEBUG
            try:
                with open(Path(__file__).parent / 'fb2_inline_debug.txt', 'a', encoding='utf-8') as _d:
                    _d.write(f"INLINE text={text!r} norm={text_norm!r}\n")
                    m0 = cls._VOLUME_KEYWORDS_RE.search(text_norm)
                    m1 = cls._VOLUME_ROMAN_RE.search(text_norm)
                    _d.write(f"  kw_match={m0} roman_match={m1} roman_group={m1.group(1) if m1 else None}\n")
            except Exception:
                pass
            m = cls._VOLUME_KEYWORDS_RE.search(text_norm)
            if m:
                return int(m.group(1))
            m = cls._VOLUME_ROMAN_RE.search(text_norm)
            if m:
                n = cls._roman_to_int(m.group(1))
                if n:
                    return n
        return None

    def _precompiled_range(self, book: CompilationBook, series: str) -> Tuple[int, int]:
        """Определить диапазон томов, охватываемых предкомпилированным файлом.

        Возвращает (lo, hi) где lo и hi — первый и последний тома включительно.
        Если файл не является предкомпиляцией, возвращает (0, 0).

        Критерии определения предкомпиляции:
        1. series_number — диапазон вида "1-3": возвращает (1, 3).
        2. Диапазон "N-M" в stem/title с привязкой к серии.
        3. stem/title содержит сервисное слово (Трилогия → 3 тома) — lo=1, hi=count.
        """
        series_lower = series.lower()
        series_words = [w for w in series_lower.split() if len(w) >= 4]
        is_subseries = '\\' in series

        def _has_series_link(txt: str) -> bool:
            import unicodedata as _ud2
            tl = _ud2.normalize('NFC', txt).lower().replace('\u0451', '\u0435')
            return not series_words or any(w in tl for w in series_words)

        # Regex для удаления пометок тома родительской серии вида «(т. 7-8)»
        _VOL_ANNOT_STRIP = re.compile(
            r'\((?:т|том|vol|book|ч|часть)\.?\s*\d+[-–—]\d+\)', re.IGNORECASE | re.UNICODE
        )

        # Критерий 1: диапазон "N-M" в имени файла (stem) или title — приоритет выше метаданных
        # Имя файла отражает реальную организацию библиотеки, метаданные могут быть неточными.
        _RANGE_RE = re.compile(r'(\d+)\s*[-–—]\s*(\d+)', re.UNICODE)
        # Диапазон в самом начале stem: «01-2_...», «1-3 Название» — явная нумерация файла,
        # не требует проверки series_link (серия может не упоминаться в имени файла).
        _LEADING_RANGE_RE = re.compile(r'^\d+\s*[-–—]\s*\d+', re.UNICODE)
        _stem_val = book.abs_path.stem
        for candidate in (_stem_val, book.record.file_title or ''):
            if is_subseries:
                # Для подсерий: убираем пометки тома родительской серии вида «(т. 7-8)»,
                # затем ищем диапазон без проверки series_link (имя подсерии редко
                # фигурирует в имени файла компиляции).
                bare = _VOL_ANNOT_STRIP.sub('', candidate).strip()
                m = _RANGE_RE.search(bare)
            else:
                # Если диапазон стоит в начале имени файла — принимаем без series_link.
                # Пример: «01-2_Свободу демонам! Том 1 и 2» → диапазон 1-2 очевиден.
                stem_leading = (candidate == _stem_val) and bool(_LEADING_RANGE_RE.match(candidate))
                if not stem_leading and not _has_series_link(candidate):
                    continue
                m = _RANGE_RE.search(candidate)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if hi > lo:
                    return lo, hi

        # Критерий 2.5: сервисное слово в имени ФАЙЛА (stem) — filename авторитетнее метаданных.
        # Пример: «Орел (Тетралогия)» → Тетралогия=4, хотя series_number может быть "1-2".
        # Проверяем stem ДО series_number, чтобы явное слово в имени файла не было перебито.
        _stem_lower = book.abs_path.stem.lower()
        for idx, kw in enumerate(self._SERIES_WORDS):
            if kw and kw.lower() in _stem_lower:
                if _has_series_link(_stem_lower):
                    return 1, idx

        # Критерий 2: series_number — диапазон "N-M" из метаданных (запасной вариант)
        # Для подсерий пропускаем: series_number ссылается на родительскую серию.
        if not is_subseries:
            sn = (book.record.series_number or '').strip()
            if sn:
                m = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', sn)
                if m:
                    lo, hi = int(m.group(1)), int(m.group(2))
                    if hi > lo:
                        return lo, hi

        # Критерий 3: title содержит сервисное слово + признак серии.
        # (stem уже проверен в Критерии 2.5)
        for _kw_text in ((book.record.file_title or '').lower(),):
            if not _kw_text:
                continue
            for idx, kw in enumerate(self._SERIES_WORDS):
                if kw and kw.lower() in _kw_text:
                    if _has_series_link(_kw_text):
                        return 1, idx  # сервисное слово → предполагаем lo=1

        # Критерий 4: файл выглядит как компиляция (по имени/title) — читаем FB2-контент
        _COMPILATION_WORDS = re.compile(
            r'компилян|компиляц|сборник|omnibus|антолог|собрани', re.IGNORECASE | re.UNICODE
        )
        _title_text = (book.record.file_title or book.abs_path.stem).lower()
        if _COMPILATION_WORDS.search(_title_text) or _COMPILATION_WORDS.search(book.abs_path.stem.lower()):
            lo, hi = self._precompiled_range_from_content(book.abs_path, series)
            if hi > lo:
                return lo, hi

        return 0, 0

    # ---- регулярки для парсинга FB2 ----
    _FB2_SEQUENCE_RE = re.compile(
        r'<sequence[^>]+number=["\'](\d+)["\']', re.IGNORECASE | re.DOTALL
    )
    _FB2_SECTION_TITLE_RE = re.compile(
        r'<section[^>]*>\s*<title[^>]*>\s*<p[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL
    )

    def _precompiled_range_from_content(self, abs_path: Path, series: str) -> Tuple[int, int]:
        """Определить диапазон томов по содержимому FB2-файла.

        Читает первые 64KB и ищет:
        1. <sequence number="N"> внутри отдельных секций — берём min/max N
        2. Заголовки секций первого уровня — ищем «Том N», «Книга N», римские цифры

        Возвращает (lo, hi) или (0, 0) если не удалось определить.
        """
        try:
            if not abs_path.exists():
                return 0, 0
            raw = abs_path.read_bytes()[:65536]
            try:
                text = raw.decode('utf-8', errors='replace')
            except Exception:
                text = raw.decode('cp1251', errors='replace')
        except Exception:
            return 0, 0

        nums: List[int] = []

        # Способ 1: <sequence number="N"> внутри <section> (наш компилятор прописывает их)
        for m in self._FB2_SEQUENCE_RE.finditer(text):
            n = int(m.group(1))
            if 1 <= n <= 100:
                nums.append(n)

        # Способ 2: заголовки секций первого уровня — ищем числа и ключевые слова
        for m in self._FB2_SECTION_TITLE_RE.finditer(text):
            title_text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
            # Ключевые слова тома + арабская цифра
            km = self._VOLUME_KEYWORDS_RE.search(title_text)
            if km:
                n = int(km.group(1))
                if 1 <= n <= 100:
                    nums.append(n)
                continue
            # Римские цифры в заголовке
            rm = self._VOLUME_ROMAN_RE.search(title_text)
            if rm:
                n = self._roman_to_int(rm.group(1))
                if n and 1 <= n <= 100:
                    nums.append(n)
                continue
            # Просто арабская цифра в начале/конце заголовка (осторожно: только если одна)
            dm = re.match(r'^(\d{1,2})[\s\.\-–]|[\s\.\-–](\d{1,2})$', title_text)
            if dm:
                n = int(next(g for g in dm.groups() if g is not None))
                if 1 <= n <= 100:
                    nums.append(n)

        if not nums:
            return 0, 0
        lo, hi = min(nums), max(nums)
        # Требуем хотя бы 2 разных номера, чтобы не принять один том за диапазон
        if lo == hi or hi - lo > 20:  # слишком большой пробел — ненадёжно
            return 0, 0
        return lo, hi

    def _precompiled_count(self, book: CompilationBook, series: str) -> int:
        """Обёртка для обратной совместимости. Возвращает hi - lo + 1 или 0."""
        lo, hi = self._precompiled_range(book, series)
        return (hi - lo + 1) if hi > lo else 0

    @classmethod
    def _normalize_title_key(cls, raw_title: str, series: str) -> str:
        """Нормализовать заголовок для дедупликации.

        Убирает возможный префикс в виде «<Серия>. » или «<Серия> » перед
        собственно названием книги, чтобы «Аквилон. Маг воды. Том 3» и
        «Маг воды. Том 3» воспринимались как один и тот же том.

        Применяет NFKC-нормализацию чтобы Unicode-символы римских цифр
        (Ⅰ U+2160 … Ⅻ U+216B) приводились к ASCII-эквивалентам (I … XII)
        и не создавали ложных дублей.
        """
        # NFKC: Ⅰ→I, Ⅱ→II, …, Ⅻ→XII и т.п.
        key = unicodedata.normalize('NFKC', raw_title).strip().lower().replace('ё', 'е')
        series_norm = unicodedata.normalize('NFKC', series).strip().lower().replace('ё', 'е')
        # Попробовать отрезать префикс вида "<серия>. " или "<серия> "
        for sep in ('. ', ' '):
            candidate = series_norm + sep
            if key.startswith(candidate):
                key = key[len(candidate):]
                break
        return key

    def _dedup_by_position(
        self,
        books: List[CompilationBook],
        duplicate_paths: List[Path],
    ) -> List[CompilationBook]:
        """Убрать книги-дубликаты с одинаковой позицией тома.

        После title-дедупликации может остаться несколько книг с одним и тем же
        sort_key на уровне 0 (series_number) или 1 (filename number).  Из таких
        дублей оставляем первую по алфавиту (det. выбор), остальные идут в
        duplicate_paths.

        Книги с ambiguous sort_key (уровень 9) из этого фильтра исключены —
        для них позиция неизвестна, они останутся до проверки order_determined.
        """
        # Для книг с одинаковой позицией тома оставляем наиболее свежую версию.
        # Для книг с одинаковой позицией тома выбираем наиболее свежую версию.
        # Критерии (по убыванию надёжности):
        #   1. Дата из тега <date> в title-info FB2 — самый достоверный признак
        #   2. Явные ключевые слова "свежести" в имени файла или title
        #   3. Алфавитный порядок пути (детерминированный fallback)
        _FRESH_KEYWORDS = re.compile(
            r'новый?\s+вариант|новая?\s+редакц|переработан|updated?|revision|new\s+ver',
            re.IGNORECASE | re.UNICODE,
        )

        def _book_freshness(book: CompilationBook):
            """Ключ сортировки: чем свежее — тем меньше (идёт первым)."""
            # 1. Дата из FB2 <date> — лексикографически сравниваем, инвертируем
            date_str = self._extract_date_from_fb2(book.abs_path) or ''
            date_key = tuple(-int(x) for x in date_str.split('-')) if date_str else (0,)

            # 2. Ключевые слова в имени/названии
            text = f"{book.abs_path.stem} {book.record.file_title or ''}"
            kw_key = 0 if _FRESH_KEYWORDS.search(text) else 1

            return (date_key, kw_key, str(book.abs_path))

        sorted_books = sorted(books, key=_book_freshness)
        seen_positions: Dict[Tuple, CompilationBook] = {}
        result: List[CompilationBook] = []
        for book in sorted_books:
            level = book.sort_key[0]
            if level == 0:
                pos_key = book.sort_key  # (0, num, 0)
                if pos_key not in seen_positions:
                    seen_positions[pos_key] = book
                    result.append(book)
                else:
                    duplicate_paths.append(book.abs_path)
            else:
                result.append(book)
        return result

    def _determine_sort_key(
        self, rec, abs_path: Path
    ) -> Tuple[Tuple, str, bool, str]:
        """Многоуровневое определение порядка книги.

        Returns:
            (sort_key_tuple, source_name, is_ambiguous, volume_label)
            volume_label — отображаемый номер/диапазон: "1", "1-3", "2021" и т.п.
        """
        stem = Path(rec.file_path).stem

        # DEBUG
        try:
            with open(Path(__file__).parent / 'fb2_sort_debug.txt', 'a', encoding='utf-8') as _dbg:
                _dbg.write(f"SORT stem={stem!r} sn={getattr(rec,'series_number','?')!r} ft={getattr(rec,'file_title','?')!r} ps={getattr(rec,'proposed_series','?')!r}\n")
        except Exception:
            pass

        # Источник А: series_number из FB2-метаданных.
        # Пропускаем для подсерий (proposed_series содержит '\') — там series_number
        # относится к родительской серии и не отражает позицию внутри подсерии.
        #
        # ВАЖНО: series_number берётся ТОЛЬКО если metadata_series соответствует
        # proposed_series. Если в FB2 указана другая серия (например, "Викинг" вместо
        # "Варяг"), её порядковый номер не имеет смысла для текущей серии.
        is_subseries = '\\' in (rec.proposed_series or '')
        sn = (rec.series_number or '').strip()
        if sn and not is_subseries:
            meta_s = (rec.metadata_series or '').strip().lower().replace('ё', 'е')
            prop_s = (rec.proposed_series or '').strip().lower().replace('ё', 'е')
            # Слова proposed_series длиной ≥ 3 (ключевые слова серии)
            prop_words = {w for w in prop_s.split() if len(w) >= 3}
            # series_number применяем только если metadata_series не задана,
            # или совпадает с proposed_series, или содержит хотя бы одно ключевое слово
            _series_ok = (
                not meta_s
                or meta_s == prop_s
                or bool(prop_words and any(w in meta_s for w in prop_words))
            )
            if _series_ok:
                meta_num: Optional[int] = None
                if re.match(r'^\d+$', sn):
                    meta_num = int(sn)
                else:
                    rng = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', sn)
                    if rng:
                        meta_num = int(rng.group(1))

                if meta_num is not None:
                    # Паттерн N.M (dot_part) имеет приоритет над series_number:
                    # файлы вида «Расходники 2.3» должны получить sort_key (0,2,3)
                    # а не (0,5,0) из метаданных, иначе они не попадут в один run
                    # с файлами 1.1, 1.2, 2.1, у которых sn отсутствует.
                    _dp = self._extract_dot_part(stem, rec.file_title or '')
                    if _dp is not None:
                        _dv, _dpt = _dp
                        return (0, _dv, _dpt), 'dot_part', False, f'{_dv}.{_dpt}'

                    # Перекрёстная проверка с именем файла.
                    # Если в stem явно написан другой номер — доверяем файлу,
                    # иначе метаданные могут быть ошибочными (например, sn='1' для тома 2).
                    fn_m = (self._STEM_NUM_RE.match(stem) or self._STEM_NUM_RE.search(stem)
                            or re.search(r'(?:^|[-–\s])(\d{1,4})\.\s+[А-ЯЁA-Z]', stem))
                    if fn_m:
                        fn_num = int(next(g for g in fn_m.groups() if g is not None))
                        # Числа >= 1900 — год в имени файла, не номер тома; игнорируем
                        if fn_num < 1900 and fn_num != meta_num:
                            # Расхождение: имя файла важнее ошибочных метаданных
                            return (0, fn_num, 0), 'filename', False, str(fn_num)
                    # Дополнительная проверка: Roman numeral inline («Том Ⅱ», «Том III» …).
                    # FB2-метаданные нередко хранят series_number="1" для всех томов серии,
                    # тогда как имя файла содержит точный номер в виде римской цифры.
                    _ft2 = rec.file_title or ''
                    _ft2_is_series = bool(_ft2) and _norm_key(_ft2) == _norm_key(rec.proposed_series or '')
                    # Проверяем паттерн «Том N. Часть M» ДО roman_inline —
                    # иначе «Том XII. Часть вторая» даёт roman_inline=12 != meta_num=13
                    # и возвращает (0, 12, 0) без учёта части.
                    _ft_for_part = rec.file_title or ''
                    vp = self._extract_volume_part(_ft_for_part, stem)
                    if vp is not None:
                        vol, part = vp
                        return (0, vol, part), 'volume_part', False, str(vol)
                    roman_inline = self._extract_inline_volume_number(
                        stem if _ft2_is_series else (_ft2 or stem), stem
                    )
                    if roman_inline is not None and roman_inline != meta_num:
                        return (0, roman_inline, 0), 'inline_title', False, str(roman_inline)
                    return (0, meta_num, 0), 'series_number', False, sn

        # Для подсерий: «Том N» в названии файла/title важнее общего числа в stem.
        # Пример: "Хроника 2. День второй. Том 1" — «2» это арк родительской серии,
        # «Том 1» — реальный номер тома внутри подсерии.
        if is_subseries:
            # Порядковый номер родительской серии: "Азиатская сага 04\Роман" → parent_num=4
            _root_part = (rec.proposed_series or '').split('\\')[0].strip()
            _parent_num_m = re.search(r'\s(\d{1,4})\s*$', _root_part)
            parent_num = int(_parent_num_m.group(1)) if _parent_num_m else 0

            inline = self._extract_inline_volume_number(rec.file_title or stem, stem)
            if inline is not None:
                if parent_num:
                    return (0, parent_num, inline), 'inline_title', False, f'{parent_num}.{inline}'
                return (0, inline, 0), 'inline_title', False, str(inline)

            # Извлечь номер подсерии по её имени в stem.
            # Пример: proposed_series="Земной круг 1\Первый закон", stem содержит
            # "Первый закон 2. Прежде чем их повесят" → номер подсерии = 2.
            subseries_name = (rec.proposed_series or '').split('\\')[-1].strip()
            if subseries_name:
                _sub_re = re.compile(
                    re.escape(subseries_name) + r'\s+(\d{1,4})',
                    re.IGNORECASE | re.UNICODE,
                )
                _sm = _sub_re.search(stem) or _sub_re.search(rec.file_title or '')
                if _sm:
                    sub_num = int(_sm.group(1))
                    if sub_num < 1900:
                        if parent_num:
                            return (0, parent_num, sub_num), 'subseries_number', False, f'{parent_num}.{sub_num}'
                        return (0, sub_num, 0), 'subseries_number', False, str(sub_num)

            # Если series_number из метаданных относится к подсерии (metadata_series
            # совпадает с именем подсерии) — использовать его.
            if sn:
                sub_name = (rec.proposed_series or '').split('\\')[-1].strip()
                meta_s_low = (rec.metadata_series or '').strip().lower().replace('ё', 'е')
                sub_name_low = sub_name.lower().replace('ё', 'е')
                if meta_s_low and sub_name_low and (
                    meta_s_low == sub_name_low
                    or meta_s_low in sub_name_low
                    or sub_name_low in meta_s_low
                ):
                    if re.match(r'^\d+$', sn):
                        sn_int = int(sn)
                        if parent_num:
                            return (0, parent_num, sn_int), 'series_number', False, f'{parent_num}.{sn}'
                        return (0, sn_int, 0), 'series_number', False, sn

            # parent_num найден, но внутренний номер не определён
            if parent_num:
                return (0, parent_num, 0), 'parent_num', False, str(parent_num)

        # Источник Б: число в начале/конце имени файла
        num_m = self._STEM_NUM_RE.match(stem) or self._STEM_NUM_RE.search(stem) or re.search(
            r'(?:^|[-–\s])(\d{1,4})\.\s+[А-ЯЁA-Z]', stem
        )
        if num_m:
            num = int(next(g for g in num_m.groups() if g is not None))
            # Числа >= 1900 — скорее всего год в имени файла, не номер тома.
            # Пример: «Тысяча и одна ночь. Том Ⅰ - 2022» → 2022 не номер тома.
            if num < 1900:
                return (0, num, 0), 'filename', False, str(num)

        # Источник В: диапазон томов в скобках внутри stem — «(Серия 1-3)», «(4-6)»
        # Используем MIN как позицию сортировки: файл (1-3) → 1, файл (4-6) → 4
        range_m = re.search(
            r'\((?:[^()]*?\s)?(\d{1,4})\s*[-–—]\s*(\d{1,4})\)', stem
        )
        if range_m:
            lo, hi = range_m.group(1), range_m.group(2)
            return (0, int(lo), 0), 'filename_range', False, f'{lo}-{hi}'

        # Источник Г: ключевое слово внутри title/stem («Свиток 1», «Том 3» …)
        # Если file_title совпадает с именем серии — он не несёт информации о конкретном
        # томе (например, «Тысяча и одна ночь. В 12 томах» для всех 12 файлов).
        # В таком случае используем только stem, где есть реальный номер тома.
        _ft = rec.file_title or ''
        _proposed = getattr(rec, 'proposed_series', '') or ''
        _ft_is_series = bool(_ft) and _norm_key(_ft) == _norm_key(_proposed)

        # Паттерн N.M (том.часть) — проверяем первым, до других inline-методов.
        # Пример: «Расходники 1.2_Название» → том=1, часть=2.
        dp = self._extract_dot_part(stem, _ft or '')
        if dp is not None:
            vol, part = dp
            return (0, vol, part), 'dot_part', False, f'{vol}.{part}'

        # Проверяем паттерн «Том N. Часть M» до общего inline-поиска,
        # чтобы «Часть» не интерпретировалась как ключевое слово тома.
        vp = self._extract_volume_part(_ft or stem, stem)
        if vp is not None:
            vol, part = vp
            return (0, vol, part), 'volume_part', False, str(vol)

        inline = self._extract_inline_volume_number(
            stem if _ft_is_series else (_ft or stem), stem
        )
        if inline is not None:
            return (0, inline, 0), 'inline_title', False, str(inline)

        # Уровень 3: дата из FB2 title-info
        year = self._extract_year_from_fb2(abs_path, section='title-info')
        if year:
            return (2, year, 0), 'title_date', False, str(year)

        # Уровень 4: дата из publish-info
        year = self._extract_year_from_fb2(abs_path, section='publish-info')
        if year:
            return (3, year, 0), 'publish_date', False, str(year)

        # Порядок не определён
        return (9, 0, 0), 'unknown', True, ''

    def _extract_date_from_fb2(self, path: Path, section: str = 'title-info') -> Optional[str]:
        """Извлечь дату из <date> внутри указанной секции FB2.

        Возвращает строку вида 'YYYY-MM-DD' или 'YYYY' — пригодную для
        лексикографического сравнения (более поздняя дата > ранняя).
        Возвращает None если дата не найдена или файл недоступен.
        """
        try:
            if not path.exists():
                return None
            chunk = path.read_bytes()[:8192]
            try:
                text = chunk.decode('utf-8', errors='replace')
            except Exception:
                text = chunk.decode('cp1251', errors='replace')

            sec_m = re.search(
                rf'<(?:fb:)?{re.escape(section)}>(.*?)</(?:fb:)?{re.escape(section)}>',
                text, re.DOTALL | re.IGNORECASE,
            )
            if not sec_m:
                return None
            sec_text = sec_m.group(1)

            # Предпочитаем атрибут value="YYYY-MM-DD" как наиболее точный
            m = re.search(
                r'<(?:fb:)?date[^>]*value=["\'](\d{4}(?:-\d{2}(?:-\d{2})?)?)["\']',
                sec_text, re.IGNORECASE,
            )
            if m:
                return m.group(1)
            # Fallback: текстовое содержимое тега <date>YYYY-MM-DD</date>
            m = re.search(
                r'<(?:fb:)?date[^>]*>(\d{4}(?:-\d{2}(?:-\d{2})?)?)</(?:fb:)?date>',
                sec_text, re.IGNORECASE,
            )
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    def _extract_year_from_fb2(self, path: Path, section: str) -> Optional[int]:
        """Извлечь год из <date> внутри указанной секции FB2."""
        try:
            if not path.exists():
                return None
            raw = path.read_bytes()
            # Минимальное чтение — только первые 8 КБ (метаданные в начале)
            chunk = raw[:8192]
            try:
                text = chunk.decode('utf-8', errors='replace')
            except Exception:
                text = chunk.decode('cp1251', errors='replace')

            # Найти нужную секцию
            sec_m = re.search(
                rf'<(?:fb:)?{re.escape(section)}>(.*?)</(?:fb:)?{re.escape(section)}>',
                text, re.DOTALL | re.IGNORECASE
            )
            if not sec_m:
                return None
            sec_text = sec_m.group(1)

            # <date value="YYYY-..."> или <date>YYYY</date>
            date_m = re.search(
                r'<(?:fb:)?date[^>]*value=["\'](\d{4})', sec_text, re.IGNORECASE
            ) or re.search(
                r'<(?:fb:)?date[^>]*>(\d{4})', sec_text, re.IGNORECASE
            )
            if date_m:
                return int(date_m.group(1))
        except Exception:
            pass
        return None

    def _split_into_consecutive_runs(
        self,
        books: List[CompilationBook],
    ) -> List[List[CompilationBook]]:
        """Разбить числовые (level-0) книги на непрерывные подгруппы без пропусков.

        На вход ожидаются ТОЛЬКО книги с sort_key[0] == 0 (series_number / filename).
        Предкомпилированные файлы с диапазоном (volume_label="1-3") учитываются по
        верхней границе: следующий файл с lo <= hi+1 считается непрерывным или
        перекрывающимся (и тогда объединяется в один блок для компиляции).
        Пример: [1-42] + [31-45]: lo=31 <= 43 → один блок → итог 1-45.
        Пример: [1-5]  + [6-9]:  lo=6  <= 6  → один блок → итог 1-9.
        Пример: [1-5]  + [7-9]:  lo=7  > 6   → разные блоки (пропуск тома 6).
        """
        if not books:
            return []

        def get_hi(book: CompilationBook) -> int:
            rng = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', book.volume_label or '')
            return int(rng.group(2)) if rng else book.sort_key[1]

        runs: List[List[CompilationBook]] = []
        current_run: List[CompilationBook] = [books[0]]
        prev_hi = get_hi(books[0])

        for book in books[1:]:
            lo = book.sort_key[1]
            if lo <= prev_hi + 1:  # следующий или перекрывающийся диапазон
                current_run.append(book)
                prev_hi = get_hi(book)
            else:
                runs.append(current_run)
                current_run = [book]
                prev_hi = get_hi(book)
        runs.append(current_run)

        return runs

    def _sort_books(
        self, books: List[CompilationBook]
    ) -> Tuple[List[CompilationBook], bool, bool]:
        """Отсортировать книги и определить, однозначен ли порядок.

        Returns:
            (sorted_books, order_determined, alphabetical_order)
            alphabetical_order=True — у всех книг неизвестная позиция,
            отсортированы по названию как единственный детерминированный вариант.
        """
        all_ambiguous = all(b.order_ambiguous for b in books)

        if all_ambiguous:
            # Нет нумерации — сортируем по названию (алфавитный порядок)
            sorted_books = sorted(
                books,
                key=lambda b: (b.record.file_title or b.abs_path.stem).lower(),
            )
            return sorted_books, True, True

        has_ambiguous = any(b.order_ambiguous for b in books)
        sorted_books = sorted(books, key=lambda b: b.sort_key)
        return sorted_books, not has_ambiguous, False

    def _compute_volume_range(self, books: List[CompilationBook]) -> str:
        """Вернуть строку диапазона томов, например '1-7'."""
        nums = []
        for b in books:
            level = b.sort_key[0]
            val = b.sort_key[1]
            if level == 0 and isinstance(val, int):
                nums.append(val)

        # Также из volume_label (для прекомпилированных диапазонов типа "3-5")
        for b in books:
            vl = (b.volume_label or '').strip()
            rng = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', vl)
            if rng:
                lo2, hi2 = int(rng.group(1)), int(rng.group(2))
                nums.extend(range(lo2, hi2 + 1))

        # Также из series_number самой записи (может быть уже диапазоном "1-3")
        for b in books:
            sn = (b.record.series_number or '').strip()
            rng = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', sn)
            if rng:
                lo, hi = int(rng.group(1)), int(rng.group(2))
                nums.extend(range(lo, hi + 1))

        if not nums:
            return ''
        lo, hi = min(nums), max(nums)
        if lo == hi:
            return str(lo)
        # Проверяем: все тома от lo до hi реально присутствуют (нет пробелов)?
        present = set(nums)
        if all(v in present for v in range(lo, hi + 1)):
            return f'{lo}-{hi}'
        # Есть пробелы — не создаём ложный диапазон, возвращаем пустую строку
        return ''

    # ------------------------------------------------------------------
    # Компиляция
    # ------------------------------------------------------------------

    def compile_group(
        self,
        group: CompilationGroup,
        output_dir: Optional[Path],
        delete_sources: bool = False,
    ) -> CompilationResult:
        """Скомпилировать группу в один FB2-файл.

        Args:
            group: Группа книг для компиляции.
            output_dir: Папка, куда поместить результирующий файл.
                        None — сохранить рядом с исходными файлами.
            delete_sources: Удалить исходники после успешной компиляции.

        Returns:
            CompilationResult с результатами.
        """
        self._log(f"Компиляция: {group.author} / {group.series} ({len(group.books)} книг)")

        # Cleanup-only: новая компиляция не нужна, только удалить устаревшие файлы
        if getattr(group, 'cleanup_only', False):
            if group.duplicate_paths:
                self._delete_sources(group.duplicate_paths)
                self._log(f"   ♻ Удалено {len(group.duplicate_paths)} устаревших файлов")
            return CompilationResult(
                group=group,
                output_path=None,
                books_compiled=0,
                source_paths=list(group.duplicate_paths),
                success=True,
                error="",
            )

        try:
            # --- Читаем содержимое каждого файла с учётом перекрытий диапазонов ---
            # Если два файла — предкомпиляции с перекрывающимися диапазонами
            # (например [1-42] и [31-45]), берём из второго только те секции,
            # которые не покрыты первым (тома 43-45).
            bodies: List[Tuple[str, str]] = []  # (book_title, body_xml)
            covered_hi = 0  # максимальный номер тома, уже добавленного в bodies
            # Бинари (обложки, иллюстрации) из всех исходников; дедупликация по id
            collected_binaries: List[str] = []
            seen_binary_ids: set = set()

            for book in group.books:
                # Собираем бинари из каждого исходника (дедупликация по id)
                for bin_block in self._extract_binaries(book):
                    id_m = re.search(r'<binary[^>]+id=["\']([^"\']+)["\']', bin_block, re.IGNORECASE)
                    bin_id = id_m.group(1) if id_m else bin_block[:40]
                    if bin_id not in seen_binary_ids:
                        seen_binary_ids.add(bin_id)
                        collected_binaries.append(bin_block)

                rng_m = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', book.volume_label or '')
                if rng_m:
                    # Предкомпиляция с известным диапазоном — разбиваем на секции
                    b_lo, b_hi = int(rng_m.group(1)), int(rng_m.group(2))
                    sections = self._extract_body_sections(book, b_lo, b_hi)
                    if not sections:
                        raise RuntimeError(
                            f"Не удалось извлечь секции из: {book.abs_path.name}"
                        )
                    # Берём только секции, ещё не покрытые предыдущими файлами
                    to_add = [(v, t, bx) for v, t, bx in sections if v > covered_hi]
                    if not to_add:
                        self._log(f"  ℹ Пропуск {book.abs_path.name} — полностью покрыт предыдущим файлом")
                        continue
                    skipped = len(sections) - len(to_add)
                    if skipped:
                        first_new = min(v for v, _, _ in to_add)
                        self._log(
                            f"  ✂ {book.abs_path.name}: пропускаем {skipped} томов "
                            f"(уже покрыты до тома {covered_hi}), "
                            f"берём {len(to_add)} томов начиная с {first_new}"
                        )
                    for _vol, sec_title, sec_body in to_add:
                        bodies.append((sec_title, sec_body))
                    covered_hi = max(covered_hi, b_hi)
                else:
                    # Обычная книга — берём целиком
                    title, body_xml = self._extract_body(book)
                    if body_xml is None:
                        raise RuntimeError(
                            f"Не удалось извлечь <body> из: {book.abs_path.name}"
                        )
                    bodies.append((title, body_xml))
                    sn = book.sort_key[1] if book.sort_key[0] == 0 else 0
                    if sn:
                        covered_hi = max(covered_hi, sn)

            # --- Извлекаем метаданные из первой (или лучшей) книги ---
            meta = self._extract_metadata(group.books[0])

            # --- Имя выходного файла и clean_series ---
            clean_series = self._clean_series_name(group.series)
            safe_author = re.sub(r'[\\/:*?"<>|]', '_', group.author)
            safe_series = re.sub(r'[/:*?"<>|]', '_', clean_series.replace('\\', '. '))

            # --- Папка назначения: явная или рядом с исходниками ---
            dest_dir = output_dir if output_dir is not None else group.books[0].abs_path.parent

            # --- Собираем итоговый XML ---
            volume_range = group.volume_range or self._compute_volume_range(group.books)
            output_xml = self._build_fb2(
                author=group.author,
                series=clean_series,
                volume_range=volume_range,
                genre=meta.get('genre', ''),
                bodies=bodies,
                binaries=collected_binaries,
                part_count=getattr(group, 'part_count', 0),
            )

            # --- Имя выходного файла ---
            suffix = self._series_suffix(len(group.books), volume_range, getattr(group, 'part_count', 0))
            fname = f"{safe_author} - {safe_series} ({suffix}).fb2"

            output_path = dest_dir / fname
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output_xml, encoding='utf-8')

            self._log(f"  ✓ Создан файл: {output_path.name}")

            # --- Удаляем дубликаты (всегда, безусловно) ---
            if group.duplicate_paths:
                self._delete_sources(group.duplicate_paths)
                self._log(f"   ♻ Удалено {len(group.duplicate_paths)} дубликатах")

            # --- Удаляем исходники ---
            source_paths = [b.abs_path for b in group.books]
            if delete_sources:
                self._delete_sources(source_paths)

            return CompilationResult(
                group=group,
                output_path=output_path,
                books_compiled=len(bodies),
                source_paths=source_paths,
                success=True,
            )

        except Exception as e:
            self._log(f"  ✗ Ошибка компиляции {group.series}: {e}")
            return CompilationResult(
                group=group,
                output_path=Path(''),
                books_compiled=0,
                source_paths=[b.abs_path for b in group.books],
                success=False,
                error=str(e),
            )

    def _read_file_text(self, path: Path) -> str:
        """Прочитать файл с автоопределением кодировки."""
        raw = path.read_bytes()
        # Определяем кодировку из XML-декларации
        declared = None
        m = re.search(
            rb'<\?xml[^>]*encoding\s*=\s*["\']([^"\']+)["\']', raw[:256], re.IGNORECASE
        )
        if m:
            declared = m.group(1).decode('ascii', errors='ignore')

        for enc in filter(None, [declared, 'utf-8-sig', 'utf-8', 'cp1251']):
            try:
                return raw.decode(enc, errors='strict')
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode('utf-8', errors='replace')

    def _extract_body(self, book: CompilationBook) -> Tuple[str, Optional[str]]:
        """Извлечь заголовок книги и главный <body> блок (без notes/footnotes)."""
        title = (book.record.file_title or '').strip() or book.abs_path.stem

        if not book.abs_path.exists():
            self._log(f"  ⚠ Файл не найден: {book.abs_path}")
            return title, None

        try:
            text = self._read_file_text(book.abs_path)
        except Exception as e:
            self._log(f"  ⚠ Ошибка чтения {book.abs_path.name}: {e}")
            return title, None

        all_bodies = re.findall(
            r'<(?:fb:)?body(?:\s[^>]*)?>.*?</(?:fb:)?body>',
            text, re.DOTALL | re.IGNORECASE
        )
        if not all_bodies:
            return title, None

        # Берём только главные тела (без name="notes"/"footnotes").
        # <body name="notes"> — сноски; их включение создаёт вложенные <body> в итоговом файле.
        _NOTES_RE = re.compile(r'<(?:fb:)?body[^>]+\bname\s*=\s*["\'](?:notes|footnotes)["\']',
                               re.IGNORECASE)
        main_bodies = [b for b in all_bodies if not _NOTES_RE.match(b[:200])]
        bodies = main_bodies if main_bodies else all_bodies[:1]

        combined = '\n'.join(bodies)
        return title, combined

    # ---- вспомогательные методы для разбора секций предкомпиляций ----

    @staticmethod
    def _split_top_level_sections(body_xml: str) -> List[str]:
        """Извлечь секции первого уровня из тела FB2.

        Использует счётчик глубины вложенности, чтобы корректно обрабатывать
        вложенные <section>.  Возвращает список XML-фрагментов каждой секции.
        """
        sections: List[str] = []
        depth = 0
        start = 0
        tag_re = re.compile(
            r'<(/?)(?:fb:)?section(?:\s[^>]*)?>',
            re.IGNORECASE,
        )
        for m in tag_re.finditer(body_xml):
            is_close = bool(m.group(1))
            if not is_close:
                if depth == 0:
                    start = m.start()
                depth += 1
            else:
                if depth > 0:
                    depth -= 1
                if depth == 0 and start is not None:
                    sections.append(body_xml[start:m.end()])
                    start = None
        return sections

    @staticmethod
    def _detect_section_volume(section_xml: str) -> Optional[int]:
        """Попытаться определить номер тома внутри секции.

        Порядок проверки:
        1. <sequence number="N"> — прописывается нашим компилятором.
        2. Заголовок <title> содержит «Книга N» / «Том N» / «Часть N» /
           «Book N» / «Vol N» / «Part N» / «Tom N» (1–2 варианта).
        3. Римские цифры в заголовке: «Книга II» → 2.
        Возвращает int или None.
        """
        # Способ 1: <sequence number="N">
        m = re.search(
            r'<(?:fb:)?sequence[^>]+number=["\'](\d+)["\']',
            section_xml, re.IGNORECASE,
        )
        if m:
            return int(m.group(1))

        # Способ 2: заголовок секции
        title_m = re.search(
            r'<(?:fb:)?title[^>]*>(.*?)</(?:fb:)?title>',
            section_xml, re.IGNORECASE | re.DOTALL,
        )
        if title_m:
            title_text = re.sub(r'<[^>]+>', '', title_m.group(1))
            # Нормализовать Unicode-символы римских цифр в ASCII: Ⅻ → XII, Ⅰ → I и т.п.
            title_text = unicodedata.normalize('NFKC', title_text)
            # Арабские цифры после ключевых слов
            kw_m = re.search(
                r'(?:книга|том|часть|book|vol(?:ume)?|part|том)\s*[.:\-]?\s*(\d+)',
                title_text, re.IGNORECASE,
            )
            if kw_m:
                return int(kw_m.group(1))
            # Римские цифры после ключевых слов
            # (?=[MDCLXVI]) гарантирует непустое совпадение;
            # V?I{0,3} вместо V?I{1,3} позволяет матчить V, X, XL, XLV и т.п.
            roman_m = re.search(
                r'(?:книга|том|часть|book|vol(?:ume)?|part)\s*[.:\-]?\s*'
                r'((?=[MDCLXVI])M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3}))',
                title_text, re.IGNORECASE,
            )
            if roman_m and roman_m.group(1):
                n = FB2CompilerService._roman_to_int(roman_m.group(1))
                if n:
                    return n
        return None

    def _extract_body_sections(
        self,
        book: CompilationBook,
        b_lo: int = 1,
        b_hi: int = 0,
    ) -> List[Tuple[int, str, str]]:
        """Разбить предкомпиляцию на секции: [(vol_num, title, body_xml), ...].

        vol_num — реальный номер тома в серии (b_lo … b_hi).

        Алгоритм:
        1. Если <body> блоков столько же, сколько томов (наш формат) —
           каждый <body> = один том, нумеруем с b_lo.
        2. Если один <body> (внешний формат) — пробуем разбить на top-level
           <section> и определить номер тома по <sequence> или заголовку.
           Если номера найдены и покрывают ≥70% секций — используем их.
           Иначе нумеруем секции последовательно с b_lo.
        3. Если секций нет — возвращаем один элемент (весь body).
        """
        stem = book.abs_path.stem
        if not book.abs_path.exists():
            return []
        try:
            text = self._read_file_text(book.abs_path)
        except Exception:
            return []

        all_raw_bodies = re.findall(
            r'<(?:fb:)?body(?:\s[^>]*)?>.*?</(?:fb:)?body>',
            text, re.DOTALL | re.IGNORECASE,
        )
        if not all_raw_bodies:
            return []

        # Отфильтровываем сноски — берём только главные тела.
        _NOTES_RE2 = re.compile(r'<(?:fb:)?body[^>]+\bname\s*=\s*["\'](?:notes|footnotes)["\']',
                                re.IGNORECASE)
        raw_bodies = [b for b in all_raw_bodies if not _NOTES_RE2.match(b[:200])]
        if not raw_bodies:
            raw_bodies = all_raw_bodies[:1]

        _title_re = re.compile(
            r'<(?:fb:)?title[^>]*>\s*<(?:fb:)?p[^>]*>(.*?)</(?:fb:)?p>',
            re.IGNORECASE | re.DOTALL,
        )

        def _body_title(xml: str, idx: int) -> str:
            m = _title_re.search(xml)
            return re.sub(r'<[^>]+>', '', m.group(1)).strip() if m else f'{stem} ({idx})'

        expected = b_hi - b_lo + 1 if b_hi >= b_lo else 0

        # --- Случай 1: наш формат (один <body> на том) ---
        if expected > 0 and len(raw_bodies) == expected:
            return [
                (b_lo + i, _body_title(bx, i + 1), bx)
                for i, bx in enumerate(raw_bodies)
            ]

        # --- Случай 2: один (или нестандартное количество) <body> ---
        # Объединяем все body, ищем top-level <section>
        all_content = '\n'.join(raw_bodies)
        top_sections = self._split_top_level_sections(all_content)

        if not top_sections:
            # Нет секций — возвращаем весь контент как один том
            title = (book.record.file_title or '').strip() or stem
            return [(b_lo, title, all_content)]

        # Regex для вырезания <title> из первой позиции внутри <section>.
        # Пример: <section>\n  <title><p>1. Книга I</p></title>\n  <p>текст...
        # После удаления: <section>\n  <p>текст...
        # Это предотвращает дублирование заголовка: наш <body><title> + оригинальный <section><title>.
        _SEC_TITLE_RE = re.compile(
            r'(<(?:fb:)?section(?:\s[^>]*)?>\s*)<(?:fb:)?title[^>]*>.*?</(?:fb:)?title>',
            re.IGNORECASE | re.DOTALL,
        )

        # Пробуем определить номера томов из содержимого секций
        detected: List[Tuple[Optional[int], str, str]] = []
        for i, sec_xml in enumerate(top_sections, 1):
            vol = self._detect_section_volume(sec_xml)
            raw_title = _body_title(sec_xml, i)
            # Убираем ведущий «N. » из заголовка секции — в _build_fb2 добавим свой индекс.
            # Без этого: "1. 1. Неудержимый. Книга I" вместо "1. Неудержимый. Книга I".
            title = re.sub(r'^\d+\.\s*', '', raw_title).strip() or raw_title
            # Вырезаем <title> из секции — он дублируется как <body><title> в итоговом файле.
            sec_clean = _SEC_TITLE_RE.sub(r'\1', sec_xml, count=1)
            detected.append((vol, title, f'<body>\n{sec_clean}\n</body>'))

        found_vols = [v for v, _, _ in detected if v is not None]
        use_detected = False
        if found_vols and expected > 0:
            in_range = sum(1 for v in found_vols if b_lo <= v <= b_hi)
            use_detected = in_range >= len(found_vols) * 0.7

        if use_detected:
            # Используем найденные номера; секции без номера пропускаем
            result = [
                (v, t, bx)
                for v, t, bx in detected
                if v is not None
            ]
            result.sort(key=lambda x: x[0])
            return result

        # Fallback: нумеруем секции последовательно с b_lo
        return [
            (b_lo + i, t, bx)
            for i, (_, t, bx) in enumerate(detected)
        ]

    def _extract_binaries(self, book: CompilationBook) -> List[str]:
        """Извлечь все <binary>...</binary> блоки из файла.

        Возвращает список XML-фрагментов, каждый — один <binary> блок.
        """
        if not book.abs_path.exists():
            return []
        try:
            text = self._read_file_text(book.abs_path)
        except Exception:
            return []
        return re.findall(
            r'<binary\b[^>]*>.*?</binary>',
            text, re.DOTALL | re.IGNORECASE,
        )

    def _extract_metadata(self, book: CompilationBook) -> dict:
        """Извлечь жанр из записи."""
        return {
            'genre': (book.record.metadata_genre or '').strip(),
        }

    def _build_fb2(
        self,
        author: str,
        series: str,
        volume_range: str,
        genre: str,
        bodies: List[Tuple[str, str]],
        binaries: Optional[List[str]] = None,
        part_count: int = 0,
    ) -> str:
        """Собрать итоговый FB2 XML из компонентов."""
        # Разбиваем автора на фамилию и имя
        parts = author.strip().split()
        last_name = _html.escape(parts[0]) if parts else ''
        first_name = _html.escape(' '.join(parts[1:])) if len(parts) > 1 else ''

        safe_series = _html.escape(series)
        n_books = len(bodies)
        suffix = self._series_suffix(n_books, volume_range, part_count)
        book_title = f"{safe_series} ({suffix})"

        # Жанр — берём первый, если несколько через запятую
        genre_tag = ''
        if genre:
            first_genre = genre.split(',')[0].strip()
            if first_genre:
                genre_tag = f'  <genre>{_html.escape(first_genre)}</genre>\n'
        if not genre_tag:
            genre_tag = '  <genre>other</genre>\n'

        # <sequence number> всегда содержит последовательный диапазон 1-N,
        # а не исходные номера томов из sort_key — иначе подсерии, чьи книги
        # пронумерованы 7 и 8 в родительской серии, ошибочно получали бы
        # number="7-8" вместо "1-2".
        seq_range = '1' if n_books == 1 else f'1-{n_books}'
        sequence_attr = f'name="{safe_series}" number="{seq_range}"'

        # Описание
        description = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"'
            ' xmlns:l="http://www.w3.org/1999/xlink">\n'
            '<description>\n'
            '<title-info>\n'
            f'{genre_tag}'
            f'<author>\n  <last-name>{last_name}</last-name>\n'
            f'  <first-name>{first_name}</first-name>\n</author>\n'
            f'<book-title>{book_title}</book-title>\n'
            f'<sequence {sequence_attr}/>\n'
            '</title-info>\n'
            '</description>\n'
        )

        # Тела книг — каждая книга в отдельном <body> с <title>
        body_parts = []
        for idx, (title, body_xml) in enumerate(bodies, 1):
            safe_title = _html.escape(title)
            # Снимаем ВСЕ <body>/<body name="..."> и </body> теги.
            # count=1 создавал вложенные <body> если исходник содержал несколько тел.
            body_content = re.sub(r'<(?:fb:)?body(?:\s[^>]*)?>',  '', body_xml, flags=re.IGNORECASE)
            body_content = re.sub(r'</(?:fb:)?body>',              '', body_content, flags=re.IGNORECASE)
            # Убираем <title>...</title> в первой секции (заменим своим)
            body_content = re.sub(
                r'^\s*<title>.*?</title>',
                '',
                body_content,
                count=1,
                flags=re.DOTALL | re.IGNORECASE
            )
            # Убираем явные namespace-префиксы fb: для совместимости
            body_content = re.sub(r'<fb:', '<', body_content)
            body_content = re.sub(r'</fb:', '</', body_content)

            body_parts.append(
                f'<body>\n'
                f'<title><p>{idx}. {safe_title}</p></title>\n'
                f'{body_content.strip()}\n'
                f'</body>'
            )

        binary_section = ('\n' + '\n'.join(binaries)) if binaries else ''
        return description + '\n'.join(body_parts) + binary_section + '\n</FictionBook>\n'

    # ------------------------------------------------------------------
    # Удаление исходников
    # ------------------------------------------------------------------

    def _delete_sources(self, paths: List[Path]) -> None:
        """Удалить исходные файлы после компиляции."""
        for path in paths:
            try:
                if path.exists():
                    path.unlink()
                    self._log(f"  🗑 Удалён исходник: {path.name}")
                # Удалить папку, если пуста
                parent = path.parent
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    self._log(f"  🗑 Удалена пустая папка: {parent.name}")
            except Exception as e:
                self._log(f"  ⚠ Не удалось удалить {path.name}: {e}")

    def delete_sources_for_result(self, result: CompilationResult) -> None:
        """Удалить исходники для уже выполненной компиляции (по подтверждению)."""
        if result.success:
            self._delete_sources(result.source_paths)
