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

import difflib
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

    def _transliterate_cyr_to_lat(self, text: str) -> str:
        """Простая побуквенная транслитерация кириллицы в латиницу.

        Используется для поиска авторов, у которых в Wikidata нет русского
        лейбла (например, британские авторы с именем только на английском).
        """
        _MAP = {
            'а': 'a',  'б': 'b',  'в': 'v',  'г': 'g',  'д': 'd',
            'е': 'e',  'ё': 'yo', 'ж': 'zh', 'з': 'z',  'и': 'i',
            'й': 'y',  'к': 'k',  'л': 'l',  'м': 'm',  'н': 'n',
            'о': 'o',  'п': 'p',  'р': 'r',  'с': 's',  'т': 't',
            'у': 'u',  'ф': 'f',  'х': 'kh', 'ц': 'ts', 'ч': 'ch',
            'ш': 'sh', 'щ': 'sch','ъ': '',   'ы': 'y',  'ь': '',
            'э': 'e',  'ю': 'yu', 'я': 'ya',
        }
        return ''.join(_MAP.get(ch, ch) for ch in text.lower())

    def _check_candidates(
        self,
        candidates: List[str],
        author: str,
        filter_mode: str,
        ua: str,
        male_ids: set,
        female_ids: set,
    ) -> Optional['LookupResult']:
        """Загрузить claims+labels для кандидатов, применить фильтр, вернуть пол или None.

        filter_mode:
          'none'           — фильтр по лейблу не применяется (Strategy 1)
          'cyrillic_fuzzy' — нечёткое сравнение кириллических слов с ru/en label (≥ 0.8)
          'translit_fuzzy' — транслитерированные слова vs en label (≥ 0.75)
        """
        if filter_mode == 'translit_fuzzy':
            filter_words = {
                self._transliterate_cyr_to_lat(w)
                for w in author.split() if len(w) >= 2
            }
            fuzzy_threshold = 0.75
        else:
            filter_words = {w.lower() for w in author.split() if len(w) >= 2}
            fuzzy_threshold = 0.8

        def _label_passes(label_words: list) -> bool:
            for w in filter_words:
                if not any(
                    difflib.SequenceMatcher(None, w, lw).ratio() >= fuzzy_threshold
                    for lw in label_words
                ):
                    return False
            return True

        params2 = urllib.parse.urlencode({
            'action':    'wbgetentities',
            'ids':       '|'.join(candidates[:10]),
            'props':     'claims|labels',
            'languages': 'ru|en',
            'format':    'json',
        })
        req2 = urllib.request.Request(
            WIKIDATA_API_URL + '?' + params2,
            headers={'User-Agent': ua},
        )
        with urllib.request.urlopen(req2, timeout=self._timeout) as resp:
            entity_data = json.loads(resp.read().decode('utf-8'))

        entities = entity_data.get('entities', {})
        for qid in candidates:
            entity = entities.get(qid, {})
            if not entity:
                continue
            claims = entity.get('claims', {})
            labels = entity.get('labels', {})

            # P31 = Q5 (human)
            p31 = claims.get('P31', [])
            is_human = any(
                c.get('mainsnak', {}).get('datavalue', {}).get('value', {}).get('id') == 'Q5'
                for c in p31
            )
            if not is_human:
                continue

            # translit_fuzzy → предпочитаем en label; иначе — ru
            if filter_mode == 'translit_fuzzy':
                label_text = (labels.get('en') or labels.get('ru') or {}).get('value', '')
            else:
                label_text = (labels.get('ru') or labels.get('en') or {}).get('value', '')

            if filter_mode != 'none':
                if not _label_passes(label_text.lower().split()):
                    continue

            first_name = label_text.split()[0] if label_text else ''

            for claim in claims.get('P21', []):
                gender_id = (
                    claim.get('mainsnak', {})
                         .get('datavalue', {})
                         .get('value', {})
                         .get('id', '')
                )
                if gender_id in male_ids:
                    return LookupResult(
                        gender_ru='Муж.', probability=1.0,
                        status=STATUS_FOUND, source='wikidata',
                        first_name=first_name,
                    )
                if gender_id in female_ids:
                    return LookupResult(
                        gender_ru='Жен.', probability=1.0,
                        status=STATUS_FOUND, source='wikidata',
                        first_name=first_name,
                    )
        return None

    def _wikidata_lookup(self, author: str) -> 'LookupResult':
        """Wikidata MediaWiki API: ищем человека по имени, возвращаем пол.

        Стратегия 1: wbsearchentities по полному имени на русском.
        Стратегия 2: fulltext (list=search) по самому длинному слову (русский).
            Фильтр: ru/en label кандидата нечётко совпадает со всеми словами
            автора (SequenceMatcher ≥ 0.8 на каждое слово).
            Позволяет найти «Наоми Олдерман» → «Наоми Алдерман».
        Стратегия 3: транслитерация кириллицы → поиск на английском.
            Используется когда у автора в Wikidata нет русского лейбла.
            Пример: «Миллингтон Мил» → «Mil Millington» / «Millington Mil».
            Пробуются оба порядка слов (в рус. форматировании фамилия идёт
            первой, в английском — имя первым); если нет попадания —
            fulltext по самому длинному транслитерированному слову.
            Фильтр: английский label нечётко совпадает с транслитерацией (≥ 0.75).
        Каждая стратегия немедленно проверяет своих кандидатов через _check_candidates.
        Если матч найден — возврат, иначе запускается следующая стратегия.
        """
        _UA     = 'EBookLibraryOrganizer/1.0 (github.com/akadimka/EBLO)'
        _MALE   = {'Q6581097', 'Q44148', 'Q2443246'}
        _FEMALE = {'Q6581072', 'Q2449503', 'Q1052281'}

        # ── Стратегия 1: wbsearchentities, полное имя, язык ru ───────────────
        cands = self._wb_search(author, 'ru', _UA, limit=5)
        if cands:
            result = self._check_candidates(cands, author, 'none', _UA, _MALE, _FEMALE)
            if result:
                return result

        # ── Стратегия 2: fulltext по самому длинному слову (кириллица) ───────
        words = [w for w in author.split() if len(w) >= 3]
        pivot = max(words, key=len) if words else author
        cands = self._wb_fulltext_search(pivot, _UA, limit=10)
        if cands:
            result = self._check_candidates(cands, author, 'cyrillic_fuzzy', _UA, _MALE, _FEMALE)
            if result:
                return result

        # ── Стратегия 3: транслитерация → поиск на английском ────────────────
        t_words = [self._transliterate_cyr_to_lat(w) for w in author.split()]
        t_fwd = ' '.join(t_words)           # «millington mil»
        t_rev = ' '.join(reversed(t_words)) # «mil millington»
        for t_query in [t_fwd, t_rev]:
            cands = self._wb_search(t_query, 'en', _UA, limit=5)
            if cands:
                result = self._check_candidates(cands, author, 'translit_fuzzy', _UA, _MALE, _FEMALE)
                if result:
                    return result
        # Также пробуем fulltext по самому длинному транслитерированному слову
        pivot_t = max(t_words, key=len) if t_words else ''
        if pivot_t:
            cands = self._wb_fulltext_search(pivot_t, _UA, limit=10)
            if cands:
                result = self._check_candidates(cands, author, 'translit_fuzzy', _UA, _MALE, _FEMALE)
                if result:
                    return result

        return LookupResult(status=STATUS_UNKNOWN, source='wikidata')

    def _wb_search(self, query: str, lang: str, ua: str, limit: int = 5) -> List[str]:
        """Вернуть список QID из wbsearchentities (поиск по labels/aliases)."""
        params = urllib.parse.urlencode({
            'action':   'wbsearchentities',
            'search':   query,
            'language': lang,
            'type':     'item',
            'limit':    str(limit),
            'format':   'json',
        })
        req = urllib.request.Request(
            WIKIDATA_API_URL + '?' + params,
            headers={'User-Agent': ua},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return [r['id'] for r in data.get('search', [])]

    def _wb_fulltext_search(self, query: str, ua: str, limit: int = 10) -> List[str]:
        """Полнотекстовый поиск по Wikidata (действие list=search)."""
        params = urllib.parse.urlencode({
            'action':      'query',
            'list':        'search',
            'srsearch':    query,
            'srnamespace': '0',
            'srlimit':     str(limit),
            'format':      'json',
        })
        req = urllib.request.Request(
            WIKIDATA_API_URL + '?' + params,
            headers={'User-Agent': ua},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return [r['title'] for r in data.get('query', {}).get('search', [])]

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

