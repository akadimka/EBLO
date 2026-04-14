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


@dataclass
class CompilationGroup:
    """Группа файлов для компиляции."""
    author: str
    series: str
    books: List[CompilationBook]
    order_determined: bool  # False если хотя бы у одной книги ambiguous
    volume_range: str       # "1-7" или ""


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

        - 2..10 книг: используем сервисное слово (Дилогия, Трилогия…)
        - больше 10: «т. 1-17»
        - если volume_range пустой: просто «Сборник»
        """
        if not volume_range:
            return 'Сборник'
        n = book_count
        if 2 <= n < len(cls._SERIES_WORDS) and cls._SERIES_WORDS[n]:
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
            books_sorted, order_determined = self._sort_books(books)

            volume_range = self._compute_volume_range(books_sorted) if order_determined else ''

            groups.append(CompilationGroup(
                author=author,
                series=series,
                books=books_sorted,
                order_determined=order_determined,
                volume_range=volume_range,
            ))

        groups.sort(key=lambda g: (g.author.lower(), g.series.lower()))
        self._log(f"Найдено групп для компиляции: {len(groups)}")
        return groups

    def _make_book(self, rec, work_dir: Path) -> CompilationBook:
        """Создать CompilationBook из BookRecord."""
        abs_path = work_dir / rec.file_path
        sort_key, sort_source, ambiguous = self._determine_sort_key(rec, abs_path)
        return CompilationBook(
            record=rec,
            abs_path=abs_path,
            sort_key=sort_key,
            sort_source=sort_source,
            order_ambiguous=ambiguous,
        )

    def _determine_sort_key(
        self, rec, abs_path: Path
    ) -> Tuple[Tuple, str, bool]:
        """Многоуровневое определение порядка книги.

        Returns:
            (sort_key_tuple, source_name, is_ambiguous)
        """
        # Уровень 1: series_number — целое число или диапазон «1-4» (компиляция)
        sn = (rec.series_number or '').strip()
        if sn:
            if re.match(r'^\d+$', sn):
                return (0, int(sn), 0), 'series_number', False
            rng = re.match(r'^(\d+)\s*[-–]\s*(\d+)$', sn)
            if rng:
                # Для компиляции используем MIN для сортировки
                return (0, int(rng.group(1)), 0), 'series_number', False

        # Уровень 2: число в начале имени файла
        stem = Path(rec.file_path).stem
        num_m = self._STEM_NUM_RE.match(stem) or re.search(
            r'(?:^|[-–\s])(\d{1,4})\.\s+[А-ЯЁA-Z]', stem
        )
        if num_m:
            num = int(next(g for g in num_m.groups() if g is not None))
            return (1, num, 0), 'filename', False

        # Уровень 3: дата из FB2 title-info
        year = self._extract_year_from_fb2(abs_path, section='title-info')
        if year:
            return (2, year, 0), 'title_date', False

        # Уровень 4: дата из publish-info
        year = self._extract_year_from_fb2(abs_path, section='publish-info')
        if year:
            return (3, year, 0), 'publish_date', False

        # Порядок не определён
        return (9, 0, 0), 'unknown', True

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

    def _sort_books(
        self, books: List[CompilationBook]
    ) -> Tuple[List[CompilationBook], bool]:
        """Отсортировать книги и определить, однозначен ли порядок."""
        has_ambiguous = any(b.order_ambiguous for b in books)
        # Сортируем всех — даже при наличии неопределённых, чтобы
        # known идут первыми по sort_key, unknown — в конец
        sorted_books = sorted(books, key=lambda b: b.sort_key)
        return sorted_books, not has_ambiguous

    def _compute_volume_range(self, books: List[CompilationBook]) -> str:
        """Вернуть строку диапазона томов, например '1-7'."""
        nums = []
        for b in books:
            level = b.sort_key[0]
            val = b.sort_key[1]
            if level <= 1 and isinstance(val, int):
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
        output_dir: Path,
        delete_sources: bool = False,
    ) -> CompilationResult:
        """Скомпилировать группу в один FB2-файл.

        Args:
            group: Группа книг для компиляции.
            output_dir: Папка, куда поместить результирующий файл.
            delete_sources: Удалить исходники после успешной компиляции.

        Returns:
            CompilationResult с результатами.
        """
        self._log(f"Компиляция: {group.author} / {group.series} ({len(group.books)} книг)")

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

            output_path = output_dir / fname
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output_xml, encoding='utf-8')

            self._log(f"  ✓ Создан файл: {output_path.name}")

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
        safe_series_range = _html.escape(volume_range) if volume_range else ''
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

        sequence_attr = f'name="{safe_series}"'
        if volume_range:
            sequence_attr += f' number="{safe_series_range}"'

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
