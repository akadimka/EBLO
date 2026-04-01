#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Онлайн-определение пола автора через Wikidata.

Источник: Wikidata MediaWiki API
  Шаг 1: wbsearchentities — текстовый поиск по индексу
  Шаг 2: wbgetentities    — P31 (человек) + P21 (пол) + labels (имя)

Кеш:
  In-memory кеш на всю сессию. Найденный результат повторно не запрашивается.

Пауза:
  WIKIDATA_DELAY секунд между последовательными запросами (politeness policy).
"""

import time
import urllib.request
import urllib.parse
import json
import threading
from typing import Dict, List, Tuple, Callable, Optional

# ── Константы ────────────────────────────────────────────────────────────────
WIKIDATA_API_URL  = "https://www.wikidata.org/w/api.php"
DEFAULT_TIMEOUT   = 10      # секунд
WIKIDATA_DELAY    = 1.1     # секунд между запросами к Wikidata

# ── Статусы строки в NamesDialog ─────────────────────────────────────────────
STATUS_PENDING    = 'pending'      # запрос отправлен
STATUS_FOUND      = 'found'        # пол определён
STATUS_UNCERTAIN  = 'uncertain'    # зарезервировано
STATUS_UNKNOWN    = 'unknown'      # имя не найдено в Wikidata
STATUS_ERROR      = 'error'        # ошибка сети/парсинга
STATUS_RATE_LIMIT = 'rate_limit'   # зарезервировано


# ── Результат ─────────────────────────────────────────────────────────────────

class LookupResult:
    """Результат определения пола для одного слова."""

    __slots__ = ('gender_ru', 'probability', 'status', 'error', 'source', 'first_name')

    def __init__(
        self,
        gender_ru: Optional[str] = None,
        probability: float = 0.0,
        status: str = STATUS_UNKNOWN,
        error: str = '',
        source: str = '',          # 'genderize' | 'wikidata' | ''
        first_name: str = '',      # только имя (не фамилия), из Wikidata label
    ):
        self.gender_ru   = gender_ru
        self.probability = probability
        self.status      = status
        self.error       = error
        self.source      = source
        self.first_name  = first_name


# ── Основной сервис ───────────────────────────────────────────────────────────

class GenderLookupService:
    """Потокобезопасный сервис определения пола через Wikidata.

    Один экземпляр на приложение — кеш общий для всех вызовов.
    Параметр api_key игнорируется (оставлен для совместимости).
    """

    def __init__(self, api_key: str = '', timeout: int = DEFAULT_TIMEOUT):
        self._timeout    = timeout
        self._cache: Dict[str, LookupResult] = {}
        self._lock       = threading.Lock()
        self._wd_lock    = threading.Lock()  # сериализует Wikidata-запросы
        self._last_wd_ts = 0.0

    # ── Публичный API ─────────────────────────────────────────────────────────

    def lookup_authors_async(
        self,
        items: List[Tuple[int, str]],
        on_result: Callable[[int, str, 'LookupResult'], None],
        on_done:   Callable[[bool], None],
    ) -> None:
        """Асинхронный lookup (не блокирует UI).

        on_result(row_idx, name_word, result) — для каждого автора.
        on_done(rate_limited) — когда все проверки завершены (rate_limited всегда False).
        """
        threading.Thread(
            target=self._worker,
            args=(items, on_result, on_done),
            daemon=True,
        ).start()

    # ── Рабочий поток ────────────────────────────────────────────────────────

    def _worker(self, items, on_result, on_done):
        """Последовательный Wikidata-поиск для каждого автора."""
        for row_idx, author in items:
            wd_key = '_wd_' + author.lower()
            if not self._in_cache(wd_key):
                self._throttle_wikidata()
                try:
                    r = self._wikidata_lookup(author)
                except Exception as exc:
                    r = LookupResult(status=STATUS_ERROR, error=str(exc))
                self._set_cache(wd_key, r)

        for row_idx, author in items:
            name_word, result = self._select_result(author)
            try:
                on_result(row_idx, name_word, result)
            except Exception:
                pass

        try:
            on_done(False)
        except Exception:
            pass

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

        # Шаг 2: получить claims P31/P21 и русский label для кандидатов
        params2 = urllib.parse.urlencode({
            'action':    'wbgetentities',
            'ids':       '|'.join(candidates),
            'props':     'claims|labels',
            'languages': 'ru|en',
            'format':    'json',
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
            labels = entity.get('labels', {})

            # Проверить P31 (instance of) = Q5 (human)
            p31 = claims.get('P31', [])
            is_human = any(
                c.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id') == 'Q5'
                for c in p31
            )
            if not is_human:
                continue

            # Извлечь имя из русского (или английского) лейбла: первое слово
            label_text = (
                labels.get('ru') or labels.get('en') or {}
            ).get('value', '')
            first_name = label_text.split()[0] if label_text else ''

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
                        first_name=first_name,
                    )
                if gender_id in _FEMALE:
                    return LookupResult(
                        gender_ru='Жен.', probability=1.0,
                        status=STATUS_FOUND, source='wikidata',
                        first_name=first_name,
                    )

        return LookupResult(status=STATUS_UNKNOWN, source='wikidata')

    # ── Итоговый выбор ────────────────────────────────────────────────────────

    def _select_result(self, author: str) -> Tuple[str, 'LookupResult']:
        """Вернуть (name_word, result) для автора из кеша Wikidata."""
        parts = [w for w in author.split() if w]
        wd_key = '_wd_' + author.lower()
        with self._lock:
            result = self._cache.get(wd_key)
        if result is None:
            result = LookupResult(status=STATUS_UNKNOWN)

        # Имя: из Wikidata label, иначе второе слово (Фамилия Имя), иначе первое
        if result.first_name:
            name_word = result.first_name
        elif len(parts) >= 2:
            name_word = parts[1]
        else:
            name_word = parts[0] if parts else author

        return name_word, result

    # ── Кеш-хелперы ──────────────────────────────────────────────────────────

    def _in_cache(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def _set_cache(self, key: str, result: 'LookupResult') -> None:
        with self._lock:
            self._cache[key] = result

