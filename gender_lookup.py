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


class RateLimitError(Exception):
    """Genderize.io вернул HTTP 429 — суточный лимит исчерпан."""

# Состояния строки в NamesDialog
STATUS_PENDING   = 'pending'     # запрос отправлен
STATUS_FOUND     = 'found'       # ответ получен, пол определён
STATUS_UNCERTAIN = 'uncertain'   # ответ получен, вероятность ниже порога
STATUS_UNKNOWN   = 'unknown'     # сервис не знает этого имени
STATUS_ERROR     = 'error'       # ошибка сети
STATUS_RATE_LIMIT= 'rate_limit'  # превышен суточный лимит запросов (HTTP 429)


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

    def _worker(
        self,
        items: List[Tuple[int, str]],
        on_result: Callable,
        on_done: Callable,
    ) -> None:
        """Фоновый поток: для каждого автора отправляет ВСЕ его слова,
        затем выбирает то слово, для которого сервис вернул пол.
        """
        # Собираем уникальные слова по всем авторам, сохраняя маппинг
        # word_lower → список (row_idx, author)
        word_to_rows: Dict[str, List[Tuple[int, str]]] = {}
        all_words_order: List[str] = []  # для сохранения порядка запроса

        for row_idx, author in items:
            parts = [w for w in author.split() if w]
            for word in parts:
                key = word.lower()
                with self._lock:
                    cached = self._cache.get(key)
                if cached is not None:
                    # кеш-хит — сразу возвращаем (будет обработан в _pick_best ниже)
                    pass
                if key not in word_to_rows:
                    word_to_rows[key] = []
                    all_words_order.append(key)
                word_to_rows[key].append((row_idx, author))

        # Запросить у сервиса слова, которых нет в кеше
        words_to_fetch = [w for w in all_words_order
                          if self._cache.get(w) is None]

        rate_limited = False   # при 429 прекращаем дальнейшие запросы

        for i in range(0, len(words_to_fetch), BATCH_SIZE):
            if rate_limited:
                # Помечаем оставшиеся слова как rate_limit
                for key in words_to_fetch[i:]:
                    with self._lock:
                        self._cache[key] = LookupResult(
                            status=STATUS_RATE_LIMIT,
                            error='HTTP 429: суточный лимит запросов исчерпан',
                        )
                break

            chunk_keys = words_to_fetch[i:i + BATCH_SIZE]
            # Оригинальный регистр для запроса (берём из первого вхождения)
            orig_words = {k: k for k in chunk_keys}  # ключ = lower
            # Восстанавливаем оригинальный регистр
            for row_idx, author in items:
                for w in author.split():
                    if w.lower() in orig_words:
                        orig_words[w.lower()] = w

            try:
                batch_results = self._genderize_batch(list(orig_words.values()))
            except RateLimitError as exc:
                rate_limited = True
                rl_result = LookupResult(status=STATUS_RATE_LIMIT, error=str(exc))
                for key in chunk_keys:
                    with self._lock:
                        self._cache[key] = rl_result
                continue
            except Exception as exc:
                err_result = LookupResult(status=STATUS_ERROR, error=str(exc))
                for key in chunk_keys:
                    with self._lock:
                        self._cache[key] = err_result
                continue

            for key, result in batch_results.items():
                with self._lock:
                    self._cache[key] = result

        # Теперь для каждого row_idx перебираем слова автора и выбираем
        # лучший результат (наивысший probability с known gender)
        for row_idx, author in items:
            parts = [w for w in author.split() if w]
            best_word: Optional[str] = None
            best_result: Optional['LookupResult'] = None

            for word in parts:
                key = word.lower()
                with self._lock:
                    r = self._cache.get(key)
                if r is None:
                    continue
                if r.status == STATUS_ERROR:
                    # Ошибка сети — запоминаем, но продолжаем искать
                    if best_result is None:
                        best_word, best_result = word, r
                    continue
                if r.status == STATUS_RATE_LIMIT:
                    # Превышен лимит — ставим этот статус и не ищем дальше
                    best_word, best_result = word, r
                    break
                if r.status == STATUS_UNKNOWN:
                    if best_result is None:
                        best_word, best_result = word, r
                    continue
                # found / uncertain: выбираем с наивысшей вероятностью
                if (best_result is None
                        or best_result.status not in (STATUS_FOUND, STATUS_UNCERTAIN)
                        or r.probability > best_result.probability):
                    best_word, best_result = word, r

            if best_word is None:
                best_word  = parts[0] if parts else ''
                best_result = LookupResult(status=STATUS_UNKNOWN)

            try:
                on_result(row_idx, best_word, best_result)
            except Exception:
                pass

        try:
            on_done(rate_limited)
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
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimitError(
                    'Суточный лимит запросов Genderize.io исчерпан. '
                    'Добавьте бесплатный API-ключ в Настройки → Общие '
                    '(1000 запросов/день вместо 100).'
                ) from exc
            raise

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
