#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Онлайн-определение пола автора.

Цепочка источников (каскад):
  1. Genderize.io  — быстро, батчами по 10 слов
  2. Wikidata SPARQL — при 429 или unknown от Genderize.io,
                       последовательно, 1 запрос/секунду

Кеш:
  Общий in-memory кеш на всю сессию. Один раз найденное слово больше не
  запрашивается ни в одном из источников.

Имя:
  Запрашиваем слова из кириллической строки автора (все слова).
  Возвращаем то кириллическое слово, которое было распознано как имя.
  Сервис определяет только ПОЛ — транслитерации не происходит.
"""

import time
import urllib.request
import urllib.parse
import json
import threading
from typing import Dict, List, Tuple, Callable, Optional

# ── Константы ────────────────────────────────────────────────────────────────
GENDERIZE_URL     = "https://api.genderize.io"
WIKIDATA_API_URL  = "https://www.wikidata.org/w/api.php"
BATCH_SIZE        = 10      # лимит Genderize.io за один запрос
DEFAULT_TIMEOUT   = 10      # секунд
MIN_PROBABILITY   = 0.75    # (Genderize) ниже — uncertain
WIKIDATA_DELAY    = 1.1     # секунд между Wikidata-запросами (политика сервиса)

_GENDER_RU = {'male': 'Муж.', 'female': 'Жен.'}

# ── Статусы строки в NamesDialog ─────────────────────────────────────────────
STATUS_PENDING    = 'pending'      # запрос отправлен
STATUS_FOUND      = 'found'        # пол определён уверенно
STATUS_UNCERTAIN  = 'uncertain'    # пол определён, вероятность < MIN_PROBABILITY
STATUS_UNKNOWN    = 'unknown'      # все источники: имя не найдено
STATUS_ERROR      = 'error'        # ошибка сети/парсинга
STATUS_RATE_LIMIT = 'rate_limit'   # HTTP 429 от Genderize.io


class RateLimitError(Exception):
    """Genderize.io вернул HTTP 429 — суточный лимит исчерпан."""


# ── Результат ─────────────────────────────────────────────────────────────────

class LookupResult:
    """Результат определения пола для одного слова."""

    __slots__ = ('gender_ru', 'probability', 'status', 'error', 'source')

    def __init__(
        self,
        gender_ru: Optional[str] = None,
        probability: float = 0.0,
        status: str = STATUS_UNKNOWN,
        error: str = '',
        source: str = '',          # 'genderize' | 'wikidata' | ''
    ):
        self.gender_ru   = gender_ru
        self.probability = probability
        self.status      = status
        self.error       = error
        self.source      = source


# ── Основной сервис ───────────────────────────────────────────────────────────

class GenderLookupService:
    """Двухуровневый потокобезопасный сервис определения пола.

    Уровень 1: Genderize.io  (батчи по 10, быстро)
    Уровень 2: Wikidata SPARQL (последовательно, 1 req/sec, fallback)

    Один экземпляр на приложение — кеш общий для обоих источников.
    """

    def __init__(self, api_key: str = '', timeout: int = DEFAULT_TIMEOUT):
        self._api_key    = api_key.strip()
        self._timeout    = timeout
        self._cache: Dict[str, LookupResult] = {}
        self._lock       = threading.Lock()
        self._wd_lock    = threading.Lock()  # сериализует Wikidata-запросы
        self._last_wd_ts = 0.0              # время последнего Wikidata-запроса

    # ── Публичный API ─────────────────────────────────────────────────────────

    def lookup_authors_async(
        self,
        items: List[Tuple[int, str]],
        on_result: Callable[[int, str, 'LookupResult'], None],
        on_done:   Callable[[bool], None],
    ) -> None:
        """Асинхронный lookup (не блокирует UI).

        on_result(row_idx, name_word, result) — для каждого автора.
        on_done(rate_limited) — когда все проверки завершены.
        """
        threading.Thread(
            target=self._worker,
            args=(items, on_result, on_done),
            daemon=True,
        ).start()

    # ── Рабочий поток ────────────────────────────────────────────────────────

    def _worker(self, items, on_result, on_done):
        """Двухфазный поиск: Genderize → Wikidata fallback."""

        # ── Фаза 1: Genderize.io (батчи) ────────────────────────────────────
        rate_limited = False

        # Собрать уникальные слова и их оригинальный регистр
        word_orig: Dict[str, str] = {}   # lower → original
        all_keys_ordered: List[str] = []
        for _, author in items:
            for w in author.split():
                k = w.lower()
                if k not in word_orig:
                    word_orig[k] = w
                    all_keys_ordered.append(k)

        keys_to_fetch = [k for k in all_keys_ordered
                         if not self._in_cache(k)]

        for i in range(0, len(keys_to_fetch), BATCH_SIZE):
            if rate_limited:
                for k in keys_to_fetch[i:]:
                    self._set_cache(k, LookupResult(
                        status=STATUS_RATE_LIMIT,
                        error='HTTP 429',
                    ))
                break

            chunk = keys_to_fetch[i:i + BATCH_SIZE]
            orig_names = [word_orig[k] for k in chunk]
            try:
                results = self._genderize_batch(orig_names)
                for k, r in results.items():
                    self._set_cache(k, r)
            except RateLimitError:
                rate_limited = True
                rl = LookupResult(status=STATUS_RATE_LIMIT,
                                  error='HTTP 429')
                for k in chunk:
                    self._set_cache(k, rl)
            except Exception as exc:
                err = LookupResult(status=STATUS_ERROR, error=str(exc))
                for k in chunk:
                    self._set_cache(k, err)

        # ── Фаза 2: Wikidata SPARQL (последовательно, для unknown/rate_limit) ─
        # Проходим по авторам целиком — Wikidata ищет по полному имени,
        # не по отдельным словам
        wikidata_items: List[Tuple[int, str]] = []
        for row_idx, author in items:
            # Быстро проверяем: есть ли в кеше хороший результат?
            best = self._pick_best_from_cache(author)
            if best is not None and best.status in (STATUS_FOUND, STATUS_UNCERTAIN):
                continue   # Genderize уже дал хороший ответ
            if best is not None and best.status == STATUS_ERROR:
                continue   # сетевая ошибка — Wikidata вряд ли поможет
            # unknown, rate_limit, или ничего → пробуем Wikidata
            wikidata_items.append((row_idx, author))

        for row_idx, author in wikidata_items:
            wd_key = '_wd_' + author.lower()
            if not self._in_cache(wd_key):
                self._throttle_wikidata()
                try:
                    r = self._wikidata_lookup(author)
                except Exception as exc:
                    r = LookupResult(status=STATUS_ERROR, error=str(exc))
                self._set_cache(wd_key, r)

        # ── Итоговый выбор для каждого автора ───────────────────────────────
        for row_idx, author in items:
            best_word, best_result = self._select_result(author)
            try:
                on_result(row_idx, best_word, best_result)
            except Exception:
                pass

        try:
            on_done(rate_limited)
        except Exception:
            pass

    # ── Genderize.io ─────────────────────────────────────────────────────────

    def _genderize_batch(self, names: List[str]) -> Dict[str, 'LookupResult']:
        """Один батч-запрос к Genderize.io."""
        params = [('name[]', n) for n in names]
        if self._api_key:
            params.append(('apikey', self._api_key))
        url = GENDERIZE_URL + '?' + urllib.parse.urlencode(params)

        req = urllib.request.Request(
            url, headers={'User-Agent': 'EBookLibraryOrganizer/1.0'},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise RateLimitError(
                    'Суточный лимит Genderize.io исчерпан. '
                    'Добавьте API-ключ в Настройки → Общие '
                    '(genderize.io, бесплатно, 1000 запросов/день).'
                ) from exc
            raise

        if not isinstance(data, list):
            data = [data]

        out: Dict[str, LookupResult] = {}
        for item in data:
            raw   = item.get('name', '')
            gender = item.get('gender')
            prob   = float(item.get('probability') or 0.0)
            count  = int(item.get('count') or 0)
            key    = raw.lower()
            if count == 0 or gender is None:
                out[key] = LookupResult(status=STATUS_UNKNOWN, source='genderize')
            else:
                status = STATUS_FOUND if prob >= MIN_PROBABILITY else STATUS_UNCERTAIN
                out[key] = LookupResult(
                    gender_ru=_GENDER_RU.get(gender),
                    probability=prob,
                    status=status,
                    source='genderize',
                )
        return out

    # ── Wikidata SPARQL ───────────────────────────────────────────────────────

    def _throttle_wikidata(self) -> None:
        """Соблюдать паузу между запросами к Wikidata (≥ WIKIDATA_DELAY сек)."""
        with self._wd_lock:
            elapsed = time.monotonic() - self._last_wd_ts
            wait = WIKIDATA_DELAY - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_wd_ts = time.monotonic()

    def _wikidata_lookup(self, author: str) -> 'LookupResult':
        """Wikidata MediaWiki API: ищем человека по имени, возвращаем пол.

        Шаг 1: wbsearchentities — текстовый поиск по индексу (быстро, 1 запрос)
        Шаг 2: wbgetentities    — получить P31/P21 claims для кандидатов (1 запрос)

        Только сущности типа Q5 (человек) с P21 (пол) принимаются во внимание.
        Кандидаты проверяются в том порядке, в котором их вернул поиск.
        """
        _UA     = 'EBookLibraryOrganizer/1.0 (github.com/akadimka/EBLO)'
        _MALE   = {'Q6581097', 'Q44148', 'Q2443246'}
        _FEMALE = {'Q6581072', 'Q2449503', 'Q1052281'}

        # Шаг 1: текстовый поиск сущностей по имени автора
        params1 = urllib.parse.urlencode({
            'action':   'wbsearchentities',
            'search':   author,
            'language': 'ru',
            'type':     'item',
            'limit':    '5',
            'format':   'json',
        })
        req1 = urllib.request.Request(
            WIKIDATA_API_URL + '?' + params1,
            headers={'User-Agent': _UA},
        )
        with urllib.request.urlopen(req1, timeout=self._timeout) as resp:
            search_data = json.loads(resp.read().decode('utf-8'))

        candidates = [r['id'] for r in search_data.get('search', [])]
        if not candidates:
            return LookupResult(status=STATUS_UNKNOWN, source='wikidata')

        # Шаг 2: получить claims P31 (тип) и P21 (пол) для кандидатов
        params2 = urllib.parse.urlencode({
            'action': 'wbgetentities',
            'ids':    '|'.join(candidates),
            'props':  'claims',
            'format': 'json',
        })
        req2 = urllib.request.Request(
            WIKIDATA_API_URL + '?' + params2,
            headers={'User-Agent': _UA},
        )
        with urllib.request.urlopen(req2, timeout=self._timeout) as resp:
            entity_data = json.loads(resp.read().decode('utf-8'))

        entities = entity_data.get('entities', {})
        for qid in candidates:
            entity = entities.get(qid, {})
            claims = entity.get('claims', {})

            # Проверить P31 (instance of) = Q5 (human)
            p31 = claims.get('P31', [])
            is_human = any(
                c.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id') == 'Q5'
                for c in p31
            )
            if not is_human:
                continue

            # Получить P21 (sex or gender)
            for claim in claims.get('P21', []):
                gender_id = (
                    claim.get('mainsnak', {})
                         .get('datavalue', {})
                         .get('value', {})
                         .get('id', '')
                )
                if gender_id in _MALE:
                    return LookupResult(
                        gender_ru='Муж.', probability=1.0,
                        status=STATUS_FOUND, source='wikidata',
                    )
                if gender_id in _FEMALE:
                    return LookupResult(
                        gender_ru='Жен.', probability=1.0,
                        status=STATUS_FOUND, source='wikidata',
                    )

        return LookupResult(status=STATUS_UNKNOWN, source='wikidata')

    # ── Итоговый выбор ────────────────────────────────────────────────────────

    def _select_result(self, author: str) -> Tuple[str, 'LookupResult']:
        """Выбрать лучший результат для автора из кеша.

        Приоритет: Wikidata (если нашёл) > Genderize found > uncertain >
                   unknown > rate_limit > error
        """
        parts = [w for w in author.split() if w]

        # Проверяем Wikidata-результат по полному имени
        wd_key = '_wd_' + author.lower()
        with self._lock:
            wd = self._cache.get(wd_key)

        if wd and wd.status in (STATUS_FOUND, STATUS_UNCERTAIN):
            # Имя слово: берём то из частей, которое сервис нашёл.
            # Для Wikidata ищем по полному имени — возвращаем первое слово
            # (чаще всего имя) как name_word, чтобы показать пользователю.
            name_word = self._best_name_word(parts)
            return name_word, wd

        # Ищем по отдельным словам (Genderize-результаты)
        best_word: str = parts[0] if parts else author
        best_r: Optional['LookupResult'] = None

        for word in parts:
            key = word.lower()
            with self._lock:
                r = self._cache.get(key)
            if r is None:
                continue
            if r.status == STATUS_RATE_LIMIT:
                best_word, best_r = word, r
                break
            if r.status == STATUS_ERROR:
                if best_r is None:
                    best_word, best_r = word, r
                continue
            if r.status == STATUS_UNKNOWN:
                if best_r is None:
                    best_word, best_r = word, r
                continue
            if (best_r is None
                    or best_r.status not in (STATUS_FOUND, STATUS_UNCERTAIN)
                    or r.probability > best_r.probability):
                best_word, best_r = word, r

        # Если Wikidata дал unknown — не портим "лучший" Genderize-результат
        if best_r is None:
            best_r = LookupResult(status=STATUS_UNKNOWN)

        return best_word, best_r

    def _best_name_word(self, parts: List[str]) -> str:
        """Вернуть наиболее вероятное имя из слов автора для отображения.

        При ответе от Wikidata нам нужно показать слово из кириллики.
        Берём слово с наивысшим individual вероятностью из genderize-кеша,
        либо второе слово (классическое "Фамилия Имя[Отчество]"), либо первое.
        """
        best_w, best_p = None, -1.0
        for w in parts:
            with self._lock:
                r = self._cache.get(w.lower())
            if r and r.status in (STATUS_FOUND, STATUS_UNCERTAIN):
                if r.probability > best_p:
                    best_w, best_p = w, r.probability
        if best_w:
            return best_w
        return parts[1] if len(parts) >= 2 else parts[0]

    # ── Кеш-хелперы ──────────────────────────────────────────────────────────

    def _in_cache(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def _set_cache(self, key: str, result: 'LookupResult') -> None:
        with self._lock:
            self._cache[key] = result

    def _pick_best_from_cache(self, author: str) -> Optional['LookupResult']:
        """Быстрая проверка: есть ли в кеше хороший результат для автора."""
        best: Optional[LookupResult] = None
        for w in author.split():
            with self._lock:
                r = self._cache.get(w.lower())
            if r is None:
                continue
            if r.status in (STATUS_FOUND, STATUS_UNCERTAIN):
                return r
            if best is None:
                best = r
        return best

