"""Сервис сканирования FB2-файлов для извлечения жанров."""
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from fb2_utils import fb2_rglob
    from fb2_author_extractor import FB2AuthorExtractor
except ImportError:
    from .fb2_utils import fb2_rglob
    from .fb2_author_extractor import FB2AuthorExtractor


def scan_fb2_genres(
    folder_path: Path,
    config_path: str,
    on_progress: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """Извлечь жанры из всех FB2-файлов в папке.

    Args:
        folder_path: путь к папке с FB2-файлами.
        config_path: путь к config.json для FB2AuthorExtractor.
        on_progress: callback(done, total, pct) — каждые 20 файлов.

    Returns:
        dict с ключами:
            results  — {genre_combo: [relative_path, ...]}
            errors   — [error_str, ...]
            total    — общее число файлов
    """
    extractor = FB2AuthorExtractor(config_path)
    results: Dict[str, List[str]] = {}
    errors: List[str] = []
    fb2_files = fb2_rglob(folder_path)
    total = len(fb2_files)

    for idx, fb2_file in enumerate(fb2_files, 1):
        try:
            genre_str = extractor._extract_genres_from_fb2(fb2_file)
            key = genre_str.strip() if genre_str and genre_str.strip() else 'Не определено'
            try:
                rel_path = str(fb2_file.relative_to(folder_path))
            except ValueError:
                rel_path = str(fb2_file)
            results.setdefault(key, []).append(rel_path)
        except Exception as e:
            errors.append(f'{fb2_file.name}: {e}')

        if on_progress and (idx % 20 == 0 or idx == total):
            on_progress(idx, total, int(idx * 100 / total) if total else 100)

    return {'results': results, 'errors': errors, 'total': total}
