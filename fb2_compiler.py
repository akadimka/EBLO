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
from dataclasses import dataclass
from pathlib import Path
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

    # Regex для извлечения числа из начала stem: "1. Название", "02 - Название", "3 Название"
    _STEM_NUM_RE = re.compile(
        r'^(\d{1,4})\s*[.\-–—_)]\s*|\s+(\d{1,4})\s*[.\-–—_)]\s', re.UNICODE
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
    def _series_suffix(cls, book_count: int, volume_range: str) -> str:
        """Вернуть суффикс для имени файла компиляции.

        Служебное слово (Дилогия, Трилогия…) присваивается ТОЛЬКО если:
          1. Диапазон начинается с тома 1 (нумерация с начала серии).
          2. Количество томов ≤ 10 (есть подходящее слово).
        Во всех остальных случаях: «т. X-Y».
        Пустой volume_range → «компиляция романов».

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
            return cls._SERIES_WORDS[n]
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
        # Группировка по (author_lower, series_lower)
        buckets: Dict[Tuple[str, str], List] = {}
        for rec in records:
            author = (rec.proposed_author or '').strip()
            series = (rec.proposed_series or '').strip()
            if not author or not series:
                continue
            key = (author.lower(), series.lower())
            buckets.setdefault(key, []).append(rec)

        groups: List[CompilationGroup] = []
        for (_, _), recs in buckets.items():
            if len(recs) < 2:
                continue
            # Используем реальное написание из первой записи
            author = recs[0].proposed_author.strip()
            series = recs[0].proposed_series.strip()

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
            for book in books:
                lo, hi = self._precompiled_range(book, series)
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
                # покрыт «лучшей» предкомпиляцией. Если не покрыт (например "1-2" + "3-4"
                # — непересекающиеся диапазоны) — они нужны как источники, не дубликаты.
                other_precompiled: List[Tuple] = []
                for entry in precompiled:
                    book, lo, hi = entry
                    if book is best_pre:
                        continue
                    if best_lo <= lo and hi <= best_hi:
                        # Полностью покрыта лучшей → дубликат
                        duplicate_paths.append(book.abs_path)
                    else:
                        # Не покрыта → сохраняем как источник
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

                    pre_covered_individually = all(
                        any(_vol_num(r) == v for r in regular_books)
                        for v in range(best_lo, best_hi + 1)
                    )

                    if pre_covered_individually:
                        # 3. ПОЛНОСТЬЮ УСТАРЕЛА — все её тома есть по отдельности
                        duplicate_paths.append(best_pre.abs_path)
                        books = regular_books
                    else:
                        # 2. ЧАСТИЧНО УСТАРЕЛА — включаем предкомпиляцию как источник,
                        # тома, уже покрытые ею, помечаем как дубликаты
                        covered_individually = [
                            r for r in regular_books
                            if (n := _vol_num(r)) is not None and best_lo <= n <= best_hi
                        ]
                        for r in covered_individually:
                            duplicate_paths.append(r.abs_path)
                        remaining = [r for r in regular_books if r not in covered_individually]
                        books = [best_pre] + remaining

                    # Добавляем прочие предкомпиляции с непересекающимися диапазонами
                    # как дополнительные источники (они уже НЕ в duplicate_paths).
                    for other_book, other_lo, other_hi in other_precompiled:
                        # Проверяем: все тома этой предкомпиляции уже есть отдельно?
                        other_fully_individual = all(
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
                title_key = self._normalize_title_key(
                    book.record.file_title or book.abs_path.stem, series
                )
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

            if len(books) < 2:
                # Даже если группа не идёт на компиляцию, дубликаты запомняем для удаления
                # (но они будут обработаны отдельно, если потребуется)
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

                first_group = True  # для назначения duplicate_paths только один раз

                # ── Числовые книги: непрерывные блоки ──────────────────────
                valid_runs = [r for r in self._split_into_consecutive_runs(numeric) if len(r) >= 2]
                lone_numeric = [b for r in self._split_into_consecutive_runs(numeric) if len(r) < 2 for b in r]

                for run in valid_runs:
                    run_range = self._compute_volume_range(run)
                    groups.append(CompilationGroup(
                        author=author,
                        series=series,
                        books=run,
                        order_determined=True,
                        volume_range=run_range,
                        duplicate_paths=duplicate_paths if first_group else [],
                        alphabetical_order=False,
                    ))
                    first_group = False

                # ── Нечисловые книги: компиляция по году / по названию ─────
                # Если нечисловых >= 2 — обычная группа
                # Если нечисловых < 2, но есть одиночные числовые книги — объединяем всё вместе
                all_others = others
                if len(others) < 2 and lone_numeric:
                    # Объединяем одиночные числовые + нечисловые в смешанную группу
                    all_others = sorted(lone_numeric, key=lambda b: b.sort_key) + list(others)
                    lone_numeric = []

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

    @classmethod
    def _extract_inline_volume_number(cls, title: str, stem: str) -> Optional[int]:
        """Извлечь номер тома из ключевых слов внутри названия.

        Ищет паттерны «Свиток 1», «Том 3», «Книга 2», «Часть 4» и т.п.
        Возвращает число или None, если паттерн не найден.

        Проверяет как file_title, так и stem файла.
        """
        for text in (title, stem):
            if not text:
                continue
            m = cls._VOLUME_KEYWORDS_RE.search(text)
            if m:
                return int(m.group(1))
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

        def _has_series_link(txt: str) -> bool:
            tl = txt.lower()
            return not series_words or any(w in tl for w in series_words)

        # Критерий 1: диапазон "N-M" в имени файла (stem) или title — приоритет выше метаданных
        # Имя файла отражает реальную организацию библиотеки, метаданные могут быть неточными.
        _RANGE_RE = re.compile(r'(\d+)\s*[-–—]\s*(\d+)', re.UNICODE)
        for candidate in (book.abs_path.stem, book.record.file_title or ''):
            if not _has_series_link(candidate):
                continue
            m = _RANGE_RE.search(candidate)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if hi > lo:
                    return lo, hi

        # Критерий 2: series_number — диапазон "N-M" из метаданных (запасной вариант)
        sn = (book.record.series_number or '').strip()
        if sn:
            m = re.match(r'^(\d+)\s*[-–—]\s*(\d+)$', sn)
            if m:
                lo, hi = int(m.group(1)), int(m.group(2))
                if hi > lo:
                    return lo, hi

        # Критерий 3: stem/title содержит сервисное слово + признак серии
        text = (book.record.file_title or book.abs_path.stem).lower()
        for idx, kw in enumerate(self._SERIES_WORDS):
            if kw and kw.lower() in text:
                if _has_series_link(text):
                    return 1, idx  # сервисное слово → предполагаем lo=1

        return 0, 0

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
        """
        key = raw_title.strip().lower()
        # Попробовать отрезать префикс вида "<серия>. " или "<серия> "
        series_prefix = series.strip().lower()
        for sep in ('. ', ' '):
            candidate = series_prefix + sep
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
                if re.match(r'^\d+$', sn):
                    return (0, int(sn), 0), 'series_number', False, sn
                rng = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', sn)
                if rng:
                    return (0, int(rng.group(1)), 0), 'series_number', False, sn

        # Источник Б: число в начале имени файла
        num_m = self._STEM_NUM_RE.match(stem) or re.search(
            r'(?:^|[-–\s])(\d{1,4})\.\s+[А-ЯЁA-Z]', stem
        )
        if num_m:
            num = int(next(g for g in num_m.groups() if g is not None))
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
        inline = self._extract_inline_volume_number(
            rec.file_title or stem, stem
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
            return (3, year, 0), 'publish_date', False

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
        верхней границе: следующий файл с lo == hi+1 считается непрерывным.
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
            if lo == prev_hi + 1:
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
        return str(lo) if lo == hi else f'{lo}-{hi}'

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
            # --- Читаем содержимое каждого файла ---
            bodies: List[Tuple[str, str]] = []  # (book_title, body_xml)
            for book in group.books:
                title, body_xml = self._extract_body(book)
                if body_xml is None:
                    raise RuntimeError(
                        f"Не удалось извлечь <body> из: {book.abs_path.name}"
                    )
                bodies.append((title, body_xml))

            # --- Извлекаем метаданные из первой (или лучшей) книги ---
            meta = self._extract_metadata(group.books[0])

            # --- Имя выходного файла и clean_series ---
            clean_series = self._clean_series_name(group.series)
            safe_author = re.sub(r'[\\/:*?"<>|]', '_', group.author)
            safe_series = re.sub(r'[\\/:*?"<>|]', '_', clean_series)

            # --- Папка назначения: явная или рядом с исходниками ---
            dest_dir = output_dir if output_dir is not None else group.books[0].abs_path.parent

            # --- Папка назначения: явная или рядом с исходниками ---
            if output_dir is None:
                dest_dir = group.books[0].abs_path.parent
            else:
                dest_dir = output_dir

            # --- Собираем итоговый XML ---
            volume_range = group.volume_range or self._compute_volume_range(group.books)
            output_xml = self._build_fb2(
                author=group.author,
                series=clean_series,
                volume_range=volume_range,
                genre=meta.get('genre', ''),
                bodies=bodies,
            )

            # --- Имя выходного файла ---
            suffix = self._series_suffix(len(group.books), volume_range)
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
        """Извлечь заголовок книги и все <body>...</body> блоки."""
        title = (book.record.file_title or '').strip() or book.abs_path.stem

        if not book.abs_path.exists():
            self._log(f"  ⚠ Файл не найден: {book.abs_path}")
            return title, None

        try:
            text = self._read_file_text(book.abs_path)
        except Exception as e:
            self._log(f"  ⚠ Ошибка чтения {book.abs_path.name}: {e}")
            return title, None

        # Находим все <body> блоки (может быть несколько — notes и т.д.)
        bodies = re.findall(
            r'<(?:fb:)?body(?:\s[^>]*)?>.*?</(?:fb:)?body>',
            text, re.DOTALL | re.IGNORECASE
        )
        if not bodies:
            return title, None

        # Объединяем в один блок, первый получает наш заголовок книги
        combined = '\n'.join(bodies)
        return title, combined

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
    ) -> str:
        """Собрать итоговый FB2 XML из компонентов."""
        # Разбиваем автора на фамилию и имя
        parts = author.strip().split()
        last_name = _html.escape(parts[0]) if parts else ''
        first_name = _html.escape(' '.join(parts[1:])) if len(parts) > 1 else ''

        safe_series = _html.escape(series)
        n_books = len(bodies)
        suffix = self._series_suffix(n_books, volume_range)
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
            # Убираем любой существующий <title> из первого body
            body_content = re.sub(
                r'<(?:fb:)?body(?:\s[^>]*)?>',
                '',
                body_xml,
                count=1,
                flags=re.IGNORECASE
            )
            body_content = re.sub(
                r'</(?:fb:)?body>',
                '',
                body_content,
                count=1,
                flags=re.IGNORECASE
            )
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

        return description + '\n'.join(body_parts) + '\n</FictionBook>\n'

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
