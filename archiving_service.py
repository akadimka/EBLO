"""Сервис архивации FB2-файлов в формат .fb2.zip."""
import zipfile
from pathlib import Path
from typing import Callable, List, Optional


def archive_fb2_files(
    fb2_files: List[Path],
    on_progress: Optional[Callable[[int, int, int], None]] = None,
) -> dict:
    """Упаковать каждый FB2-файл в ZIP, удалить оригинал.

    Args:
        fb2_files: список Path к .fb2 файлам.
        on_progress: callback(done, total, pct) — вызывается каждые 50 файлов.

    Returns:
        dict с ключами: done, total, errors, size_before, size_after.
    """
    done = 0
    errors: List[str] = []
    total = len(fb2_files)
    size_before = 0
    size_after = 0

    for idx, fb2_path in enumerate(fb2_files, 1):
        try:
            fb2_size = fb2_path.stat().st_size
            zip_path = fb2_path.with_name(fb2_path.name + '.zip')
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
                zf.write(fb2_path, arcname=fb2_path.name)
            zip_size = zip_path.stat().st_size
            fb2_path.unlink()
            done += 1
            size_before += fb2_size
            size_after += zip_size
        except Exception as e:
            errors.append(f'{fb2_path.name}: {e}')

        if on_progress and (idx % 50 == 0 or idx == total):
            on_progress(idx, total, int(idx * 100 / total))

    return {
        'done': done,
        'total': total,
        'errors': errors,
        'size_before': size_before,
        'size_after': size_after,
    }
