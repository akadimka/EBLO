#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Онлайн-определение пола по имени через Genderize.io.

Особенности:
- Батчевые запросы (до 10 имён за раз)
- In-memory кеш (повторные запросы ничего не стоят)
- Полностью асинхронный: не блокирует UI
- Работает с Кириллицей: имя берётся из исходного автора (не из ответа сервиса),
  сервис определяет только ПОЛ, а не транслитерирует имя

Зеркало логики определения:
  "Жозе Агуалуза" → запрашиваем "Жозе" → сервис отвечает gender=male
  → в поле Name пишем "Жозе" (наш Кириллический вариант), не "José"
"""

import urllib.request
import urllib.parse
import json
import threading
from typing import Dict, List, Tuple, Callable, Optional

# ── Константы ────────────────────────────────────────────────────────────────
GENDERIZE_URL   = "https://api.genderize.io"
BATCH_SIZE      = 10      # лимит Genderize.io за один запрос
DEFAULT_TIMEOUT = 8       # секунд
MIN_PROBABILITY = 0.75    # ниже — считаем ненадёжным (но всё равно заполняем)

_GENDER_RU = {'male': 'Муж.', 'female': 'Жен.'}

# Состояния строки в NamesDialog
STATUS_PENDING  = 'pending'   # запрос отправлен
STATUS_FOUND    = 'found'     # ответ получен, пол определён
STATUS_UNCERTAIN= 'uncertain' # ответ получен, вероятность ниже порога
STATUS_UNKNOWN  = 'unknown'   # сервис не знает этого имени
STATUS_ERROR    = 'error'     # ошибка сети / исчерпан лимит


class LookupResult:
    """Результат определения пола для одного имени."""

    __slots__ = ('gender_ru', 'probability', 'status', 'error')

    def __init__(
        self,
        gender_ru: Optional[str] = None,
        probability: float = 0.0,
        status: str = STATUS_UNKNOWN,
        error: str = '',
    ):
        self.gender_ru   = gender_ru    # 'Муж.' | 'Жен.' | None
        self.probability = probability  # 0.0–1.0
        self.status      = status       # одна из STATUS_* констант
        self.error       = error        # сообщение об ошибке


class GenderLookupService:
    """Потокобезопасный батчевый сервис определения пола через Genderize.io.

    Один экземпляр на приложение — кеш накапливается между вызовами.
    """

    def __init__(self, api_key: str = '', timeout: int = DEFAULT_TIMEOUT):
        self._api_key  = api_key.strip()
        self._timeout  = timeout
        self._cache: Dict[str, LookupResult] = {}
        self._lock = threading.Lock()

    # ── Публичный API ─────────────────────────────────────────────────────────

    def lookup_authors_async(
        self,
        items: List[Tuple[int, str]],       # (row_index, author_string)
        on_result: Callable[[int, str, 'LookupResult'], None],
        on_done:   Callable[[], None],
    ) -> None:
        """Запустить асинхронный lookup.

        Вызывает on_result(row_idx, name_word, result) для каждого автора.
        name_word — слово из оригинального кириллического автора, которое
        было отправлено на проверку (его и надо писать в поле Name).

        on_done() вызывается когда все запросы завершены.
        """
        t = threading.Thread(
            target=self._worker,
            args=(items, on_result, on_done),
            daemon=True,
        )
        t.start()

    # ── Внутренние методы ────────────────────────────────────────────────────

    @staticmethod
    def pick_name_word(author: str) -> str:
        """Выбрать слово для запроса из строки автора.

        Соглашение: "Фамилия Имя" → word[1].
        Для однословных → word[0].
        """
        parts = author.split()
        if not parts:
            return ''
        return parts[1] if len(parts) >= 2 else parts[0]

    def _worker(
        self,
        items: List[Tuple[int, str]],
        on_result: Callable,
        on_done: Callable,
    ) -> None:
        """Фоновый поток: отдаёт кеш-хиты и батчами запрашивает остальное."""
        pending: List[Tuple[int, str, str]] = []  # (idx, author, name_word)

        # Кеш-хиты
        for row_idx, author in items:
            name_word = self.pick_name_word(author)
            if not name_word:
                continue
            key = name_word.lower()
            with self._lock:
                cached = self._cache.get(key)
            if cached is not None:
                try:
                    on_result(row_idx, name_word, cached)
                except Exception:
                    pass
            else:
                pending.append((row_idx, author, name_word))

        # Батчевые запросы к Genderize.io
        for i in range(0, len(pending), BATCH_SIZE):
            chunk = pending[i:i + BATCH_SIZE]
            names = [w for _, _, w in chunk]

            try:
                batch_results = self._genderize_batch(names)
            except Exception as exc:
                err_result = LookupResult(status=STATUS_ERROR, error=str(exc))
                for row_idx, _, name_word in chunk:
                    with self._lock:
                        self._cache[name_word.lower()] = err_result
                    try:
                        on_result(row_idx, name_word, err_result)
                    except Exception:
                        pass
                continue

            for row_idx, _, name_word in chunk:
                result = batch_results.get(
                    name_word.lower(),
                    LookupResult(status=STATUS_UNKNOWN),
                )
                with self._lock:
                    self._cache[name_word.lower()] = result
                try:
                    on_result(row_idx, name_word, result)
                except Exception:
                    pass

        try:
            on_done()
        except Exception:
            pass

    def _genderize_batch(self, names: List[str]) -> Dict[str, 'LookupResult']:
        """Запрос к Genderize.io — до BATCH_SIZE имён."""
        params = [('name[]', n) for n in names]
        if self._api_key:
            params.append(('apikey', self._api_key))
        url = GENDERIZE_URL + '?' + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'EBookLibraryOrganizer/1.0'},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        if not isinstance(data, list):
            data = [data]

        results: Dict[str, LookupResult] = {}
        for item in data:
            raw_name = item.get('name', '')
            gender   = item.get('gender')         # 'male' | 'female' | None
            prob     = float(item.get('probability') or 0.0)
            count    = int(item.get('count') or 0)
            key      = raw_name.lower()

            if count == 0 or gender is None:
                results[key] = LookupResult(status=STATUS_UNKNOWN)
            else:
                status = STATUS_FOUND if prob >= MIN_PROBABILITY else STATUS_UNCERTAIN
                results[key] = LookupResult(
                    gender_ru   = _GENDER_RU.get(gender),
                    probability = prob,
                    status      = status,
                )
        return results
